"""Cross-case audit of the annotations (beyond schema validation).

Checks that quotes come from the cited source answers, lists polarity
candidates for human review, and compares annotation habits across batches.
"""
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC, ANN = HERE / "source", HERE / "annotations"
BATCHES = {
    "ref": ["001"],
    "A": ["002", "003", "004", "005", "007", "008", "009", "010", "011"],
    "B": ["012", "013", "014", "015", "016", "017", "020", "021", "022"],
    "C": ["023", "024", "026", "027", "028", "029", "031", "033"],
    "D": ["034", "035", "036", "037", "038", "039", "043", "044"],
}
BARE_NO = re.compile(r"^(no|nope|none|never|no, i (am|do|don't|have)( not)?|no, (there|it) (isn't|is not|wasn't))[.!]?$", re.I)


def norm(s):
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"').replace("—", "-").replace("–", "-")
    return re.sub(r"\s+", " ", s).strip().strip('"').lower()


def main():
    by_batch = defaultdict(Counter)
    quote_problems, polarity_review, absent_long = [], [], []
    for batch, nums in BATCHES.items():
        for n in nums:
            cid = f"medqa-cs-{n}"
            path = ANN / f"{cid}.json"
            if not path.exists():
                continue
            src = json.loads((SRC / f"{cid}.json").read_text(encoding="utf-8"))
            a = json.loads(path.read_text(encoding="utf-8"))
            answers = {q["fact_id"]: q["answer"] for q in src["qa"]}
            if src.get("chief_complaint"):
                answers["cc"] = src["chief_complaint"]["answer"]
            note = src.get("patient_note_history", "")
            c = by_batch[batch]
            c["cases"] += 1
            c["qa"] += len(src["qa"])
            for f in a["patient_facts"]:
                c["facts"] += 1
                c[f"assert_{f['assertion']}"] += 1
                c[f"temp_{f['temporality']}"] += 1
                pool = " ".join(answers.get(s, "") for s in f["source_ids"]) + (" " + note if "note" in f["source_ids"] else "")
                parts = [p for p in re.split(r"\s+/\s+", f.get("quote", "")) if p.strip()]
                if any(norm(p).rstrip(".") not in norm(pool) for p in parts):
                    quote_problems.append(f"{f['id']}: quote not found in cited answers: {f.get('quote')!r}")
                srcs = [s for s in f["source_ids"] if s in answers]
                if f["assertion"] == "present" and srcs and all(BARE_NO.match(answers[s].strip()) for s in srcs):
                    polarity_review.append(f"{f['id']} PRESENT but answer is a bare no: {f['text']!r}")
                if f["assertion"] == "absent" and srcs and not any(re.search(r"\b(no|not|never|none|denies|nothing|neither|nor|without)\b|n't|n’t", answers[s], re.I) for s in srcs):
                    absent_long.append(f"{f['id']} ABSENT but answer has no negation word: {f['text']!r} <- {answers[srcs[0]][:80]!r}")
            env = a["clinical_environment"]
            c["env"] += sum(len(env[k]) for k in ("vital_signs", "physical_examination", "investigations"))
            c["sp_note_findings"] += sum(x["source"] == "sp_notes" for x in env["physical_examination"])
            c["source_issues"] += len(a["qc"]["source_issues"])
            c["from_note"] += sum(bool(f.get("from_note")) for f in a["patient_facts"])
    print("batch  cases  facts/qa  absent%  current% recurrent% historical% resolved% unclear%  env/case  sp_findings  issues/case  from_note")
    for b, c in by_batch.items():
        fx = c["facts"] or 1
        print(f"{b:5} {c['cases']:6} {c['facts'] / max(c['qa'], 1):9.2f} {100 * c['assert_absent'] / fx:8.0f} "
              + " ".join(f"{100 * c['temp_' + t] / fx:9.0f}" for t in ("current", "recurrent", "historical", "resolved", "unclear"))
              + f" {c['env'] / max(c['cases'], 1):9.1f} {c['sp_note_findings']:11} {c['source_issues'] / max(c['cases'], 1):11.1f} {c['from_note']:9}")
    for title, items in (("QUOTE PROBLEMS", quote_problems), ("POLARITY: present from a bare 'no'", polarity_review),
                         ("POLARITY: absent without a negation word in the answer", absent_long)):
        print(f"\n{title} ({len(items)})")
        for x in items:
            print("  ", x)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
