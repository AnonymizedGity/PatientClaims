"""The per-finding labels of the tests-available axis (simulator/README.md), made once before
the runs: every finding of every kind in the release's environment file (vital signs, examination findings, test
results) gets "names", "confirms" or "other", judged against the case's gold diagnosis. Code labels "names" where the
shared scorer's matcher (<eval-dir>/tools/score.py) finds the gold or an alias in the result; the
model labels the rest, one schema-forced call per finding, given only the finding, the gold diagnosis and a fixed
instruction (prompts/compile_findings.md). Written to <out>/<dataset>.json; a file that already holds every finding is
kept.

With --base (an earlier compile), its labels are kept and a second, stricter pass
(prompts/compile_findings_pass2.md) looks again at each examination or test finding
it labelled "other": it can move a finding to "names" or "confirms" ("by": "model-pass2"), never back. --overrides
labels given findings by hand, last. A changed label keeps the first compile's under "base"; every finding pass 2
looked at has its answer under "pass2"; <out>/<dataset>_changes.tsv lists the labels that differ from --base's. With
--no-pass2 the base's labels are copied as they are (no model calls) and only the overrides change them.

    python -B -m sim.compile_tests --base-url http://127.0.0.1:PORT/v1 --eval-dir EVAL_DIR --releases ... \\
        --versions ... --datasets agentclinic,medcasereasoning,medqa_cs --out tests
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .data import load_cases, load_findings, parse_versions, read_jsonl, release_dir, study_ids
from .llm import Client
from .patient import StepFailed, Stats, derive_seed, prompt, prompt_hashes, structured
from .run import code_commit, now, write_json

LABELS = ("names", "confirms", "other")
KIND_WORDS = {"vital": "vital sign", "exam": "physical examination finding", "test": "test result"}
PASS2_KINDS = ("exam", "test")      # pass 2 skips vital signs


def scorer(eval_dir: Path):
    """The study's scorer module (its `matches` is the name matcher every outcome uses)."""
    spec = importlib.util.spec_from_file_location("study_score", eval_dir / "tools" / "score.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def gold_names(gold: dict) -> list:
    """The gold diagnosis and its aliases, as the scorer reads them (longer than 2 characters)."""
    return [n for n in [gold.get("diagnosis", ""), *gold.get("aliases", [])] if len(n) > 2]


def ask_model(client: Client, instruction: str, case_id: str, step: str, finding: dict, gold: dict) -> tuple:
    """One label call: (label, reason, problems). Unusable output gives "names" (hidden), flagged."""
    also = [n for n in gold.get("aliases", []) if n]
    when = f" ({finding['time']})" if finding.get("time") else ""
    user = "\n".join([f"Correct diagnosis: {gold['diagnosis']}" + (f" (also called: {', '.join(also)})" if also else ""),
                      f"Finding ({KIND_WORDS.get(finding['kind'], finding['kind'])}){when}: "
                      f"{finding['name']}: {finding['result']}"])
    schema = {"type": "object", "properties": {"reason": {"type": "string"}, "label": {"enum": list(LABELS)}},
              "required": ["reason", "label"], "additionalProperties": False}
    try:
        value, problems = structured(client, prompt(instruction), user, schema, Stats(), max_tokens=400,
                                     check=lambda v: [] if v.get("label") in LABELS else ["label must be names, "
                                                                                         "confirms or other"],
                                     temperature=0.0, seed=derive_seed(case_id, step, finding["id"]))
    except StepFailed as error:
        value, problems = {}, [str(error)]
    label = value.get("label") if value.get("label") in LABELS else "names"
    return label, value.get("reason", ""), problems


def label_finding(client: Client, case_id: str, finding: dict, gold: dict, names: list, matches) -> dict:
    hit = next((n for n in names if matches(n, finding["result"])), None)
    out = {"kind": finding["kind"], "name": finding["name"]}
    if hit:
        return {**out, "label": "names", "by": "scorer", "reason": f'the scorer\'s matcher finds "{hit}" in the result'}
    label, reason, problems = ask_model(client, "compile_findings", case_id, "findings", finding, gold)
    return {**out, "label": label, "by": "model", "reason": reason, **({"problems": problems} if problems else {})}


def recheck_finding(client: Client, case_id: str, finding: dict, gold: dict, old: dict) -> dict:
    """Pass 2 on a finding the base labelled "other": the stricter instruction can only hide it."""
    label, reason, problems = ask_model(client, "compile_findings_pass2", case_id, "findings_pass2", finding, gold)
    seen = {"label": label, "reason": reason, **({"problems": problems} if problems else {})}
    if label == "other":
        return {**old, "pass2": seen}
    return {"kind": old["kind"], "name": old["name"], "label": label, "by": "model-pass2", "reason": reason,
            "base": {k: old[k] for k in ("label", "by", "reason")}, "pass2": seen}


def write_changes(path: Path, dataset: str, cases: dict, findings: dict, gold: dict, before: dict | None) -> int:
    """The findings whose label (or its author) differs from the --base compile's (before), or without one, that
    keep a "base", one row each, for review."""
    rows = []
    for cid, labels in cases.items():
        by_id = {f["id"]: f for f in findings.get(cid, [])}
        for fid, v in labels.items():
            old = before[cid][fid] if before else v.get("base")
            if old and (not before or (old["label"], old["by"]) != (v["label"], v["by"])):
                f = by_id[fid]
                rows.append([dataset, cid, fid, v["kind"], f["name"], f.get("time") or "", f["result"],
                             gold[cid]["diagnosis"], old["label"], v["label"], v["by"], v["reason"]])
    with open(path, "w", encoding="utf-8", newline="") as out:
        writer = csv.writer(out, delimiter="\t", lineterminator="\n")
        writer.writerow(["dataset", "case_id", "finding", "kind", "name", "time", "result", "gold", "base_label",
                         "label", "by", "reason"])
        writer.writerows([" ".join(str(x).split()) for x in row] for row in rows)
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", default="local")
    parser.add_argument("--model-id", default="")
    parser.add_argument("--no-thinking-switch", action="store_true")
    parser.add_argument("--eval-dir", type=Path, required=True, help="the evaluation files, e.g. data/ (main/, tools/score.py)")
    parser.add_argument("--releases", type=Path)
    parser.add_argument("--versions", default="")
    parser.add_argument("--datasets", default="agentclinic,medcasereasoning,medqa_cs")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--base", type=Path, help="an earlier compile whose labels are kept, with pass 2 over its "
                                                  "examination and test findings labelled other")
    parser.add_argument("--no-pass2", action="store_true", help="with --base: copy its labels as they are, no model "
                                                                "calls (only --overrides change them)")
    parser.add_argument("--overrides", type=Path, help='labels by hand, applied last: JSON {"by", "reason", '
                                                       '"labels": {case id: {finding id: label}}}')
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args()
    releases = args.releases or args.eval_dir / "data" / "releases"
    client = Client(args.base_url, args.model, thinking_switch=not args.no_thinking_switch)
    versions = parse_versions(args.versions)
    score = scorer(args.eval_dir)
    scorer_sha = hashlib.sha256((args.eval_dir / "tools" / "score.py").read_bytes()).hexdigest()[:12]
    overrides, overrides_file = {"labels": {}}, None
    if args.overrides:
        raw = args.overrides.read_bytes()
        overrides = json.loads(raw)
        overrides_file = {"path": str(args.overrides), "sha256": hashlib.sha256(raw).hexdigest()[:12]}
        bad = [f"{cid} {fid}" for cid, fs in overrides["labels"].items() for fid, lab in fs.items() if lab not in LABELS]
        if bad:
            raise SystemExit(f"{args.overrides}: not a label for {bad}")
    if args.no_pass2 and not args.base:
        raise SystemExit("--no-pass2 needs --base")
    used_prompts = ["compile_findings.md"] + (["compile_findings_pass2.md"] if args.base else [])
    datasets = args.datasets.split(",")
    split = {d: study_ids(args.eval_dir, d) for d in datasets}
    unknown = [cid for cid in overrides["labels"] if not any(cid in ids for ids in split.values())]
    if unknown:
        raise SystemExit(f"{args.overrides}: cases not in the datasets: {unknown}")
    args.out.mkdir(parents=True, exist_ok=True)
    for dataset in datasets:
        ids = split[dataset][:args.limit] if args.limit else split[dataset]
        mine = {cid: fs for cid, fs in overrides["labels"].items() if cid in ids}
        release = load_cases(args.eval_dir, releases, dataset, ids[:1], version=versions.get(dataset))[0].release
        findings = load_findings(releases, dataset, versions.get(dataset))
        gold = {r["case_id"]: r for r in read_jsonl(release_dir(releases, dataset, versions.get(dataset))
                                                    / f"{dataset}_gold.jsonl") if r.get("case_id")}
        work = [(cid, f) for cid in ids for f in findings.get(cid, [])]
        absent = [f"{cid} {fid}" for cid, fs in mine.items() for fid in fs
                  if fid not in {f["id"] for f in findings.get(cid, [])}]
        if absent:
            raise SystemExit(f"{args.overrides}: no such findings {absent}")
        path = args.out / f"{dataset}.json"
        if path.exists():
            have = json.loads(path.read_text(encoding="utf-8"))
            if have.get("release") == release and all(f["id"] in have["cases"].get(cid, {}) for cid, f in work):
                print(f"{now()} {path}: all {len(work)} findings there, kept", flush=True)
                continue
        base_file, rechecked, before = None, 0, None
        if args.base:
            raw = (args.base / f"{dataset}.json").read_bytes()
            base = json.loads(raw)
            base_file = {"path": str(args.base / f"{dataset}.json"), "sha256": hashlib.sha256(raw).hexdigest()[:12]}
            missing = [f"{cid} {f['id']}" for cid, f in work if f["id"] not in base["cases"].get(cid, {})]
            if base.get("release") != release or missing:
                raise SystemExit(f"{base_file['path']}: release {base.get('release')} (not {release}) or no label "
                                 f"for {missing[:5]}")
            before = base["cases"]
            olds = [before[cid][f["id"]] for cid, f in work]
            todo = [] if args.no_pass2 else [i for i, ((cid, f), old) in enumerate(zip(work, olds))
                                             if f["kind"] in PASS2_KINDS and old["label"] == "other"]
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                again = list(pool.map(lambda i: recheck_finding(client, work[i][0], work[i][1], gold[work[i][0]],
                                                                olds[i]), todo))
            labelled = list(olds)
            for i, value in zip(todo, again):
                labelled[i] = value
            rechecked = len(todo)
        else:
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                labelled = list(pool.map(lambda w: label_finding(client, w[0], w[1], gold[w[0]],
                                                                 gold_names(gold[w[0]]), score.matches), work))
        cases = {cid: {} for cid in ids}
        for (cid, finding), value in zip(work, labelled):
            cases[cid][finding["id"]] = value
        applied = 0
        for cid, fs in mine.items():
            for fid, lab in fs.items():
                old = cases[cid][fid]
                cases[cid][fid] = {"kind": old["kind"], "name": old["name"], "label": lab, "by": overrides["by"],
                                   "reason": overrides["reason"],
                                   "base": old.get("base") or {k: old[k] for k in ("label", "by", "reason")},
                                   **({"pass2": old["pass2"]} if "pass2" in old else {})}
                applied += 1
        values = [v for c in cases.values() for v in c.values()]
        counts = Counter((v["kind"], v["label"]) for v in values)
        changes = write_changes(args.out / f"{dataset}_changes.tsv", dataset, cases, findings, gold, before) \
            if args.base or args.overrides else 0
        write_json(path, {
            "_note": "Per-finding labels of the tests-available axis (simulator/README.md): names / confirms / "
                     "other against the gold diagnosis; only \"other\" is shown to the doctor. \"by\": scorer (the "
                     "shared matcher found the gold in the result), model, model-pass2 (the stricter second pass, "
                     "which can only hide) or the overrides' author. \"base\": the first compile's label where it "
                     "changed. Spot-check before use.",
            "dataset": dataset, "release": release, "split": "main", "model": args.model_id or args.model,
            "code_commit": code_commit(), "prompts": {f"prompts/{p}": prompt_hashes()[p] for p in used_prompts},
            "scorer": {"path": "tools/score.py", "sha256": scorer_sha}, "created": now(),
            **({"base": base_file, "pass2": {"kinds": [] if args.no_pass2 else list(PASS2_KINDS),
                                             "rechecked": rechecked}} if base_file else {}),
            **({"overrides": {**overrides_file, "applied": applied}} if overrides_file else {}),
            "counts": {f"{k}/{lab}": n for (k, lab), n in sorted(counts.items())}, "changes": changes,
            "cases": cases})
        problems = sum(bool(v.get("problems") or v.get("pass2", {}).get("problems")) for v in values)
        print(f"{now()} {path}: {len(work)} findings in {len(ids)} cases, {dict(Counter(v['label'] for v in values))}, "
              f"by {dict(Counter(v['by'] for v in values))}; " + (f"pass 2 looked at {rechecked}; " if args.base else "")
              + (f"{applied} overrides; " if overrides_file else "") + f"{changes} changed from the base, "
              f"{problems} with problems left after the redrafts", flush=True)


if __name__ == "__main__":
    main()
