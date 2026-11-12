"""Reviewer pass: move commentary out of environment `finding` text into `flags`.

`finding` is what the simulated doctor receives; doubts about the source go in
`flags` (and stay in qc.source_issues). Each edit is listed explicitly.
"""
import json
import sys
from pathlib import Path

ANN = Path(__file__).resolve().parent / "annotations"
NOT_DOC = "Result not documented"

EDITS = {
    "012": {
        "x006": ("Positive", "Side not stated in the source."),
        "x014": (NOT_DOC, "Source reads 'Babinski reflex is 8 bilaterally' — symbol garbled (OCR); direction cannot be recovered."),
        "x017": ("Positive", "Stated positive in the source, but meningeal signs fit neither the history nor the gold differential; likely a source error. Review before use."),
    },
    "014": {"x013": ("Regular rate and rhythm", "Source reads 'Respiratory rate and rhythm' — evidently a mis-expanded 'RRR'.")},
    "015": {"x011": ("Bowel sounds present in all four quadrants", "Source reads 'EF> bowel sounds x 4 quadrants' — OCR artifact, most likely '+'.")},
    "017": {"x028": (NOT_DOC, "Source reads '8 heel to shin' — symbol garbled (OCR); result cannot be recovered.")},
    "022": {
        "x017": (NOT_DOC, "Source reads '8 Dix-Hallpike' — symbol garbled (OCR); positive/negative cannot be recovered. Important for this vertigo case."),
        "x020": (NOT_DOC, "Source reads 'Babinski sign bilaterally' without a direction."),
    },
    "023": {"x009": ("Active bowel sounds", "Source reads 'active bowel sounds four times per minute' — probably meant 'x4 quadrants'.")},
    "024": {
        "x010": ("Tender to palpation over the medial calcaneal tuberosity and plantar fascia", "Side not stated in the source."),
        "x011": ("Plantar heel and arch pain with dorsiflexion of the toes", "Side not stated in the source."),
    },
    "028": {"x021": ("Babinski sign present bilaterally", "Faithful to the source, but clinically implausible next to an otherwise normal neurological exam; likely a source error. Review before use.")},
    "031": {
        "x005": ("S1 and S2 within normal limits", "Source reads '51152 WNL' — OCR artifact for S1/S2."),
        "x012": (NOT_DOC, "Source reads 'Ely's psoas sign' — prefix garbled (OCR); result cannot be recovered."),
        "x013": (NOT_DOC, "Source reads 'Ely's Rovsing sign' — prefix garbled (OCR); result cannot be recovered."),
        "x014": (NOT_DOC, "Source reads '6 obturator sign' — prefix garbled (OCR); result cannot be recovered."),
    },
}


def main():
    for num, edits in EDITS.items():
        path = ANN / f"medqa-cs-{num}.json"
        a = json.loads(path.read_text(encoding="utf-8"))
        done = set()
        for sec in ("vital_signs", "physical_examination", "investigations"):
            for x in a["clinical_environment"][sec]:
                if x["id"] in edits:
                    finding, flag = edits[x["id"]]
                    print(f"{num} {x['id']}: {x['finding']!r} -> {finding!r}")
                    x["finding"] = finding
                    x["flags"] = [f for f in x.get("flags", []) if f != flag] + [flag]
                    done.add(x["id"])
        missing = set(edits) - done
        if missing:
            sys.exit(f"{num}: records not found {missing}")
        note = "Reviewer edit: environment commentary moved from `finding` to `flags` for " + ", ".join(sorted(done)) + "."
        if note not in a["qc"]["annotator_notes"]:
            a["qc"]["annotator_notes"].append(note)
        path.write_text(json.dumps(a, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
