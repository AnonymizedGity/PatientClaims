"""Build the MedQA-CS release in the common case schema from validated bundles.

Writes release/medqa_cs_{patient,environment,gold,qc}.jsonl and release/manifest.json.
Refuses to build unless all 35 bundles exist and pass both validators.
"""
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUNDLES, OUT = HERE / "bundles", HERE / (sys.argv[1] if len(sys.argv) > 1 else "release")  # output folder
SOURCE = HERE / "source"


def main():
    expected = sorted(p.stem for p in SOURCE.glob("medqa-cs-*.json"))
    have = sorted(p.stem for p in BUNDLES.glob("medqa-cs-*.json"))
    if have != expected:
        sys.exit(f"missing bundles: {sorted(set(expected) - set(have))}")
    for cmd in ([sys.executable, "-I", str(HERE.parent / "validate_cases.py"), "--bundles", str(BUNDLES)],
                [sys.executable, "-I", str(HERE / "check_coverage.py")]):
        if subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8").returncode:
            sys.exit(f"validation failed: {' '.join(cmd[2:3])} — run it to see the errors")
    OUT.mkdir(exist_ok=True)
    parts = ("patient", "environment", "gold", "qc")
    handles = {p: (OUT / f"medqa_cs_{p}.jsonl").open("w", encoding="utf-8") for p in parts}
    stats = Counter()
    for cid in expected:
        b = json.loads((BUNDLES / f"{cid}.json").read_text(encoding="utf-8"))
        for p in parts:
            handles[p].write(json.dumps(b[p], ensure_ascii=False) + "\n")
        facts = b["patient"]["facts"]
        stats["cases"] += 1
        stats["facts"] += len(facts)
        stats["child_facts"] += sum("parent" in f for f in facts)
        stats["absent_facts"] += sum(f["polarity"] == "absent" for f in facts)
        stats["findings"] += len(b["environment"]["findings"])
        stats["initial_findings"] += sum(bool(x.get("initial")) for x in b["environment"]["findings"])
        stats["gold_aliases"] += len(b["gold"]["aliases"])
        stats["source_issues"] += len(b["qc"].get("source_issues", []))
    for h in handles.values():
        h.close()
    manifest = {
        "dataset": "medqa_cs",
        "schema": "case_schema v1 (data/conversion/case_schema.md)",
        "world": "open",
        "cases": stats["cases"],
        "source": "bio-nlp/MedQA-CS (CC BY-NC 4.0), Hugging Face release 2024-09-27, 35 adult cases; "
                  "template answers checked against the 2024-06-12 release",
        "built_from": "data/raw/medqa_cs via data/conversion/medqa_cs/{source,annotations,bundles}",
        "stats": dict(stats),
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest["stats"], indent=2))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
