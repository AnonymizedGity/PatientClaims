"""Run dialogues between the study doctor and the patient (design S1VRFm2), and write them in the common format
(results/README.md). Resumable: finished dialogues are skipped, errors are retried. Several processes (for
example two jobs serving the same model) can work on the same run folder: each dialogue is claimed with a lock file
first, so none is run twice.

    python -B -m sim.run --design S1VRFm2 --base-url http://127.0.0.1:PORT/v1 --eval-dir EVAL_DIR --out runs/NAME

The doctor runs on the patient's server unless --doctor-base-url names its own (another model as the doctor): its
requests stay as simulator/README.md describes them, sent to that server without the Qwen thinking switch.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from .conditions import Condition, Run
from .data import ARMS, DATASETS, load_cases, load_findings, parse_versions, study_ids
from .doctor import CLOSING, MAX_QUESTIONS, TESTS_KINDS, Doctor, DoctorFormatError, as_message, results_message
from .llm import Client
from .patient import (NAME, STILL_WORRIED, WORRY, Controller, Opening, Stats, make_block_opening, make_opening,
                      prompt_hashes, strip_worry, told_before)

ROOT = Path(__file__).resolve().parents[1]
LOCK_STALE = 300      # seconds without a refresh after which a claim is taken to belong to a process that died
LOCK_REFRESH = 60     # how often a live process refreshes the claims it holds
_held: set[Path] = set()
_held_guard = threading.Lock()


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_json(path: Path, value) -> None:
    tmp = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def claim(lock: Path) -> bool:
    """Claim a dialogue for this process; False if another live process holds it."""
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            if time.time() - lock.stat().st_mtime < LOCK_STALE:
                return False
            lock.unlink()                     # a stale claim: its process died
        except FileNotFoundError:
            pass
        return claim(lock)
    with os.fdopen(fd, "w") as f:
        f.write(f"{socket.gethostname()} job {os.environ.get('SLURM_JOB_ID', '-')} pid {os.getpid()} {now()}\n")
    with _held_guard:
        if not any(t.name == "refresh-claims" for t in threading.enumerate()):
            threading.Thread(target=refresh_claims, name="refresh-claims", daemon=True).start()
        _held.add(lock)
    return True


def release(lock: Path) -> None:
    with _held_guard:
        _held.discard(lock)
    lock.unlink(missing_ok=True)


def refresh_claims() -> None:
    """Touch this process's claims, so a claim goes stale only when its process has died (a time limit, a crash)."""
    while True:
        time.sleep(LOCK_REFRESH)
        with _held_guard:
            held = list(_held)
        for lock in held:
            try:
                os.utime(lock)
            except FileNotFoundError:
                pass


def code_commit() -> str:
    if (ROOT / "COMMIT").exists():
        return (ROOT / "COMMIT").read_text(encoding="utf-8").strip()
    try:
        out = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10)
        dirty = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain"], capture_output=True, text=True,
                               timeout=10).stdout.strip()
        return out.stdout.strip() + ("+dirty" if dirty else "")
    except (OSError, subprocess.SubprocessError):
        return "unknown"


BLOCK_PROMPTS = ("task.md", "arm_control.md", "opening_blocks.md", "opening_check.md", "checker_record.md",
                 "redraft.md", "reply_rules.md")


def get_opening(client: Client, case, seed: int, folder: Path, model: str, ids: list | None = None) -> Opening:
    """One opening per case and seed, shared by the arms and by every run (and job) pointed at the same folder.
    The file is keyed by the model, the opening's prompts, the release and the opening facts' texts (a new data
    version gets new openings); the first writer wins, so concurrent runs agree. With ids (A13), the opening says
    those facts, checked, and is keyed by them and by its own prompts."""
    prompts = prompt_hashes()
    facts = {f["id"]: f["text"] for f in case.facts}
    if ids is None:
        key = {"model": model, "prompts": {k: prompts[k] for k in ("task.md", "arm_control.md", "opening.md")},
               "release": case.release, "opening": [facts[i] for i in case.opening]}
    else:
        key = {"model": model, "prompts": {k: prompts[k] for k in BLOCK_PROMPTS}, "release": case.release,
               "opening": [facts[i] for i in ids], "kind": "blocks"}
    tag = hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()[:10]
    path = folder / f"{case.case_id}__s{seed}__{tag}.json"
    if not path.exists():
        opening = make_opening(client, case, seed) if ids is None else make_block_opening(client, case, seed, ids)
        tmp = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps({"case_id": case.case_id, "seed": seed, "key": key, "opening": opening.__dict__},
                                  ensure_ascii=False, indent=1), encoding="utf-8")
        try:
            os.link(tmp, path)          # atomic: fails if another run wrote it first
        except FileExistsError:
            pass
        finally:
            tmp.unlink()
    return Opening(**json.loads(path.read_text(encoding="utf-8"))["opening"])


