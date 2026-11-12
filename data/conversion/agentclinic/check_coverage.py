"""AgentClinic-specific checks for case-schema bundles (on top of validate_cases.py).

- every patient fragment (and the chief complaint) is cited in qc.fact_sources,
  unless listed in qc.excluded_sources;
- every exam and test leaf is cited in qc.finding_sources, unless listed in qc.excluded_exam_lines;
- demographics agree with the source text;
- quotes are exact fragments of the cited source text;
- the gold diagnosis matches the source label (warning if reworded);
- words of the gold diagnosis that appear in patient facts or finding names are
  listed in qc.leakage (warning otherwise).

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
        "right", "bilateral", "deficiency", "failure", "injury", "early", "late", "stage", "severe", "mild"}


def norm(s):
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"').replace("—", "-").replace("–", "-")
    return re.sub(r"\s+", " ", s).strip().strip('"').lower()


def check(cid):
    errs, warns = [], []
    src = json.loads((SRC / f"{cid}.json").read_text(encoding="utf-8"))
    b = json.loads((BUNDLES / f"{cid}.json").read_text(encoding="utf-8"))
    qc, patient = b["qc"], b["patient"]
    cited = {s for ids in qc.get("fact_sources", {}).values() for s in ids}
    excluded = {x["id"] for x in qc.get("excluded_sources", [])}
    need = {f["fact_id"] for f in src["fragments"]} | ({"cc"} if src["chief_complaint"] else set())
    if sorted(need - cited - excluded):
        errs.append(f"fragments not cited: {sorted(need - cited - excluded)}")
    leaves = {x["exam_id"] for x in src["exam_leaves"] + src["test_leaves"]}
    leaf_cited = {e for x in qc.get("finding_sources", {}).values() for e in x.get("exam_ids", [])}
    leaf_excl = {x["id"] for x in qc.get("excluded_exam_lines", [])}
    if sorted(leaves - leaf_cited - leaf_excl):
        errs.append(f"exam/test leaves not cited: {sorted(leaves - leaf_cited - leaf_excl)}")
    m = re.search(r"(\d+)[- ]year", src["demographics_text"])
    sex = "female" if re.search(r"\b(female|woman|girl)\b", src["demographics_text"], re.I) else \
          "male" if re.search(r"\b(male|man|boy)\b", src["demographics_text"], re.I) else None
    if m and patient["demographics"].get("age") != int(m.group(1)):
        errs.append(f"age {patient['demographics'].get('age')} vs source {src['demographics_text']!r}")
    if sex and patient["demographics"].get("sex") != sex:
        errs.append(f"sex {patient['demographics'].get('sex')} vs source {src['demographics_text']!r}")
    texts = {f["fact_id"]: f["text"] for f in src["fragments"]}
    texts["cc"] = src["chief_complaint"]
    for fid, quote in qc.get("quotes", {}).items():
        pool = " ".join(texts.get(s, "") for s in qc["fact_sources"].get(fid, []))
        for part in (p for p in re.split(r"\s+/\s+", quote) if p.strip()):
            if norm(part).rstrip(".") not in norm(pool):
                warns.append(f"{fid}: quote not found in cited fragments: {part!r}")
    if norm(b["gold"]["diagnosis"]) != norm(src["correct_diagnosis"]):
        warns.append(f"gold diagnosis {b['gold']['diagnosis']!r} differs from source {src['correct_diagnosis']!r} (fine if only cleaned)")
    words = {w for w in re.findall(r"[a-z]{4,}", src["correct_diagnosis"].lower()) if w not in STOP}
    listed = {x.get("fact_id") or x.get("id") for x in qc.get("leakage", []) if isinstance(x, dict)}
    for f in patient["facts"]:
        hit = sorted(w for w in words if re.search(rf"\b{w}", f["text"].lower() + " " + f["item"].lower()))
        if hit and f["id"] not in listed:
            warns.append(f"{f['id']}: patient fact mentions gold term(s) {hit} but is not in qc.leakage")
    for x in b["environment"]["findings"]:
        hit = sorted(w for w in words if re.search(rf"\b{w}", x["name"].lower() + " " + " ".join(x.get("aliases", [])).lower()))
        if hit:
            warns.append(f"{x['id']}: finding name/aliases mention gold term(s) {hit} — rename unless the test is named that way clinically")
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
