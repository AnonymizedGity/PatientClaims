"""Build one source-inventory JSON per adult MedQA-CS case.

The inventory is deterministic: it only splits the raw SP sheet into the
patient Q/A script, doorway vital signs, SP acting notes, the patient-note
history and examination lines, and the examiner's diagnosis key. Clinical
annotation is done separately on top of these files.

Usage: python build_source_inventory.py
"""
import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RAW = ROOT / "data" / "raw" / "medqa_cs"
OUT = Path(__file__).resolve().parent / "source"

# Paediatric / caregiver-reported cases are excluded (35 adult cases remain).
EXCLUDED = {6, 18, 19, 25, 30, 32, 40, 41, 42}


def load(name):
    return json.loads((RAW / name).read_text(encoding="utf-8"))


def section_input(rows, section, cid):
    row = next(r for r in rows if r["section"] == section and r["case_id"] == cid)
    inp = row["input"]
    return inp if isinstance(inp, dict) else ast.literal_eval(inp)


def between(text, start, ends):
    i = text.find(start)
    if i < 0:
        return None
    i += len(start)
    j = min([k for k in (text.find(e, i) for e in ends) if k >= 0] or [len(text)])
    return text[i:j].strip()


def bullets(block):
    if not block:
        return []
    return [re.sub(r"^[-•*]\s*", "", ln).strip() for ln in block.splitlines() if ln.strip()]


def unquote(s):
    s = s.strip()
    if len(s) >= 2 and s[0] in "\"“" and s[-1] in "\"”":
        s = s[1:-1]
    return s.strip()


PATIENT = re.compile(r"^Patient(?: response)?:\s*", re.I)


def parse_qa(block):
    """Split the Question/Patient Response script into ordered Q/A pairs.

    Source layouts vary: 'Topic:' lines or bare/quoted topic lines ending in ':',
    'Doctor:' on its own line or after the topic on the same line, quoted
    questions without a 'Doctor:' label (follow-ups inherit the previous topic),
    and 'Patient:' or 'Patient response:' answers.
    """
    items, topic = [], None
    lines = [ln.strip() for ln in block.splitlines()]
    i = 0
    while i < len(lines):
        ln = lines[i]
        if not ln or PATIENT.match(ln):
            i += 1
            continue
        if "Doctor:" in ln and not ln.startswith("Doctor:"):
            head, ln = ln.split("Doctor:", 1)
            topic = re.sub(r'^["“]?Topic:\s*', "", head.strip()).strip().strip('"“”:').strip()
            ln = "Doctor:" + ln
        is_question = ln.startswith("Doctor:") or (ln[0] in "\"“" and not ln.rstrip().endswith(":")
                                                   and not re.match(r'^["“]Topic:', ln))
        if not is_question:
            topic = re.sub(r'^["“]?Topic:\s*', "", ln).strip().strip('"“”: ')
            i += 1
            continue
        q = ln[len("Doctor:"):] if ln.startswith("Doctor:") else ln
        j = i + 1
        while j < len(lines) and not PATIENT.match(lines[j]):
            if lines[j]:
                q += " " + lines[j]
            j += 1
        if j >= len(lines):
            break
        a = PATIENT.sub("", lines[j])
        k = j + 1
        while k < len(lines) and lines[k] and not re.match(r'^(Topic:|Doctor:|["“])', lines[k]) \
                and not lines[k].endswith(":") and "Doctor:" not in lines[k]:
            a += " " + lines[k]
            k += 1
        items.append({"topic": (topic or "").strip(), "question": unquote(q), "answer": unquote(a)})
        i = k
    return items


def main():
    student, exam = load("med-student.json"), load("med-exam.json")
    OUT.mkdir(parents=True, exist_ok=True)
    report = []
    for cid in sorted({r["case_id"] for r in student}):
        if cid in EXCLUDED:
            continue
        opening = section_input(student, "diagnosis", cid)["opening"]
        ex = section_input(exam, "diagnosis", cid)
        scenario = between(opening, "Opening Scenario:", ["Vital Signs"]) or ""
        scenario = re.sub(r"^\s*Patient Presentation:\s*", "", scenario).strip()
        vitals = bullets(between(opening, "Vital Signs:", ["Examinee Tasks"]))
        sp_notes = bullets(between(opening, "Notes for the SP:", ["Challenging Questions"]))
        challenging = bullets(between(opening, "Challenging Questions to Ask:", ["Sample Examinee Response", "Examinee Response", "Examinee Checklist"]))
        qa_block = between(opening, "Question Patient Response:",
                           ["Physical Examination:", "Physical Exam:", "Sample Closure", "\nClosure:"]) or ""
        qa = parse_qa(qa_block)
        note = opening[opening.find("Patient Note"):] if "Patient Note" in opening else ""
        # the heading is "Patient Note:" in most cases but "Patient Note" without a colon in some (e.g. case 8)
        note_history = (between(note, "Patient Note", ["Physical Examination:", "Physical Exam:"]) or "").lstrip(":").strip()
        pe_block = between(note, "Physical Examination:", ["Data Interpretation", "Diagnostic Workup", "Differential Diagnosis", "Workup:"]) or ""
        pe_lines = [ln.strip() for ln in pe_block.splitlines() if ln.strip()]
        sid = f"medqa-cs-{cid:03d}"
        cc, rest = (qa[0], qa[1:]) if qa and "complaint" in qa[0]["topic"].lower() else (None, qa)
        case = {
            "case_id": sid,
            "source_case_id": cid,
            "opening_scenario": scenario,
            "doorway_vital_signs": vitals,
            "sp_notes": sp_notes,
            "challenging_questions": challenging,
            "chief_complaint": cc,
            "qa": [{"fact_id": f"{sid}-p{n:03d}", **item} for n, item in enumerate(rest, 1)],
            "patient_note_history": note_history,
            "exam_lines": [{"exam_id": f"{sid}-e{n:03d}", "source_text": ln} for n, ln in enumerate(pe_lines, 1)],
            "gold_target": ex.get("target", ""),
            "gold_additional_diagnosis": ex.get("additional_diagnosis", ""),
            "raw_opening": opening,
        }
        (OUT / f"{sid}.json").write_text(json.dumps(case, ensure_ascii=False, indent=2), encoding="utf-8")
        report.append((sid, len(case["qa"]), bool(cc), len(case["exam_lines"]), len(vitals), len(sp_notes)))
    for r in report:
        print(*r, sep="\t")
    print(len(report), "cases")


if __name__ == "__main__":
    main()
