"""The per-case data of the patient-behaviour conditions (simulator/README.md), made once before
the runs: the A12a target fact (GOLD), the A12a ANCHOR one (a present fact that fits X) and the A13 block map. The
local model chooses, one schema-forced call per choice; code allows only fitting entries and checks every pick.
Written to <out>/<dataset>.json; a file that already holds every case is kept. With --base (one or more earlier
compiles), their picks are kept as they are; the ANCHOR pick is made again unless the same compile_anchor.md made it
for the same anchor, and a case in no base is compiled in full.

    python -B -m sim.compile_conditions --base-url http://127.0.0.1:PORT/v1 --eval-dir EVAL_DIR --releases ... \
        --versions ... --out conditions [--base OLD_COMPILE [--base ...]]
"""
from __future__ import annotations

import argparse
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .data import DATASETS, Case, fact_line, load_cases, parse_versions, person, read_jsonl, release_dir, \
    study_ids
from .llm import Client
from .patient import Stats, derive_seed, prompt, prompt_hashes, structured
from .run import code_commit, now, write_json

PROMPTS = ("compile_target.md", "compile_blocks.md", "compile_anchor.md")
# A13 blocks 2 and 3 are the complaint's own recorded details: the opening entries'
# details, sorted by the release's own attribute; the model adds only complaint timing that a record keeps as an entry
# of its own (block 2), and blocks 4 and 5.
ATTRIBUTES = {"2": ("onset", "duration"), "3": ("character", "severity")}
GROUPS = {"onset": "2", "associated": "4", "history": "5"}
CAP = {"onset": 2, "associated": 3, "history": 3}


def present(case: Case) -> list:
    """The patient's own present entries outside the opening (DDXPlus: the case's facts, not the checklist)."""
    return [f for f in case.facts if f.get("polarity") == "present" and f["id"] not in case.opening]


def sheet(facts: list, case: Case) -> list:
    """Entry lines, details indented under their entry when it is listed too."""
    ids = {f["id"] for f in facts}
    return [fact_line(f, "    " if f.get("parent") in ids or f.get("parent") in case.opening else "") for f in facts]


def opening_lines(case: Case) -> list:
    facts = {f["id"]: f for f in case.facts}
    return [fact_line(facts[i]) for i in case.opening]


def choose(client: Client, case: Case, step: str, user: str, schema: dict, check) -> tuple[dict, list]:
    system = prompt(step)
    value, problems = structured(client, system, user, schema, Stats(), max_tokens=1200, check=check,
                                 temperature=0.0, seed=derive_seed(case.case_id, "compile", step))
    return value, problems


def compile_anchor(client: Client, case: Case, gold: str | None) -> dict:
    """A12a ANCHOR: the present entry that fits the anchor X best, from the same entries as the GOLD pick, the GOLD
    target excluded; none when no entry fits."""
    if not case.anchor:
        return {"target": None, "reason": "not an anchored case"}
    pool = [f for f in present(case) if ("parent" not in f or f["parent"] in case.opening) and f["id"] != gold]
    ids = [f["id"] for f in pool]
    if not ids:
        return {"target": None, "reason": "no entry to choose from"}
    by_id = {f["id"]: f for f in pool}
    user = "\n".join([f"Patient: {person(case.demographics)}.",
                      f"Condition: {case.anchor['condition']} (the patient's words: {case.anchor['phrase']})", "",
                      "What the patient says first:"] + opening_lines(case) + ["", "Entries to choose from:"]
                     + sheet(pool, case))
    schema = {"type": "object", "properties": {"reason": {"type": "string"}, "target": {"enum": ids + ["none"]}},
              "required": ["reason", "target"], "additionalProperties": False}
    value, problems = choose(client, case, "compile_anchor", user, schema,
                             lambda v: [] if v.get("target") in ids + ["none"] else ["target must be a listed id or none"])
    target = value.get("target") if value.get("target") in ids else None
    return {"target": target, "reason": value.get("reason", ""), "anchor": case.anchor["phrase"],
            **({"item": by_id[target]["item"], "text": by_id[target]["text"]} if target else {}),
            **({"problems": problems} if problems else {})}


