"""Build per-case source files for the selected MedCaseReasoning test cases.

Reads selection/selected.json and the raw test split; writes source/<case_id>.json with the case
prompt split into numbered sentences (s001, …), the gold fields, and the selection notes. The
article title, full text and link are left out: they contain the diagnosis.

Usage: python -I build_source_inventory.py
"""
import json
import re
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RAW = ROOT / "data" / "raw" / "medcasereasoning" / "test.parquet"
OUT = HERE / "source"

ABBREV = r"(?:e\.g|i\.e|vs|Dr|Drs|Mr|Mrs|Ms|St|Fig|Figs|approx|No|Nos|ca|cf|al|Inc|Ltd|Jr|Sr|Prof|mo|yr|yrs|min|max|resp|op|dept)\."
PROTECT = "\u0000"


def sentences(text):
    out = []
    for para in (p.strip() for p in text.split("\n")):
        if not para:
            continue
        para = re.sub(ABBREV, lambda m: m.group(0).replace(".", PROTECT), para)
        for s in re.split(r"(?<=[.!?])\s+(?=[\"“(\[]?[A-Z0-9])", para):
            s = s.replace(PROTECT, ".").strip()
            if s:
                out.append(s)
    return out


def main():
    sel = json.loads((HERE / "selection" / "selected.json").read_text(encoding="utf-8"))
    screen = {json.loads(l)["idx"]: json.loads(l) for l in (HERE / "selection" / "screen_all.jsonl").open(encoding="utf-8")}
    second = {}
    for p in sorted((HERE / "selection" / "second_look").glob("part_*.jsonl")):
        second.update({json.loads(l)["idx"]: json.loads(l) for l in p.open(encoding="utf-8")})
    te = pd.read_parquet(RAW)
    OUT.mkdir(exist_ok=True)
    n_sent = 0
    for r in sel:
        rows = te.index[te["Unnamed: 0"] == r["test_index"]].tolist()
        assert len(rows) == 1 and te.loc[rows[0], "pmcid"] == r["pmcid"], r
        row = te.loc[rows[0]]
        cid = f"mcr-test-{r['test_index']:05d}"
        sents = sentences(row["case_prompt"])
        assert re.sub(r"\s+", "", "".join(sents)) == re.sub(r"\s+", "", row["case_prompt"]), cid
        n_sent += len(sents)
        s1, s2 = screen[r["idx"]], second[r["idx"]]
        src = {
            "case_id": cid, "pmcid": r["pmcid"], "test_row": int(rows[0]), "test_index": r["test_index"],
            "case_prompt": row["case_prompt"],
            "sentences": [{"id": f"s{i:03d}", "text": s} for i, s in enumerate(sents, 1)],
            "final_diagnosis": row["final_diagnosis"].strip(),
            "diagnostic_reasoning": row["diagnostic_reasoning"],
            "selection": {
                "age": s1["age"], "sex": s1["sex"], "specialty": s2["specialty"], "dx_key": s2["dx_key"],
                "setting": s1["setting"], "time_structure": s1["time_structure"], "leakage": s1["leakage"],
                "narrative_conclusion": s2["narrative_conclusion"], "interview_value": s2["interview_value"],
                "screen_reason": s1["reason"], "second_look_note": s2["note"],
            },
        }
        (OUT / f"{cid}.json").write_text(json.dumps(src, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(sel)} cases, {n_sent} sentences")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
