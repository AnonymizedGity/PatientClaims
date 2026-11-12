"""Build the AgentClinic-MedQA Extended release in the common case schema.

Writes release/agentclinic_{patient,environment,gold,qc}.jsonl and release/manifest.json.
Refuses to build unless all 150 bundles exist and pass both validators.
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
    expected = sorted(p.stem for p in SOURCE.glob("agentclinic-medqa-ext-*.json"))
    have = sorted(p.stem for p in BUNDLES.glob("agentclinic-medqa-ext-*.json"))
    if have != expected:
        sys.exit(f"missing bundles ({len(set(expected) - set(have))}): {sorted(set(expected) - set(have))[:10]}")
    for cmd in ([sys.executable, "-I", str(HERE.parent / "validate_cases.py"), "--bundles", str(BUNDLES)],
                [sys.executable, "-I", str(HERE / "check_coverage.py")]):
        if subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8").returncode:
            sys.exit(f"validation failed: {Path(cmd[2]).name} — run it to see the errors")
    OUT.mkdir(exist_ok=True)
    parts = ("patient", "environment", "gold", "qc")
    handles = {p: (OUT / f"agentclinic_{p}.jsonl").open("w", encoding="utf-8") for p in parts}
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
        stats["source_issues"] += len(b["qc"].get("source_issues", []))
        stats["cases_with_leakage_entries"] += bool(b["qc"].get("leakage"))
    for h in handles.values():
        h.close()
    manifest = {
        "dataset": "agentclinic_medqa_extended",
        "schema": "case_schema v1 (data/conversion/case_schema.md)",
        "world": "open",
        "cases": stats["cases"],
        "source": "AgentClinic-MedQA Extended (synthetic OSCE cases generated from MedQA), "
                  "150 adult conversation-capable cases (selected_150.json)",
        "built_from": "data/raw/agentclinic via data/conversion/agentclinic/{source,bundles}",
        "stats": dict(stats),
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest["stats"], indent=2))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
