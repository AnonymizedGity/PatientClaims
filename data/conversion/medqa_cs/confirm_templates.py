"""Confirm denials that rest on September-2024 template answers against the June-2024 release.

The September 2024 MedQA-CS release (data/raw/medqa_cs) is a reworded version of the
June 2024 upload (data/raw/medqa_cs_2024-06). The rewording replaced short "No."/"None."
answers with stock phrases ("No, I do not.", "No changes.", ...). For every patient fact built
on such an answer, this script records what the June release says and stops if the June
answer is not a plain denial.
"""
import importlib.util
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
spec = importlib.util.spec_from_file_location("inv", HERE / "build_source_inventory.py")
inv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inv)

TEMPLATES = {"No changes.", "No, there isn't.", "No, I do not.", "No, I am not.", "Not really."}
PLAIN_DENIAL = re.compile(r"^(no|none|nothing|not really)\.?$", re.I)


def opening(folder, cid):
    rows = json.loads((folder / "med-student.json").read_text(encoding="utf-8"))
    return inv.section_input(rows, "diagnosis", cid)["opening"]


def qa(text):
    block = inv.between(text, "Question Patient Response:",
                        ["Physical Examination:", "Physical Exam:", "Sample Closure", "\nClosure:"]) or ""
    return inv.parse_qa(block)


def main():
    sep_rows = json.loads((ROOT / "data/raw/medqa_cs/med-student.json").read_text(encoding="utf-8"))
    jun_rows = json.loads((ROOT / "data/raw/medqa_cs_2024-06/med-student.json").read_text(encoding="utf-8"))
    total_answers = total_facts = 0
    for src_path in sorted((HERE / "source").glob("*.json")):
        src = json.loads(src_path.read_text(encoding="utf-8"))
        cid = src["source_case_id"]
        qa_s = qa(inv.section_input(sep_rows, "diagnosis", cid)["opening"])
        qa_j = qa(inv.section_input(jun_rows, "diagnosis", cid)["opening"])
        offset = 1 if src["chief_complaint"] else 0
        june = {}
        for n, (s, j) in enumerate(zip(qa_s, qa_j)):
            if s["answer"] in TEMPLATES:
                fid = f"{src['case_id']}-p{n - offset + 1:03d}"
                assert any(q["fact_id"] == fid and q["answer"] == s["answer"] for q in src["qa"]), fid
                if not PLAIN_DENIAL.match(j["answer"].strip()):
                    sys.exit(f"{fid}: June answer is not a plain denial: {j['answer']!r}")
                june[fid] = j["answer"]
        if not june:
            continue
        path = HERE / "annotations" / f"{src['case_id']}.json"
        a = json.loads(path.read_text(encoding="utf-8"))
        n_facts = 0
        for f in a["patient_facts"]:
            hits = [s for s in f["source_ids"] if s in june]
            if not hits:
                continue
            if f["assertion"] != "absent":
                sys.exit(f"{f['id']}: built on a template denial but marked {f['assertion']}")
            note = "Sep-2024 template answer; the June-2024 release reads " + \
                   ", ".join(f"'{june[s]}' ({s.rsplit('-', 1)[1]})" for s in hits) + " — denial confirmed."
            f["flags"] = [x for x in f.get("flags", []) if not re.search(r"template|No changes|June-2024", x)] + [note]
            n_facts += 1
        phrases = sorted({q["answer"] for q in src["qa"] if q["fact_id"] in june})
        summary = (f"{len(june)} template answers ({', '.join(phrases)}) checked against the June-2024 release: "
                   f"all are plain denials there; {n_facts} facts confirmed.")
        a["qc"]["annotator_notes"] = [x for x in a["qc"]["annotator_notes"] if "June-2024 release" not in x] + [summary]
        path.write_text(json.dumps(a, ensure_ascii=False, indent=2), encoding="utf-8")
        total_answers += len(june)
        total_facts += n_facts
        print(f"{src['case_id']}: {len(june)} template answers, {n_facts} facts confirmed")
    print(f"total: {total_answers} template answers, {total_facts} facts")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
