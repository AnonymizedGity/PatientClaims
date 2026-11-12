"""Validate MedQA-CS annotations against their source inventories.

Usage: python validate.py [case_id ...]     (default: every file in annotations/)
Exit code 1 if any case has errors.
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC, ANN = HERE / "source", HERE / "annotations"

CATEGORIES = {"symptoms", "history_and_exposures"}
SUBTYPES = {"hpi", "ros", "pmh", "psh", "medications", "allergies", "family", "social", "sexual",
            "ob_gyn", "exposures", "preventive", "functional", "concerns", "other"}
ASSERTIONS = {"present", "absent"}
TEMPORALITY = {"current", "historical", "recurrent", "resolved", "unclear"}
ENV_SECTIONS = {"vital_signs", "physical_examination", "investigations"}
ENV_SOURCES = {"doorway", "patient_note", "sp_notes"}
COMMENTARY = re.compile(r"\bOCR\b|artifact|garbled|recorded as|source reads|not stated|\(SP-simulated\)|possibly meant|\bsee qc\b", re.I)


def check(case_id):
    errs, warns = [], []
    src = json.loads((SRC / f"{case_id}.json").read_text(encoding="utf-8"))
    path = ANN / f"{case_id}.json"
    if not path.exists():
        return [f"missing {path.name}"], []
    try:
        a = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return [f"invalid JSON: {e}"], []

    def need(obj, key, where):
        if key not in obj:
            errs.append(f"{where}: missing '{key}'")
            return False
        return True

    for k in ("case_id", "demographics", "opening_fact", "patient_facts", "persona",
              "clinical_environment", "gold", "qc"):
        need(a, k, "top level")
    if errs:
        return errs, warns
    if a["case_id"] != case_id:
        errs.append("case_id mismatch")

    p_ids = {q["fact_id"] for q in src["qa"]}
    e_ids = {e["exam_id"] for e in src["exam_lines"]}
    valid_src = p_ids | {"cc", "note"}

    # patient facts
    seen, covered = set(), set()
    for i, f in enumerate(a["patient_facts"]):
        where = f"patient_facts[{i}]"
        for k in ("id", "source_ids", "category", "subtype", "assertion", "temporality", "text", "quote"):
            need(f, k, where)
        fid = f.get("id", "")
        if not re.fullmatch(rf"{re.escape(case_id)}-f\d{{3}}", fid):
            errs.append(f"{where}: bad id {fid!r}")
        if fid in seen:
            errs.append(f"{where}: duplicate id {fid}")
        seen.add(fid)
        if f.get("category") not in CATEGORIES:
            errs.append(f"{fid}: category {f.get('category')!r}")
        if f.get("subtype") not in SUBTYPES:
            errs.append(f"{fid}: subtype {f.get('subtype')!r}")
        if f.get("assertion") not in ASSERTIONS:
            errs.append(f"{fid}: assertion {f.get('assertion')!r}")
        if f.get("temporality") not in TEMPORALITY:
            errs.append(f"{fid}: temporality {f.get('temporality')!r}")
        sids = f.get("source_ids") or []
        if not sids:
            errs.append(f"{fid}: empty source_ids")
        for s in sids:
            if s not in valid_src:
                errs.append(f"{fid}: unknown source id {s!r}")
        covered.update(sids)
        if "note" in sids and not f.get("from_note"):
            warns.append(f"{fid}: source 'note' without from_note=true")
        if not str(f.get("text", "")).strip():
            errs.append(f"{fid}: empty text")
        # absent facts must read as an absence; present facts must not open with a bare denial word
        t = str(f.get("text", "")).lower()
        if f.get("assertion") == "present" and re.match(r"^(no|denies|never|without)\b", t):
            warns.append(f"{fid}: present fact starts with a denial word — check polarity: {f.get('text')!r}")
    excluded = {x.get("source_id") for x in a.get("excluded_source_ids", [])}
    missing = sorted((p_ids - covered) - excluded)
    if missing:
        errs.append(f"source Q/A not covered: {missing}")
    if src.get("chief_complaint") and "cc" not in covered and "cc" not in (a["opening_fact"].get("source_ids") or []):
        errs.append("chief complaint not used")

    # opening fact
    of = a["opening_fact"]
    if not str(of.get("text", "")).strip():
        errs.append("opening_fact.text empty")
    if re.search(r"\(.*\)", str(of.get("text", ""))):
        warns.append("opening_fact contains a parenthetical (stage direction?)")

    # environment
    env = a["clinical_environment"]
    for sec in ENV_SECTIONS:
        if sec not in env or not isinstance(env[sec], list):
            errs.append(f"clinical_environment.{sec} missing or not a list")
    env_cov, env_seen = set(), set()
    for sec in ENV_SECTIONS & set(env):
        for i, x in enumerate(env[sec]):
            where = f"{sec}[{i}]"
            for k in ("id", "source", "name", "finding", "source_text"):
                need(x, k, where)
            if x.get("id") in env_seen:
                errs.append(f"{where}: duplicate id {x.get('id')}")
            env_seen.add(x.get("id"))
            if x.get("source") not in ENV_SOURCES:
                errs.append(f"{where}: source {x.get('source')!r}")
            if x.get("source") == "patient_note":
                ids = x.get("exam_ids") or []
                if not ids:
                    errs.append(f"{where}: patient_note finding without exam_ids")
                for e in ids:
                    if e not in e_ids:
                        errs.append(f"{where}: unknown exam id {e!r}")
                env_cov.update(ids)
            if not str(x.get("finding", "")).strip():
                errs.append(f"{where}: empty finding")
            if COMMENTARY.search(str(x.get("finding", ""))):
                warns.append(f"{where}: finding looks like review commentary; move it to `flags`: {x.get('finding')!r}")
    missing_e = sorted(e_ids - env_cov - {x.get("exam_id") for x in a.get("excluded_exam_ids", [])})
    if missing_e:
        errs.append(f"exam lines not covered: {missing_e}")
    if src["doorway_vital_signs"] and not any(x.get("source") == "doorway" for x in env.get("vital_signs", [])):
        errs.append("doorway vital signs not included")

    # gold
    g = a["gold"]
    dd = g.get("differential") or []
    if not dd:
        errs.append("gold.differential empty")
    for i, d in enumerate(dd):
        for k in ("rank", "diagnosis", "history_findings", "exam_findings"):
            need(d, k, f"gold.differential[{i}]")
    if [d.get("rank") for d in dd] != list(range(1, len(dd) + 1)):
        errs.append("gold ranks must be 1..n")
    need(g, "additional_considerations", "gold")
    need(g, "leakage_check", "gold")

    # persona
    for k in ("acting_notes", "patient_questions"):
        need(a["persona"], k, "persona")
    need(a["qc"], "source_issues", "qc")
    return errs, warns


def main():
    ids = sys.argv[1:] or sorted(p.stem for p in ANN.glob("medqa-cs-*.json"))
    bad = 0
    for cid in ids:
        errs, warns = check(cid)
        status = "OK" if not errs else "FAIL"
        bad += bool(errs)
        print(f"{cid}: {status} ({len(errs)} errors, {len(warns)} warnings)")
        for e in errs:
            print("   ERROR", e)
        for w in warns:
            print("   warn ", w)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
