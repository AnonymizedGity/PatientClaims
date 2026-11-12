"""MedQA-CS-specific checks for case-schema bundles (on top of validate_cases.py).

- every source Q/A id (and the chief complaint) is cited in qc.fact_sources,
  unless listed in qc.excluded_sources;
- every exam line id is cited in qc.finding_sources, unless listed in qc.excluded_exam_lines;
- doorway vitals are present and marked initial;
- polarity per source answer agrees with the annotation
  (catches yes/no flips during conversion);
- quotes are exact fragments of the cited answers or the student note.

Usage: python check_coverage.py [case_id ...]
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC, ANN, BUNDLES = HERE / "source", HERE / "annotations", HERE / "bundles"


def norm(s):
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"').replace("—", "-").replace("–", "-")
    return re.sub(r"\s+", " ", s).strip().strip('"').lower()


def check(cid):
    errs, warns = [], []
    src = json.loads((SRC / f"{cid}.json").read_text(encoding="utf-8"))
    b = json.loads((BUNDLES / f"{cid}.json").read_text(encoding="utf-8"))
    ann = json.loads((ANN / f"{cid}.json").read_text(encoding="utf-8"))
    qc, facts = b["qc"], {f["id"]: f for f in b["patient"]["facts"]}
    cited = {s for ids in qc.get("fact_sources", {}).values() for s in ids}
    excluded = {x["id"] for x in qc.get("excluded_sources", [])}
    need = {q["fact_id"] for q in src["qa"]} | ({"cc"} if src["chief_complaint"] else set())
    missing = sorted(need - cited - excluded)
    if missing:
        errs.append(f"source answers not cited: {missing}")
    exam_cited = {e for x in qc.get("finding_sources", {}).values() for e in x.get("exam_ids", [])}
    exam_excluded = {x["id"] for x in qc.get("excluded_exam_lines", [])}
    missing_e = sorted({e["exam_id"] for e in src["exam_lines"]} - exam_cited - exam_excluded)
    if missing_e:
        errs.append(f"exam lines not cited: {missing_e}")
    vitals = [x for x in b["environment"]["findings"] if x["kind"] == "vital"]
    if src["doorway_vital_signs"] and not any(x.get("initial") for x in vitals):
        errs.append("doorway vitals missing or not marked initial")
    # polarity per source answer: annotation vs bundle
    pol_ann, pol_bundle = {}, {}
    for f in ann["patient_facts"]:
        for s in f["source_ids"]:
            pol_ann.setdefault(s, set()).add(f["assertion"])
    for fid, ids in qc.get("fact_sources", {}).items():
        for s in ids:
            if fid in facts:
                pol_bundle.setdefault(s, set()).add(facts[fid]["polarity"])
    for s in sorted(set(pol_ann) & set(pol_bundle)):
        if s != "note" and pol_ann[s] != pol_bundle[s]:
            warns.append(f"{s}: polarity annotation {sorted(pol_ann[s])} vs bundle {sorted(pol_bundle[s])} — check")
    # quotes
    answers = {q["fact_id"]: q["answer"] for q in src["qa"]}
    if src["chief_complaint"]:
        answers["cc"] = src["chief_complaint"]["answer"]
    for fid, quote in qc.get("quotes", {}).items():
        pool = " ".join(answers.get(s, "") for s in qc["fact_sources"].get(fid, []))
        if "note" in qc["fact_sources"].get(fid, []):
            pool += " " + src["patient_note_history"]
        pool += " " + " ".join(q["question"] for q in src["qa"])  # source defects put answers in questions (007)
        for part in (p for p in re.split(r"\s+/\s+", quote) if p.strip()):
            if norm(part).rstrip(".") not in norm(pool):
                warns.append(f"{fid}: quote not found in cited sources: {part!r}")
    return errs, warns


def main():
    ids = sys.argv[1:] or sorted(p.stem for p in BUNDLES.glob("*.json"))
    bad = 0
    for cid in ids:
        errs, warns = check(cid)
        bad += bool(errs)
        print(f"{cid}: {'OK' if not errs else 'FAIL'} ({len(errs)} errors, {len(warns)} warnings)")
        for e in errs:
            print("   ERROR", e)
        for w in warns:
            print("   warn ", w)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
