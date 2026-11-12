"""Build one source-inventory JSON per selected AgentClinic-MedQA Extended case.

Case set: the 150 adult, conversation-capable cases listed in selected_150.json (1-based source row
numbers): case agentclinic-medqa-ext-NNN = raw row NNN-1.

Patient fragments, in this order:
  cc   = Symptoms.Primary_Symptom
  p001 = History, then Secondary_Symptoms (one id each), Past_Medical_History,
         Social_History, Review_of_Systems, then medication and family-history fields.
Objective findings are flattened to leaves with their source paths:
  eNNN = Physical_Examination_Findings leaves, iNNN = Test_Results leaves.
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RAW = ROOT / "data" / "raw" / "agentclinic" / "agentclinic_medqa_extended.jsonl"
POOL_MANIFEST = HERE.parent / "pools" / "agentclinic_medqa_extended" / "manifest.json"
OUT = HERE / "source"
# Medications, drug and family history (present in 9 cases) come last.
FIELD_ORDER = ["Past_Medical_History", "Social_History", "Review_of_Systems",
               "Current_Medications", "Medications", "Drug_History", "Family_History"]


def leaves(node, path):
    if isinstance(node, dict):
        for k, v in node.items():
            yield from leaves(v, f"{path}.{k}")
    elif isinstance(node, list):
        yield path, "; ".join(str(x) for x in node)
    else:
        yield path, str(node)


def main():
    raw = [json.loads(line) for line in RAW.read_text(encoding="utf-8").splitlines() if line.strip()]
    selected = json.loads((HERE / "selected_150.json").read_text(encoding="utf-8"))
    flags = {r["source_row_index_zero_based"]: r for r in json.loads(POOL_MANIFEST.read_text(encoding="utf-8"))["records"]}
    OUT.mkdir(exist_ok=True)
    for n in selected:
        o = raw[n - 1]["OSCE_Examination"]
        pa = o["Patient_Actor"]
        cid = f"agentclinic-medqa-ext-{n:03d}"
        sym = pa.get("Symptoms", {})
        frags = [("History", pa.get("History", ""))]
        frags += [("Secondary_Symptoms", s) for s in sym.get("Secondary_Symptoms", [])]
        frags += [(f, pa[f] if isinstance(pa[f], str) else json.dumps(pa[f], ensure_ascii=False))
                  for f in FIELD_ORDER if f in pa]
        extra = sorted(set(pa) - {"Demographics", "History", "Symptoms", *FIELD_ORDER})
        frags += [(f, json.dumps(pa[f], ensure_ascii=False)) for f in extra]
        exam = list(leaves(o["Physical_Examination_Findings"], "Physical_Examination_Findings"))
        tests = list(leaves(o.get("Test_Results", {}), "Test_Results"))
        rec = flags.get(n - 1, {})
        case = {
            "case_id": cid,
            "source_row": n,
            "demographics_text": pa.get("Demographics", ""),
            "objective_for_doctor": o.get("Objective_for_Doctor", ""),
            "chief_complaint": sym.get("Primary_Symptom", ""),
            "fragments": [{"fact_id": f"{cid}-p{i:03d}", "field": f, "text": t} for i, (f, t) in enumerate(frags, 1) if str(t).strip()],
            "exam_leaves": [{"exam_id": f"{cid}-e{i:03d}", "path": p, "text": t} for i, (p, t) in enumerate(exam, 1)],
            "test_leaves": [{"exam_id": f"{cid}-i{i:03d}", "path": p, "text": t} for i, (p, t) in enumerate(tests, 1)],
            "correct_diagnosis": o.get("Correct_Diagnosis", ""),
            "pool_flags": {"visible_gold_alias_partitions": rec.get("visible_gold_alias_partitions", []),
                           "requires_diagnosis_text_cleanup": rec.get("requires_diagnosis_text_cleanup", False)},
        }
        (OUT / f"{cid}.json").write_text(json.dumps(case, ensure_ascii=False, indent=2), encoding="utf-8")
    print(len(selected), "cases written to", OUT)


if __name__ == "__main__":
    main()