def run_dialogue(case, arm: str, seed: int, opening: Opening, design, doctor: Doctor,
                 condition: Run | None = None, tests: dict | None = None) -> dict:
    """One dialogue. With a condition (sim/conditions.py) its spec is fixed first, and each turn logs what the
    condition planned, what decided it and what was said. With tests ({"findings", "labels"}, variant T; the regime is
    the doctor's), the doctor can retrieve the findings once: that turn is a doctor turn (its seed counts on) but not
    one of the questions, the patient is not called for it and never sees the results, and it is logged in "tests";
    the finishing turn's re-samples, and a closing requested again past the turn limit, in "closing_log"."""
    stats = Stats(**opening.stats)        # the opening's call counts for every arm that uses it
    phrase = case.anchor["phrase"] if arm != "control" else None
    sentence = condition.opening_sentence() if condition else (WORRY.format(phrase=phrase) if phrase else None)
    first = opening.text + (" " + sentence if sentence else "")
    opening_facts = (condition and condition.opening_ids()) or list(case.opening)
    turns = [{"doctor": None, "patient": first, "internal": {"opening": opening.internal,
                                                             "worry_appended": bool(phrase)}}]
    if condition:
        turns[0]["internal"]["condition"] = condition.opening_log(opening_facts)
    disclosed = [{"turn": 0, "facts": list(opening_facts)}]
    history = [{"role": "user", "content": first}]
    closing, final, stop, error_detail, message = None, None, None, None, None
    tests_log = {"regime": doctor.tests, "requested": False, "doctor_turn": None, "after_questions": None,
                 "shown": [], "hidden": []} if tests else None
    closing_log = {}        # variant T: the doctor's finishing turn's re-samples and extensions
    doctor_turn, question = 0, 0
    try:
        while question < MAX_QUESTIONS:
            doctor_turn += 1
            action, message, resamples, extensions = doctor.turn(
                case.case_id, seed, doctor_turn, case.demographics, history,
                tests_open=bool(tests) and not tests_log["requested"])
            if action == "tests":
                text, shown, hidden = results_message(doctor.tests, tests["findings"], tests["labels"])
                history += [as_message(action, message), {"role": "user", "content": text}]
                tests_log.update(requested=True, doctor_turn=doctor_turn, after_questions=question, shown=shown,
                                 hidden=hidden, message=text)
                if resamples:
                    tests_log["doctor_format_resamples"] = resamples
                if extensions:
                    tests_log["doctor_length_extensions"] = extensions
                continue
            history.append(as_message(action, message))
            if action == "finish":
                closing, stop = message, "doctor_finished"
                if tests and resamples:
                    closing_log["doctor_format_resamples"] = resamples
                if extensions:
                    closing_log["doctor_length_extensions"] = extensions
                break
            question += 1
            if condition:
                result = design.reply(case, arm, turns, disclosed, message, stats,
                                      directive=condition.directive(question, disclosed))
            else:
                result = design.reply(case, arm, turns, disclosed, message, stats)
            text, stripped = strip_worry(result.reply, phrase) if phrase else (result.reply, 0)
            if condition:
                text, more = condition.strip(text)
                stripped += more
                # the condition's own sentences (A15's persistence sentence in place of A1's)
                text, condition_log = condition.after(question, message, result, text, told_before(disclosed))
                appended = condition_log.pop("appended", False)
                if not text:
                    raise RuntimeError(f"empty patient reply at turn {question}: {result.internal.get('problems')}")
            else:
                if not text:
                    raise RuntimeError(f"empty patient reply at turn {question}: {result.internal.get('problems')}")
                # in persistence the fixed sentence follows a dispute and a question about the
                # worry.
                appended = arm == "persistence" and (result.worry_disputed or result.worry_asked)
                if appended:
                    text += " " + STILL_WORRIED.format(phrase=phrase)
            internal = dict(result.internal, worry_disputed=result.worry_disputed, worry_asked=result.worry_asked,
                            worry_appended=appended)
            if condition:
                internal["condition"] = condition_log
            if stripped:
                internal["worry_stripped"] = stripped
            if resamples:
                internal["doctor_format_resamples"] = resamples
            if extensions:
                internal["doctor_length_extensions"] = extensions
            turns.append({"doctor": message, "patient": text, "internal": internal})
            disclosed.append({"turn": question, "facts": result.facts})
            history.append({"role": "user", "content": text})
        else:
            closing, stop = CLOSING, "max_questions"
            history.append(as_message("finish", CLOSING))
        final, retries = doctor.final(case.case_id, seed, case.demographics, history)
        if retries:
            turns[-1]["internal"]["final_format_retries"] = retries
    except DoctorFormatError as error:
        stop = "error:doctor_format"
        error_detail = {"turn": len(turns), "doctor": message, "error": str(error)[:2000]}
        if error.extensions:
            error_detail["doctor_length_extensions"] = error.extensions
    except Exception as error:   # noqa: BLE001 -- recorded in the dialogue, retried on the next run
        stop = f"error:{type(error).__name__}: {error}"[:300]
        error_detail = {"turn": len(turns), "doctor": message, "error": str(error)[:2000]}
        traceback.print_exc()
    dialogue = {"case_id": case.case_id, "dataset": case.dataset, "release": case.release, "arm": arm, "seed": seed,
                "anchor": phrase, "turns": turns, "closing": closing, "final": final, "stop_reason": stop,
                "disclosed": disclosed, "stats": stats.as_dict()}
    if condition:
        dialogue["condition"] = condition.end(len(turns) - 1, stop)
    if tests_log:
        tests_log["doctor_turns"] = doctor_turn
        dialogue["tests"] = tests_log
    if closing_log:
        dialogue["closing_log"] = closing_log
    if error_detail:
        dialogue["error_detail"] = error_detail
    return dialogue


