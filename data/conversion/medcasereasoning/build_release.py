"""Build the MedCaseReasoning (test split) release in the common case schema.

Writes release/medcasereasoning_{patient,environment,gold,qc}.jsonl and release/manifest.json.
Refuses to build unless every selected case has a bundle and all pass both validators.
"""
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BUNDLES, OUT, SOURCE = HERE / "bundles", HERE / (sys.argv[1] if len(sys.argv) > 1 else "release"), HERE / "source"


def main():
    expected = sorted(p.stem for p in SOURCE.glob("mcr-test-*.json"))
    have = sorted(p.stem for p in BUNDLES.glob("mcr-test-*.json"))
    if have != expected:
        sys.exit(f"missing bundles ({len(set(expected) - set(have))}): {sorted(set(expected) - set(have))[:10]}")
    for cmd in ([sys.executable, "-I", str(HERE.parent / "validate_cases.py"), "--bundles", str(BUNDLES)],
                [sys.executable, "-I", str(HERE / "check_coverage.py")]):
        if subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8").returncode:
            sys.exit(f"validation failed: {Path(cmd[2]).name} — run it to see the errors")
    OUT.mkdir(exist_ok=True)
    parts = ("patient", "environment", "gold", "qc")
    handles = {p: (OUT / f"medcasereasoning_{p}.jsonl").open("w", encoding="utf-8") for p in parts}
    stats = Counter()
    for cid in expected:
        b = json.loads((BUNDLES / f"{cid}.json").read_text(encoding="utf-8"))
        for p in parts:
            handles[p].write(json.dumps(b[p], ensure_ascii=False) + "\n")
        facts, findings = b["patient"]["facts"], b["environment"]["findings"]
        stats["cases"] += 1
        stats["facts"] += len(facts)
        stats["child_facts"] += sum("parent" in f for f in facts)
        stats["absent_facts"] += sum(f["polarity"] == "absent" for f in facts)
        stats["findings"] += len(findings)
        for x in findings:
            stats[f"findings_{x['kind']}"] += 1
        stats["gold_aliases"] += len(b["gold"]["aliases"])
        stats["findings_with_time"] += sum("time" in x for x in findings)
        stats["source_issues"] += len(b["qc"].get("source_issues", []))
        stats["cases_with_leakage_entries"] += bool(b["qc"].get("leakage"))
    for h in handles.values():
        h.close()
    manifest = {
        "dataset": "medcasereasoning",
        "schema": "case_schema v1 (data/conversion/case_schema.md)",
        "world": "open",
        "cases": stats["cases"],
        "source": "MedCaseReasoning test split (zou-lab/MedCaseReasoning); 100 adult cases chosen for dialogue "
                  "simulation in two screening passes (see selection/README.md). case_id = mcr-test-<dataset index>",
        "built_from": "data/raw/medcasereasoning/test.parquet via data/conversion/medcasereasoning/{selection,source,bundles}",
        "gold_reasoning": "gold.reasoning holds the source diagnostic_reasoning verbatim",
        "stats": dict(stats),
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest["stats"], indent=2))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
