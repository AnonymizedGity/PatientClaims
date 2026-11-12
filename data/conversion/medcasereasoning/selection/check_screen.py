"""Check screening outputs against SCREENING.md.

Usage: python check_screen.py [batch_number ...]   (default: every batch that has an output file)
Errors: missing or extra cases, wrong keys, bad values. Warnings: verdict differs from the rules.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
KEYS = ["idx", "pmcid", "age", "sex", "specialty", "setting", "can_converse", "patient_facts", "objective_findings",
        "time_structure", "leakage", "inferable", "decisive_evidence", "label_issue", "image_dependence", "verdict", "reason"]
ENUMS = {
    "sex": {"male", "female", None},
    "specialty": {"cardiology", "pulmonology", "gastroenterology_hepatology", "nephrology_urology", "endocrinology",
                  "hematology_oncology", "infectious_disease", "rheumatology_immunology", "neurology", "psychiatry",
                  "dermatology", "ent_dental_eye", "obstetrics_gynecology", "surgery_trauma", "toxicology",
                  "general_internal_medicine", "other"},
    "setting": {"outpatient", "emergency", "inpatient_onset", "referral"},
    "time_structure": {"single_episode", "staged_workup", "course_dependent"},
    "leakage": {"none", "test_result", "history"},
    "inferable": {"high", "medium", "low"},
    "decisive_evidence": {"history", "exam", "lab", "imaging", "pathology", "genetic", "other"},
    "verdict": {"include", "maybe", "exclude"},
}


def rule_verdict(r):
    if (not r["can_converse"] or r["time_structure"] == "course_dependent" or r["leakage"] == "history"
            or r["inferable"] == "low" or r["patient_facts"] < 5 or r["objective_findings"] == 0 or r["image_dependence"]):
        return "exclude"
    if (r["patient_facts"] >= 8 and r["objective_findings"] >= 3 and r["inferable"] in ("high", "medium")
            and r["label_issue"] is None):
        return "include"
    return "maybe"


def check(n):
    errs, warns = [], []
    src = [json.loads(l) for l in (HERE / "batches" / f"batch_{n}.jsonl").open(encoding="utf-8")]
    path = HERE / "screen" / f"batch_{n}.jsonl"
    if not path.exists():
        return [f"missing {path.name}"], []
    out = []
    for i, line in enumerate(path.open(encoding="utf-8"), 1):
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as e:
                errs.append(f"line {i}: invalid JSON ({e})")
    if [r.get("idx") for r in out] != [s["idx"] for s in src]:
        errs.append(f"idx sequence differs from the batch (got {len(out)} rows for {len(src)} cases)")
    by = {s["idx"]: s for s in src}
    for r in out:
        where = f"idx {r.get('idx')}"
        if list(r) != KEYS:
            errs.append(f"{where}: keys {list(r)}")
            continue
        if by.get(r["idx"], {}).get("pmcid") != r["pmcid"]:
            errs.append(f"{where}: pmcid mismatch")
        for k, allowed in ENUMS.items():
            if r[k] not in allowed:
                errs.append(f"{where}: {k}={r[k]!r}")
        for k in ("can_converse", "image_dependence"):
            if not isinstance(r[k], bool):
                errs.append(f"{where}: {k} must be true/false")
        for k in ("patient_facts", "objective_findings"):
            if not isinstance(r[k], int) or r[k] < 0:
                errs.append(f"{where}: {k} must be a non-negative integer")
        if r["age"] is not None and not isinstance(r["age"], int):
            errs.append(f"{where}: age must be an integer or null")
        if r["label_issue"] is not None and not (isinstance(r["label_issue"], str) and r["label_issue"].strip()):
            errs.append(f"{where}: label_issue must be null or a non-empty string")
        if not str(r["reason"]).strip():
            errs.append(f"{where}: empty reason")
        if not errs and r["verdict"] != rule_verdict(r):
            warns.append(f"{where}: verdict {r['verdict']} but the rules give {rule_verdict(r)}")
    return errs, warns


def main():
    ns = sys.argv[1:] or sorted(p.stem.split("_")[1] for p in (HERE / "screen").glob("batch_*.jsonl"))
    bad = 0
    for n in ns:
        errs, warns = check(n)
        bad += bool(errs)
        print(f"batch_{n}: {'OK' if not errs else 'FAIL'} ({len(errs)} errors, {len(warns)} warnings)")
        for e in errs[:30]:
            print("   ERROR", e)
        for w in warns:
            print("   warn ", w)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