def load_tests(regime: str, tests_dir: Path, releases: Path, versions: dict, cases: list) -> tuple[dict, dict]:
    """Variant T: case id -> {"findings", "labels"}, and the label files read (path, sha256). Every finding of the
    regime's kinds must have a label from a compile of the same release."""
    tests, files = {}, {}
    for dataset in dict.fromkeys(c.dataset for c in cases):
        path = tests_dir / f"{dataset}.json"
        raw = path.read_bytes()
        labels = json.loads(raw)
        files[dataset] = {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()[:12]}
        findings = load_findings(releases, dataset, versions.get(dataset))
        for case in (c for c in cases if c.dataset == dataset):
            if labels.get("release") != case.release:
                raise SystemExit(f"{path}: labels for release {labels.get('release')}, not {case.release}")
            mine = labels["cases"].get(case.case_id, {})
            missing = [f["id"] for f in findings.get(case.case_id, []) if f["kind"] in TESTS_KINDS[regime]
                       and f["id"] not in mine]
            if missing:
                raise SystemExit(f"{path}: {case.case_id} has no label for {missing}")
            tests[case.case_id] = {"findings": findings.get(case.case_id, []), "labels": mine}
    return tests, files


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--design", choices=[NAME], default=NAME, help="the patient design (only S1VRFm2 here)")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", default="local", help="model name on the server")
    parser.add_argument("--model-id", default="", help="the real model behind the server, for run.json")
    parser.add_argument("--no-thinking-switch", action="store_true", help="do not send enable_thinking")
    parser.add_argument("--eval-dir", type=Path, required=True, help="the evaluation files, e.g. data/ (main/, anchors/, data/releases/)")
    parser.add_argument("--releases", type=Path, help="default: <eval-dir>/data/releases")
    parser.add_argument("--versions", default="", help="release version per dataset, e.g. medqa_cs=5eeb1bcf7230,... "
                        "(needed when a dataset has several versions in --releases)")
    parser.add_argument("--datasets", default=",".join(DATASETS))
    parser.add_argument("--cases", default="", help="comma-separated case ids (default: all study cases)")
    parser.add_argument("--limit", type=int, default=0, help="first N cases per dataset (smoke tests)")
    parser.add_argument("--arms", default=",".join(ARMS))
    parser.add_argument("--seeds", default="1")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--openings", type=Path, help="shared openings folder (default: <out>/openings)")
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--openings-only", action="store_true",
                        help="only make the openings (run once before the runs that share them)")
    parser.add_argument("--condition", default="", help="a patient-behaviour condition PATTERN:LEVEL "
                        "(simulator/README.md, sim/conditions.py), e.g. A15:AI; its arms are taken from --arms")
    parser.add_argument("--conditions-dir", type=Path, help="the compiled per-case data (A12a, A13); "
                        "default <eval-dir>/conditions")
    parser.add_argument("--doctor-base-url", default="", help="the doctor's own server (default: the patient's)")
    parser.add_argument("--doctor-model", default="", help="model name on the doctor's server (default: the first "
                        "model it serves)")
    parser.add_argument("--doctor-model-id", default="", help="the real model behind the doctor's server, for run.json")
    parser.add_argument("--doctor-thinking-switch", action="store_true", help="send enable_thinking to the doctor's "
                        "own server too (a Qwen doctor); off by default, since other templates do not know it")
    parser.add_argument("--tests", choices=["TT", "TE"], help="variant T (simulator/README.md): the doctor can "
                        "retrieve the findings once; TT test results, TE also vital signs and examination findings")
    parser.add_argument("--tests-dir", type=Path, help="the per-finding labels (sim/compile_tests.py), "
                        "<dataset>.json; default <eval-dir>/tests")
    args = parser.parse_args()

    releases = args.releases or args.eval_dir / "data" / "releases"
    client = Client(args.base_url, args.model, thinking_switch=not args.no_thinking_switch)
    design = Controller(client)
    doctor_client, doctor_served = client, None
    if args.doctor_base_url:
        doctor_client = Client(args.doctor_base_url, args.doctor_model or "local",
                               thinking_switch=args.doctor_thinking_switch)
        try:
            listed = doctor_client.models().get("data", [])
        except Exception:   # noqa: BLE001
            listed = []
        doctor_served = [m.get("root") or m.get("id") for m in listed]
        if not args.doctor_model and listed:
            doctor_client.model = listed[0]["id"]
    doctor = Doctor(doctor_client, tests=args.tests)
    arms = args.arms.split(",")
    seeds = [int(s) for s in args.seeds.split(",")]
    wanted = set(args.cases.split(",")) if args.cases else None
    versions = parse_versions(args.versions)
    cases = []
    for dataset in args.datasets.split(","):
        ids = study_ids(args.eval_dir, dataset)
        ids = [i for i in ids if wanted is None or i in wanted]
        cases += load_cases(args.eval_dir, releases, dataset, ids[:args.limit] if args.limit else ids,
                            version=versions.get(dataset))
    condition = None
    if args.condition:
        condition = Condition.parse(args.condition, args.conditions_dir or args.eval_dir / "conditions",
                                    dict.fromkeys(c.dataset for c in cases))
        jobs = [(case, arm, seed) for case in cases for seed in seeds for arm in arms if condition.applies(case, arm)]
    else:
        jobs = [(case, arm, seed) for case in cases for seed in seeds for arm in arms
                if arm == "control" or case.anchor]

    tests, tests_files = {}, {}
    if args.tests and not args.openings_only:
        tests, tests_files = load_tests(args.tests, args.tests_dir or args.eval_dir / "tests", releases, versions, cases)

    openings = args.openings or args.out / "openings"
    openings.mkdir(parents=True, exist_ok=True)
    try:
        served = [m.get("root") or m.get("id") for m in client.models().get("data", [])]
    except Exception:   # noqa: BLE001
        served = []
    model_key = args.model_id or ",".join(served) or args.model
    if args.openings_only:
        pairs = {(c.case_id, s): (c, s) for c, _, s in jobs}
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for future in as_completed([pool.submit(get_opening, client, c, s, openings, model_key)
                                        for c, s in pairs.values()]):
                future.result()
        print(f"{now()} openings ready: {len(pairs)} in {openings}", flush=True)
        return
    dialogues = args.out / "dialogues"
    dialogues.mkdir(parents=True, exist_ok=True)
    run = {"design": design.name, "presentation": "P1", "code_commit": code_commit(),
           "prompt_files": {f"prompts/{k}": v for k, v in prompt_hashes().items()},
           "models": {"patient": {"base_url": args.base_url, "model": args.model, "model_id": args.model_id,
                                  "served": served},
                      "doctor": {"same_server_as_patient": True, "model": args.model, "model_id": args.model_id}
                      if not args.doctor_base_url else
                      {"base_url": args.doctor_base_url, "model": doctor_client.model, "model_id": args.doctor_model_id,
                       "served": doctor_served, "thinking_switch": args.doctor_thinking_switch}},
           "release": {c.dataset: c.release for c in cases}, "split": "main",
           "cases": {d: [c.case_id for c in cases if c.dataset == d] for d in dict.fromkeys(c.dataset for c in cases)},
           "arms": arms, "seeds": seeds, "openings": str(openings), "start": now(), "end": None}
    if condition:
        run["condition"] = {"name": condition.name, "data_files": condition.files}
    if args.tests:
        run["tests"] = {"regime": args.tests, "kinds": list(TESTS_KINDS[args.tests]), "label_files": tests_files}
    run_file = args.out / "run.json"
    if run_file.exists():
        run["start"] = json.loads(run_file.read_text(encoding="utf-8")).get("start", run["start"])
    write_json(run_file, run)
    process = (f"{socket.gethostname()} job {os.environ.get('SLURM_JOB_ID', '-')} pid {os.getpid()} {args.base_url}"
               + (f" doctor {args.doctor_base_url}" if args.doctor_base_url else ""))
    with open(args.out / "processes.log", "a", encoding="utf-8") as log:
        log.write(f"{now()} start {process} seeds {args.seeds}\n")

    def path_of(case, arm, seed) -> Path:
        return dialogues / f"{case.case_id}__{arm}__s{seed}.json"

    def done(case, arm, seed) -> bool:
        path = path_of(case, arm, seed)
        return path.exists() and not json.loads(path.read_text(encoding="utf-8"))["stop_reason"].startswith("error")

    def work(case, arm, seed) -> dict | None:
        """Run one dialogue unless another process has claimed it or finished it meanwhile."""
        path = path_of(case, arm, seed)
        lock = path.with_suffix(".lock")
        if not claim(lock):
            return None
        try:
            if done(case, arm, seed):
                return None
            result = run_dialogue(case, arm, seed, opening[(case.case_id, seed)], design, doctor,
                                  Run(condition, case, arm) if condition else None, tests.get(case.case_id))
            write_json(path, result)
            return result
        finally:
            release(lock)

    todo = [j for j in jobs if not done(*j)]
    print(f"{now()} {design.name}: {len(jobs)} dialogues, {len(jobs) - len(todo)} already done", flush=True)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        needed = {(c.case_id, s): (c, a, s) for c, a, s in todo}
        # A13: the opening says the planned blocks' facts, so it is made (and kept) apart from the shared one
        futures = {pool.submit(get_opening, client, c, s, openings, model_key,
                               Run(condition, c, a).opening_ids() if condition else None): key
                   for key, (c, a, s) in needed.items()}
        opening = {}
        for future in as_completed(futures):
            try:
                opening[futures[future]] = future.result()
            except Exception as error:   # noqa: BLE001 -- its dialogues stay undone and are retried next run
                print(f"{now()} opening failed for {futures[future]}: {error}", flush=True)
        futures = {pool.submit(work, c, a, s): (c, a, s) for c, a, s in todo if (c.case_id, s) in opening}
        finished = 0
        for future in as_completed(futures):
            case, arm, seed = futures[future]
            result = future.result()
            if result is None:
                continue
            finished += 1
            print(f"{now()} {finished} done here ({len(todo)} were open) {case.case_id}__{arm}__s{seed} "
                  f"turns={len(result['turns'])} stop={result['stop_reason']} calls={result['stats']['calls']}",
                  flush=True)
    pending = sum(not done(*j) for j in jobs)
    errors = sum(path_of(*j).exists() and not done(*j) for j in jobs)
    run.update(end=now(), dialogues={"total": len(jobs), "not_done": pending, "errors": errors})
    write_json(run_file, run)
    with open(args.out / "processes.log", "a", encoding="utf-8") as log:
        log.write(f"{now()} end {process}: {finished} dialogues here, {pending} not done ({errors} errors)\n")
    print(f"{now()} finished: {len(jobs) - pending}/{len(jobs)} dialogues complete, {errors} errors, "
          f"{pending - errors} with another process or failed to start", flush=True)
    sys.exit(1 if pending else 0)


if __name__ == "__main__":
    main()
