"""MedCaseReasoning-specific checks for case-schema bundles (on top of validate_cases.py).

- every sentence of the case prompt is cited by a fact or finding, or listed in qc.excluded_sentences;
- cited sentence ids exist;
- quotes and finding source_text are exact fragments of the cited sentences;
- demographics agree with the screened age and sex;
- gold.reasoning is the source diagnostic_reasoning; the gold diagnosis matches the source label
  (warning if reworded);
- qc.notes has an "Index visit:" entry;
- words of the gold diagnosis in patient facts or finding names are listed in qc.leakage (warning).

Usage: python check_coverage.py [case_id ...]
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC, BUNDLES = HERE / "source", HERE / "bundles"
STOP = {"of", "the", "and", "with", "due", "to", "in", "a", "an", "or", "acute", "chronic", "syndrome", "disease",
        "disorder", "infection", "primary", "secondary", "type", "induced", "related", "associated", "active", "left",
        "right", "bilateral", "deficiency", "failure", "injury", "early", "late", "stage", "severe", "mild",
        "idiopathic", "reaction", "drug"}


def norm(s):
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"').replace("—", "-").replace("–", "-")
    return re.sub(r"\s+", " ", s).strip().strip('"').lower()


def check(cid):
    errs, warns = [], []
    src = json.loads((SRC / f"{cid}.json").read_text(encoding="utf-8"))
    b = json.loads((BUNDLES / f"{cid}.json").read_text(encoding="utf-8"))
    qc, patient = b["qc"], b["patient"]
    text = {s["id"]: s["text"] for s in src["sentences"]}

    fact_cited = {s for ids in qc.get("fact_sources", {}).values() for s in ids}
    find_cited = {s for x in qc.get("finding_sources", {}).values() for s in x.get("sentences", [])}
    excluded = {x["id"] for x in qc.get("excluded_sentences", [])}
    unknown = sorted((fact_cited | find_cited | excluded) - set(text))
    if unknown:
        errs.append(f"unknown sentence ids: {unknown}")
    missing = sorted(set(text) - fact_cited - find_cited - excluded)
    if missing:
        errs.append(f"sentences not cited or excluded: {missing}")

    def exact(parts, ids, what):
        pool = norm(" ".join(text.get(s, "") for s in ids))
        for part in (p for p in re.split(r"\s+/\s+", parts) if p.strip()):
            if norm(part).rstrip(".") not in pool:
                warns.append(f"{what}: text not found in cited sentences: {part!r}")

    for fid, quote in qc.get("quotes", {}).items():
        exact(quote, qc.get("fact_sources", {}).get(fid, []), fid)
    for xid, x in qc.get("finding_sources", {}).items():
        if not x.get("sentences"):
            errs.append(f"{xid}: finding_sources entry without sentences")
        exact(x.get("source_text", ""), x.get("sentences", []), xid)

    sel = src["selection"]
    if sel["age"] is not None and patient["demographics"].get("age") != sel["age"]:
        errs.append(f"age {patient['demographics'].get('age')} vs screened {sel['age']}")
    if sel["sex"] and patient["demographics"].get("sex") != sel["sex"]:
        errs.append(f"sex {patient['demographics'].get('sex')} vs screened {sel['sex']}")

    g = b["gold"]
    if norm(g.get("reasoning", "")) != norm(src["diagnostic_reasoning"]):
        errs.append("gold.reasoning is not the source diagnostic_reasoning")
    if re.sub(r"[^a-z0-9]", "", g["diagnosis"].lower()) != re.sub(r"[^a-z0-9]", "", src["final_diagnosis"].lower()):
        warns.append(f"gold diagnosis {g['diagnosis']!r} differs from source {src['final_diagnosis']!r} (fine if only cleaned)")
    if not any(str(n).startswith("Index visit:") for n in qc.get("notes", [])):
        errs.append("qc.notes has no 'Index visit:' entry")

    label = re.sub(r"([a-z])([A-Z])", r"\1 \2", src["final_diagnosis"]).lower()
    words = {w for w in re.findall(r"[a-z]{4,}", label) if w not in STOP}
    listed = {x.get("fact_id") or x.get("id") for x in qc.get("leakage", []) if isinstance(x, dict)}
    for f in patient["facts"]:
        hit = sorted(w for w in words if re.search(rf"\b{w}", f["text"].lower() + " " + f["item"].lower()))
        if hit and f["id"] not in listed:
            warns.append(f"{f['id']}: patient fact mentions gold term(s) {hit} but is not in qc.leakage")
    for x in b["environment"]["findings"]:
        hit = sorted(w for w in words if re.search(rf"\b{w}", x["name"].lower() + " " + " ".join(x.get("aliases", [])).lower()))
        if hit:
            warns.append(f"{x['id']}: finding name/aliases mention gold term(s) {hit} - rename unless the test is named that way clinically")
        res = sorted(w for w in words if re.search(rf"\b{w}", x["result"].lower()))
        if res and x["id"] not in listed:
            warns.append(f"{x['id']}: result mentions gold term(s) {res} but is not in qc.leakage")
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