def compile_case(client: Client, case: Case, diagnosis: str, base: dict | None = None,
                 keep_anchor: bool = False) -> dict:
    """Every pick of one case; with base (an earlier compile's case), its picks are kept and ANCHOR is made again,
    unless keep_anchor (the base's ANCHOR pick was made by today's prompt for the same anchor)."""
    if base is not None:
        if keep_anchor:
            return base
        return {**base, "a12a_anchor": compile_anchor(client, case, (base.get("a12a") or {}).get("target"))}
    facts = present(case)
    by_id = {f["id"]: f for f in facts}
    head = [f"Patient: {person(case.demographics)}."]
    out = {"problems": []}

    # A12a: the present non-opening entry that points most clearly to the diagnosis; a detail only of the opening's
    # entries, since a detail of a symptom not told yet cannot be volunteered on its own
    told_alone = [f for f in facts if "parent" not in f or f["parent"] in case.opening]
    ids = [f["id"] for f in told_alone]
    if ids:
        user = "\n".join(head + [f"Correct diagnosis: {diagnosis}", "", "What the patient says first:"]
                         + opening_lines(case) + ["", "Entries to choose from:"] + sheet(told_alone, case))
        schema = {"type": "object", "properties": {"reason": {"type": "string"}, "target": {"enum": ids}},
                  "required": ["reason", "target"], "additionalProperties": False}
        value, problems = choose(client, case, "compile_target", user, schema,
                                 lambda v: [] if v.get("target") in ids else ["target must be one of the listed ids"])
        target = value.get("target") if value.get("target") in ids else None
        out["a12a"] = {"target": target, "reason": value.get("reason", ""),
                       **({"item": by_id[target]["item"], "text": by_id[target]["text"]} if target else {})}
        out["problems"] += [f"a12a: {p}" for p in problems]
    else:
        out["a12a"] = {"target": None, "reason": "no present entry outside the opening"}

    # A13: blocks 2-3 are the complaint's own details by the release's attribute; the model adds complaint timing
    # kept as an entry of its own (block 2) and blocks 4 and 5, at most 3 entries each
    top = [f for f in facts if "parent" not in f]
    allowed = {"onset": [f["id"] for f in top if f["category"] == "symptom"],
               "associated": [f["id"] for f in top if f["category"] == "symptom"],
               "history": [f["id"] for f in top if f["category"] != "symptom"]}
    ids = [f["id"] for f in top]
    user = "\n".join(head + ["", "What the patient says first (the complaint):"] + opening_lines(case)
                     + ["", "Entries to choose from:"] + sheet(top, case))
    schema = {"type": "object", "properties": {
        g: {"type": "array", "items": {"enum": allowed[g]}} if allowed[g] else {"type": "array", "maxItems": 0}
        for g in GROUPS}, "required": list(GROUPS), "additionalProperties": False}

    def block_problems(v: dict) -> list:
        problems, seen = [], []
        for group in GROUPS:
            picked = v.get(group) if isinstance(v.get(group), list) else []
            wrong = [f for f in picked if f not in allowed[group]]
            if wrong:
                problems.append(f"{group} may not hold {wrong}")
            if len(picked) > CAP[group]:
                problems.append(f"{group} holds at most {CAP[group]} entries")
            seen += picked
        twice = sorted({f for f in seen if seen.count(f) > 1})
        if twice:
            problems.append(f"each entry at most once: {twice}")
        return problems

    blocks = {"1": list(case.opening), "2": [], "3": [], "4": [], "5": []}
    for n, attributes in ATTRIBUTES.items():
        blocks[n] = [f["id"] for f in facts if f.get("parent") in case.opening and f.get("attribute") in attributes]
    if ids:
        value, problems = choose(client, case, "compile_blocks", user, schema, block_problems)
        seen = {f for n in "123" for f in blocks[n]}
        for group, n in GROUPS.items():        # whatever still breaks the rules after the redrafts is dropped
            picked = []
            for f in value.get(group) or []:
                if f in allowed[group] and f not in seen and len(picked) < CAP[group]:
                    picked.append(f)
                    seen.add(f)
            blocks[n] += picked
        out["problems"] += [f"a13: {p}" for p in problems]
    out["a13"] = {"blocks": blocks, "texts": {f: by_id[f]["text"] for n in "2345" for f in blocks[n]}}
    out["a12a_anchor"] = compile_anchor(client, case, out["a12a"]["target"])
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", default="local")
    parser.add_argument("--model-id", default="")
    parser.add_argument("--no-thinking-switch", action="store_true")
    parser.add_argument("--eval-dir", type=Path, required=True)
    parser.add_argument("--releases", type=Path)
    parser.add_argument("--versions", default="")
    parser.add_argument("--datasets", default=",".join(DATASETS))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--base", type=Path, action="append", default=[],
                        help="an earlier compile's folder (repeatable): its picks are kept; ANCHOR is made again "
                             "unless today's prompt made it for the same anchor; a case in no base is compiled in full")
    args = parser.parse_args()
    releases = args.releases or args.eval_dir / "data" / "releases"
    client = Client(args.base_url, args.model, thinking_switch=not args.no_thinking_switch)
    versions = parse_versions(args.versions)
    args.out.mkdir(parents=True, exist_ok=True)
    hashes = prompt_hashes()
    for dataset in args.datasets.split(","):
        ids = study_ids(args.eval_dir, dataset)
        cases = load_cases(args.eval_dir, releases, dataset, ids[:args.limit] if args.limit else ids,
                           version=versions.get(dataset))
        path = args.out / f"{dataset}.json"
        if path.exists():
            have = json.loads(path.read_text(encoding="utf-8"))
            if have.get("release") == cases[0].release and all("a12a_anchor" in have["cases"].get(c.case_id, {})
                                                                 for c in cases):
                print(f"{now()} {path}: all {len(cases)} cases there, kept", flush=True)
                continue
        base, base_files, same_prompt = {}, [], {}
        for folder in args.base:
            raw = (folder / f"{dataset}.json").read_bytes()
            base_files.append({"path": str(folder / f"{dataset}.json"), "sha256": hashlib.sha256(raw).hexdigest()[:12]})
            have = json.loads(raw)
            if have.get("release") != cases[0].release:
                raise SystemExit(f"{dataset}: the base {folder} is for release {have.get('release')}, "
                                 f"not {cases[0].release}")
            twice = sorted(set(have["cases"]) & set(base))
            if twice:
                raise SystemExit(f"{dataset}: {twice} are in two bases")
            base.update(have["cases"])
            same = (have.get("prompts") or {}).get("prompts/compile_anchor.md") == hashes["compile_anchor.md"]
            same_prompt.update(dict.fromkeys(have["cases"], same))

        def keep_anchor(c: Case) -> bool:
            return same_prompt.get(c.case_id, False) and \
                (base[c.case_id].get("a12a_anchor") or {}).get("anchor") == (c.anchor or {}).get("phrase")

        gold = {row["case_id"]: row["diagnosis"] for row in
                read_jsonl(release_dir(releases, dataset, versions.get(dataset)) / f"{dataset}_gold.jsonl")}
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            done = dict(zip([c.case_id for c in cases],
                            pool.map(lambda c: compile_case(client, c, gold[c.case_id], base.get(c.case_id),
                                                            c.case_id in base and keep_anchor(c)), cases)))
        write_json(path, {
            "_note": "Per-case data of the patient-behaviour conditions (simulator/README.md): a12a.target, "
                     "a12a_anchor.target, a13.blocks (1 is the opening). Chosen by the model below, checked by code "
                     "(sim/compile_conditions.py); spot-check before use.",
            "dataset": dataset, "release": cases[0].release, "split": "main",
            "model": args.model_id or args.model, "code_commit": code_commit(),
            "prompts": {f"prompts/{k}": hashes[k] for k in PROMPTS}, "created": now(),
            **({"base": base_files} if base_files else {}), "cases": done})
        problems = sum(len(c["problems"]) + len(c["a12a_anchor"].get("problems", [])) for c in done.values())
        print(f"{now()} {path}: {len(done)} cases, "
              f"{sum(bool(c['a12a_anchor']['target']) for c in done.values())} with an anchor fact, "
              f"{problems} problems left after the redrafts"
              + (f"; from the base: {sum(c.case_id in base for c in cases)} cases, "
                 f"{sum(c.case_id in base and keep_anchor(c) for c in cases)} with their ANCHOR pick kept"
                 if base_files else ""), flush=True)


if __name__ == "__main__":
    main()
