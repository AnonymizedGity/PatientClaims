"""Validate a dataset release against data/conversion/case_schema.md.

Usage:
    python data/conversion/validate_cases.py <release_dir>          # <dataset>_{patient,environment,gold,qc}.jsonl + manifest.json
    python data/conversion/validate_cases.py --bundles <dir>        # one <case_id>.json per case: {patient, environment, gold, qc}
    python data/conversion/validate_cases.py --bundles <dir> <case_id> ...

Exit code 1 if any case has errors. Warnings are printed but do not fail.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

CATEGORIES = {"symptom", "medical_history", "medication", "family_history", "habit_exposure", "social_background"}
SYSTEMS = {"general", "cardiovascular", "respiratory", "gastrointestinal", "genitourinary", "reproductive",
           "musculoskeletal", "neurological", "psychiatric", "skin", "ent", "eye", "endocrine", "hematologic"}
ATTRIBUTES = {"onset", "duration", "course", "frequency", "timing", "severity", "location", "radiation", "character",
              "aggravating", "relieving", "context", "quantity", "appearance", "treatment_response", "other"}
POLARITY = {"present", "absent"}
TIME = {"current", "historical", "recurrent", "resolved"}
KINDS = {"vital", "exam", "test"}
FACT_KEYS = {"id", "item", "text", "polarity", "category", "system", "parent", "attribute", "value", "scale",
             "complete", "time", "aliases", "pattern", "key"}
FINDING_KEYS = {"id", "kind", "name", "result", "system", "aliases", "time", "initial"}
COMMENTARY = re.compile(r"\bOCR\b|artifact|garbled|recorded as|source reads|not stated|possibly meant|\bsee qc\b", re.I)
THIRD_PERSON = re.compile(r"^(the )?patient\b|^(he|she) (has|is|reports|denies)\b", re.I)


def is_str_list(x):
    return isinstance(x, list) and all(isinstance(s, str) and s.strip() for s in x)


def check_patient(p, errs, warns, world=None):
    for k in ("case_id", "dataset", "demographics", "opening", "facts"):
        if k not in p:
            errs.append(f"patient: missing '{k}'")
    if errs:
        return set()
    ab = p.get("answered_by")
    if ab is not None:
        fact_ids = {f.get("id") for f in p["facts"]}
        if world == "open" or not isinstance(ab, dict):
            errs.append("patient.answered_by must map catalogue keys to fact ids (closed world only)")
        else:
            for key, ids in ab.items():
                if not isinstance(ids, list) or any(i not in fact_ids for i in ids):
                    errs.append(f"patient.answered_by[{key}] must list existing fact ids")
    demo = p["demographics"]
    if not isinstance(demo.get("age"), int) or not 0 <= demo["age"] <= 120:
        errs.append(f"patient.demographics.age invalid: {demo.get('age')!r}")
    if demo.get("sex") not in ("male", "female"):
        errs.append(f"patient.demographics.sex invalid: {demo.get('sex')!r}")
    facts = p["facts"]
    ids = [f.get("id") for f in facts]
    by_id = {f.get("id"): f for f in facts}
    if len(set(ids)) != len(ids):
        errs.append("patient: duplicate fact ids")
    seen_items = {}
    for f in facts:
        fid = f.get("id", "?")
        if not re.fullmatch(r"f\d{3}", str(fid)):
            errs.append(f"{fid}: id must look like f001")
        extra = set(f) - FACT_KEYS
        if extra:
            errs.append(f"{fid}: unknown keys {sorted(extra)}")
        for k in ("item", "text", "polarity", "category"):
            if not f.get(k):
                errs.append(f"{fid}: missing '{k}'")
        if f.get("polarity") and f["polarity"] not in POLARITY:
            errs.append(f"{fid}: polarity {f['polarity']!r}")
        if f.get("category") and f["category"] not in CATEGORIES:
            errs.append(f"{fid}: category {f['category']!r}")
        if f.get("category") == "symptom" and "system" not in f:
            errs.append(f"{fid}: symptom without system")
        if "system" in f and f["system"] not in SYSTEMS:
            errs.append(f"{fid}: system {f['system']!r}")
        if "time" in f and f["time"] not in TIME:
            errs.append(f"{fid}: time {f['time']!r}")
        if ("parent" in f) != ("attribute" in f):
            errs.append(f"{fid}: 'parent' and 'attribute' go together")
        if "parent" in f:
            if f["parent"] == fid or f["parent"] not in by_id:
                errs.append(f"{fid}: parent {f['parent']!r} not found")
            elif "parent" in by_id[f["parent"]] and by_id[f["parent"]]["parent"] == fid:
                errs.append(f"{fid}: parent cycle")
            elif by_id[f["parent"]].get("category") != f.get("category"):
                warns.append(f"{fid}: category {f.get('category')!r} differs from parent's {by_id[f['parent']].get('category')!r}")
        if "attribute" in f and f["attribute"] not in ATTRIBUTES:
            errs.append(f"{fid}: attribute {f['attribute']!r}")
        if "value" in f and not (isinstance(f["value"], (int, float, str)) and not isinstance(f["value"], bool)
                                 or is_str_list(f["value"])):
            errs.append(f"{fid}: value must be a number, a string or a list of strings")
        if "complete" in f and (not isinstance(f["complete"], bool) or not isinstance(f.get("value"), list)):
            errs.append(f"{fid}: 'complete' must be a boolean on a list value")
        if "scale" in f:
            sc = f["scale"]
            if not (isinstance(sc, list) and len(sc) == 2 and all(isinstance(v, (int, float)) for v in sc)
                    and sc[0] < sc[1]):
                errs.append(f"{fid}: scale must be [min, max]")
            elif not isinstance(f.get("value"), (int, float)) or not sc[0] <= f["value"] <= sc[1]:
                errs.append(f"{fid}: scale needs a numeric value inside it")
        if "key" in f and not (isinstance(f["key"], str) and f["key"].strip()):
            errs.append(f"{fid}: key must be a non-empty string")
        if world == "closed" and "key" not in f:
            errs.append(f"{fid}: closed-world facts need a catalogue key")
        if "aliases" in f and not is_str_list(f["aliases"]):
            errs.append(f"{fid}: aliases must be a list of strings")
        if "pattern" in f and not isinstance(f["pattern"], bool):
            errs.append(f"{fid}: pattern must be a boolean")
        item, text = str(f.get("item", "")), str(f.get("text", ""))
        if item and text and item.strip().lower() == text.strip().lower():
            errs.append(f"{fid}: item repeats the answer text")
        if len(item) > 70:
            warns.append(f"{fid}: long item label ({len(item)} chars): {item!r}")
        if THIRD_PERSON.match(text):
            warns.append(f"{fid}: text should be first person: {text!r}")
        key = (item.lower(), f.get("parent"))
        if key in seen_items:
            warns.append(f"{fid}: same item as {seen_items[key]} ({item!r})")
        seen_items[key] = fid
    opening = p["opening"]
    if not opening or not isinstance(opening, list):
        errs.append("patient.opening must be a non-empty list of fact ids")
    else:
        for o in opening:
            if o not in by_id:
                errs.append(f"opening id {o!r} not found")
            elif by_id[o].get("polarity") != "present":
                errs.append(f"opening fact {o} is not present")
    return set(ids)


def check_environment(e, errs, warns):
    if "findings" not in e or not isinstance(e["findings"], list):
        errs.append("environment: missing 'findings' list")
        return set()
    ids = [x.get("id") for x in e["findings"]]
    if len(set(ids)) != len(ids):
        errs.append("environment: duplicate finding ids")
    for x in e["findings"]:
        xid = x.get("id", "?")
        if not re.fullmatch(r"x\d{3}", str(xid)):
            errs.append(f"{xid}: id must look like x001")
        extra = set(x) - FINDING_KEYS
        if extra:
            errs.append(f"{xid}: unknown keys {sorted(extra)}")
        for k in ("kind", "name", "result"):
            if not x.get(k):
                errs.append(f"{xid}: missing '{k}'")
        if x.get("kind") and x["kind"] not in KINDS:
            errs.append(f"{xid}: kind {x['kind']!r}")
        if x.get("kind") == "exam" and "system" not in x:
            errs.append(f"{xid}: exam without system")
        if "system" in x and x["system"] not in SYSTEMS:
            errs.append(f"{xid}: system {x['system']!r}")
        if "aliases" in x and not is_str_list(x["aliases"]):
            errs.append(f"{xid}: aliases must be a list of strings")
        if "initial" in x and not isinstance(x["initial"], bool):
            errs.append(f"{xid}: initial must be a boolean")
        if COMMENTARY.search(str(x.get("result", ""))):
            warns.append(f"{xid}: result looks like review commentary: {x.get('result')!r}")
    return set(ids)


def check_gold(g, errs, warns):
    if not str(g.get("diagnosis", "")).strip():
        errs.append("gold: missing diagnosis")
    if not isinstance(g.get("aliases"), list) or not all(isinstance(a, str) for a in g.get("aliases", [])):
        errs.append("gold: aliases must be a list of strings")
    elif not g["aliases"]:
        warns.append("gold: no aliases")
    dd = g.get("differential")
    if dd is not None:
        if [d.get("rank") for d in dd] != list(range(1, len(dd) + 1)):
            errs.append("gold.differential ranks must be 1..n")
        for d in dd:
            if not str(d.get("diagnosis", "")).strip():
                errs.append("gold.differential: empty diagnosis")
            for k in ("aliases", "evidence"):
                if k in d and not is_str_list(d[k]):
                    errs.append(f"gold.differential[{d.get('rank')}].{k} must be a list of strings")
            if "probability" in d and not (isinstance(d["probability"], (int, float)) and 0 <= d["probability"] <= 1):
                errs.append(f"gold.differential[{d.get('rank')}].probability must be in [0, 1]")
    for oc in g.get("other_considerations", []):
        if not str(oc.get("diagnosis", "")).strip():
            errs.append("gold.other_considerations: empty diagnosis")


def check_qc(q, fact_ids, finding_ids, errs, warns):
    fs = q.get("fact_sources")
    if not isinstance(fs, dict):
        errs.append("qc: missing fact_sources")
    else:
        missing = sorted(fact_ids - set(fs))
        if missing:
            errs.append(f"qc.fact_sources missing for {missing[:8]}{'…' if len(missing) > 8 else ''}")
    xs = q.get("finding_sources")
    if finding_ids and not isinstance(xs, dict):
        errs.append("qc: missing finding_sources")
    elif finding_ids:
        missing = sorted(finding_ids - set(xs))
        if missing:
            errs.append(f"qc.finding_sources missing for {missing[:8]}")


def check_case(patient, env, gold, qc, world=None):
    errs, warns = [], []
    ids = {x.get("case_id") for x in (patient, env, gold, qc)}
    if len(ids) != 1:
        errs.append(f"case_id differs across files: {ids}")
    fact_ids = check_patient(patient, errs, warns, world)
    finding_ids = check_environment(env, errs, warns)
    check_gold(gold, errs, warns)
    check_qc(qc, fact_ids, finding_ids, errs, warns)
    return errs, warns


def load_release(path):
    files = {}
    for part in ("patient", "environment", "gold", "qc"):
        hits = list(path.glob(f"*_{part}.jsonl"))
        if len(hits) != 1:
            sys.exit(f"expected exactly one *_{part}.jsonl in {path}, found {len(hits)}")
        files[part] = {r["case_id"]: r for r in map(json.loads, hits[0].read_text(encoding="utf-8").splitlines()) if r}
    sets = {k: set(v) for k, v in files.items()}
    if len({frozenset(s) for s in sets.values()}) != 1:
        sys.exit(f"case_id sets differ across files: { {k: len(v) for k, v in sets.items()} }")
    manifest = path / "manifest.json"
    if not manifest.exists():
        sys.exit("manifest.json missing")
    m = json.loads(manifest.read_text(encoding="utf-8"))
    if m.get("world") not in ("open", "closed"):
        sys.exit("manifest.world must be 'open' or 'closed'")
    if m["world"] == "closed" and not (path / f"{m.get('dataset')}_catalogue.json").exists():
        sys.exit("closed-world release needs <dataset>_catalogue.json")
    cases = {cid: tuple(files[p][cid] for p in ("patient", "environment", "gold", "qc")) for cid in sorted(sets["patient"])}
    return cases, m["world"]


def load_bundles(path, only):
    out = {}
    for f in sorted(path.glob("*.json")):
        if only and f.stem not in only:
            continue
        b = json.loads(f.read_text(encoding="utf-8"))
        out[f.stem] = tuple(b.get(p, {}) for p in ("patient", "environment", "gold", "qc"))
    return out


def main(argv):
    if not argv:
        sys.exit(__doc__)
    if argv[0] == "--bundles":
        cases, world = load_bundles(Path(argv[1]), set(argv[2:])), None
    else:
        cases, world = load_release(Path(argv[0]))
    bad = 0
    for cid, parts in cases.items():
        errs, warns = check_case(*parts, world=world)
        bad += bool(errs)
        print(f"{cid}: {'OK' if not errs else 'FAIL'} ({len(errs)} errors, {len(warns)} warnings)")
        for e in errs:
            print("   ERROR", e)
        for w in warns:
            print("   warn ", w)
    print(f"{len(cases) - bad}/{len(cases)} cases valid")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv[1:]))
