"""Check second-look outputs against SECOND_LOOK.md.

Usage: python check_second.py [part_number ...]   (default: every part that has an output file)
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent / "second_look"
KEYS = ["idx", "pmcid", "reliable_historian", "interview_value", "gold_fit", "narrative_conclusion", "course_problem",
        "dx_key", "specialty", "keep", "note"]
SPECIALTIES = {"cardiology", "pulmonology", "gastroenterology_hepatology", "nephrology_urology", "endocrinology",
               "hematology_oncology", "infectious_disease", "rheumatology_immunology", "neurology", "psychiatry",
               "dermatology", "ent_dental_eye", "obstetrics_gynecology", "surgery_trauma", "toxicology",
               "general_internal_medicine"}


def rule_keep(r):
    return r["reliable_historian"] and r["interview_value"] != "low" and r["gold_fit"] == "good" and not r["course_problem"]


def check(n):
    errs = []
    src = [json.loads(l) for l in (HERE / f"input_{n}.jsonl").open(encoding="utf-8")]
    path = HERE / f"part_{n}.jsonl"
    if not path.exists():
        return [f"missing {path.name}"]
    out = []
    for i, line in enumerate(path.open(encoding="utf-8"), 1):
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as e:
                errs.append(f"line {i}: invalid JSON ({e})")
    if [r.get("idx") for r in out] != [s["idx"] for s in src]:
        errs.append(f"idx sequence differs from the input ({len(out)} rows for {len(src)} cases)")
    by = {s["idx"]: s for s in src}
    for r in out:
        where = f"idx {r.get('idx')}"
        if list(r) != KEYS:
            errs.append(f"{where}: keys {list(r)}")
            continue
        if by.get(r["idx"], {}).get("pmcid") != r["pmcid"]:
            errs.append(f"{where}: pmcid mismatch")
        for k in ("reliable_historian", "narrative_conclusion", "course_problem", "keep"):
            if not isinstance(r[k], bool):
                errs.append(f"{where}: {k} must be true/false")
        if r["interview_value"] not in ("high", "medium", "low"):
            errs.append(f"{where}: interview_value={r['interview_value']!r}")
        if r["gold_fit"] not in ("good", "weak"):
            errs.append(f"{where}: gold_fit={r['gold_fit']!r}")
        if r["specialty"] not in SPECIALTIES:
            errs.append(f"{where}: specialty={r['specialty']!r}")
        if not str(r["dx_key"]).strip() or r["dx_key"] != r["dx_key"].lower():
            errs.append(f"{where}: dx_key must be non-empty lower case")
        if not str(r["note"]).strip():
            errs.append(f"{where}: empty note")
        if not errs and r["keep"] != rule_keep(r):
            errs.append(f"{where}: keep={r['keep']} but the rule gives {rule_keep(r)}")
    return errs


def main():
    ns = sys.argv[1:] or sorted(p.stem.split("_")[1] for p in HERE.glob("part_*.jsonl"))
    bad = 0
    for n in ns:
        errs = check(n)
        bad += bool(errs)
        print(f"part_{n}: {'OK' if not errs else 'FAIL'} ({len(errs)} errors)")
        for e in errs[:30]:
            print("   ERROR", e)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
