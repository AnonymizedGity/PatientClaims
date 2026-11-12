"""Cross-batch harmonisation of the AgentClinic bundles (explicit, reviewed edits; idempotent).

Run after all batches pass both validators; findings come from scan.py.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUNDLES = HERE / "bundles"

# Blanket denials get one label per scope: "other symptoms" (anything not recorded),
# "chronic medical problems" (no history at all), "other medical problems" (history with exceptions).
FACT_EDITS = {
    "127": {"f005": {"item": ("other complaints", "other symptoms")}},
    "144": {"f005": {"item": ("other complaints", "other symptoms")},
            "f003": {"system": ("neurological", "general")},
            "f004": {"system": ("neurological", "general")}},
    "122": {"f010": {"item": ("other body-wide symptoms", "other symptoms")}},
    "123": {"f017": {"item": ("other body-wide symptoms", "other symptoms")}},
    "125": {"f016": {"item": ("other body-wide symptoms", "other symptoms")}},
    "048": {"f006": {"item": ("other whole-body symptoms", "other symptoms")}},
    "174": {"f010": {"item": ("other general symptoms", "other symptoms")}},
    "200": {"f005": {"item": ("other symptoms in the body", "other symptoms")}},
    "090": {"f018": {"item": ("other physical complaints", "other physical symptoms")}},
    "156": {"f012": {"item": ("chronic medical conditions", "chronic medical problems")}},
    "116": {"f009": {"item": ("chronic illnesses", "chronic medical problems")}},
    "205": {"f016": {"item": ("other chronic medical problems", "other medical problems")}},
    "017": {"f009": {"item": ("chronic medical problems", "other medical problems")}},
    "019": {"f012": {"item": ("chronic medical problems", "other medical problems")}},
    "196": {"f009": {"item": ("chronic medical problems", "other medical problems")}},
    "203": {"f010": {"item": ("chronic medical problems", "other medical problems")}},
    # sleep complaints: system general (the batches used general, psychiatric and neurological)
    "128": {"f007": {"system": ("psychiatric", "general")}},
    "131": {"f005": {"system": ("psychiatric", "general")}},
    "140": {"f011": {"system": ("psychiatric", "general")}},
    # breast complaints: system reproductive
    "009": {"f005": {"system": ("skin", "reproductive")}},
    # patient voice: a patient feels a sore lower belly, not a tender uterus
    "010": {"f001": {"item": ("uterine tenderness", "lower belly tenderness"),
                     "text": ("My womb feels tender.", "My lower belly feels tender."),
                     "aliases": (["tender womb", "sore uterus", "lower belly tenderness"],
                                 ["uterine tenderness", "tender womb", "sore uterus"])}},
}

# A bedside examination returns the finding, not the examiner's diagnosis.
FINDING_EDITS = {
    "025": {"x007": ("Present, suggestive of ascites.", "Present.")},
    "054": {"x008": ("Positive: right-sided horizontal nystagmus when moving from sitting to supine, suggestive of BPPV.",
                     "Positive: right-sided horizontal nystagmus when moving from sitting to supine.")},
    "123": {"x007": ("Corneal ulceration with infiltration, suggesting microbial keratitis.",
                     "Corneal ulceration with infiltration.")},
    "212": {"x005": ("Reduced range of motion and crepitus in both knees, indicating osteoarthritis.",
                     "Reduced range of motion and crepitus in both knees.")},
}

# Everyday clinical names of the same diagnosis that the batches left out.
GOLD_ALIASES = {
    "053": (["pancreatic cancer", "pancreatic carcinoma"], "'Pancreatic cancer' is the everyday name of pancreatic adenocarcinoma (about 90% of pancreatic cancers)."),
    "058": (["pancreatic cancer", "pancreatic carcinoma"], "'Pancreatic cancer' is the everyday name of pancreatic adenocarcinoma (about 90% of pancreatic cancers)."),
    "043": (["chronic hepatitis B", "chronic HBV infection"], "'Chronic hepatitis B' accepted: the case separates chronic from acute or resolved infection; activity is a refinement."),
    "202": (["chronic kidney disease", "CKD", "chronic renal insufficiency"], "Same aliases as case 159 (chronic kidney failure)."),
    "116": (["somatic symptom disorder"], "'Somatic symptom disorder' is the DSM-5 successor of somatization disorder."),
    "201": (["somatic symptom disorder"], "'Somatic symptom disorder' is the DSM-5 successor of somatization disorder."),
    "157": (["blunt cardiac injury"], "'Blunt cardiac injury' is the current name for cardiac contusion."),
    "186": (["emphysema"], "Emphysema accepted as in cases 110 and 117; hyperinflation with a flattened diaphragm fits it."),
}


def edit(cid, b):
    changed = []
    q = b["qc"]
    facts = {f["id"]: f for f in b["patient"]["facts"]}
    for fid, fields in FACT_EDITS.get(cid, {}).items():
        f = facts[fid]
        for key, (old, new) in fields.items():
            if f.get(key) == new:
                continue
            assert f.get(key) == old, (cid, fid, key, f.get(key))
            f[key] = new
            changed.append(f"{fid}.{key}")
    findings = {x["id"]: x for x in b["environment"]["findings"]}
    for xid, (old, new) in FINDING_EDITS.get(cid, {}).items():
        x = findings[xid]
        if x["result"] == new:
            continue
        assert x["result"] == old, (cid, xid, x["result"])
        x["result"] = new
        q.setdefault("finding_flags", {}).setdefault(xid, []).append(
            f"Source interpretation removed from the result (source: {old!r}); a bedside examination returns the finding, not the diagnosis.")
        q["leakage"] = [e for e in q.get("leakage", []) if (e.get("id") or e.get("fact_id")) != xid]
        changed.append(f"{xid}.result")
    if cid in GOLD_ALIASES:
        add, note = GOLD_ALIASES[cid]
        new = [a for a in add if a.lower() not in {x.lower() for x in b["gold"]["aliases"]}]
        if new:
            b["gold"]["aliases"].extend(new)
            q.setdefault("notes", []).append(f"Gold aliases added in harmonisation ({', '.join(new)}): {note}")
            changed.append("gold.aliases")
    return changed


def dump(b):
    """Compact layout like the hand-written bundles: one fact, finding or keyed entry per line."""
    j = lambda v: json.dumps(v, ensure_ascii=False)
    parts = []
    for part, body in b.items():
        lines = []
        for k, v in body.items():
            if isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
                lines.append(f"    {j(k)}: [\n" + ",\n".join(f"      {j(x)}" for x in v) + "\n    ]")
            elif isinstance(v, dict) and v and k != "demographics":
                lines.append(f"    {j(k)}: {{\n" + ",\n".join(f"      {j(kk)}: {j(vv)}" for kk, vv in v.items()) + "\n    }")
            else:
                lines.append(f"    {j(k)}: {j(v)}")
        parts.append(f"  {j(part)}: {{\n" + ",\n".join(lines) + "\n  }")
    return "{\n" + ",\n".join(parts) + "\n}\n"


def main():
    total = 0
    for p in sorted(BUNDLES.glob("agentclinic-medqa-ext-*.json")):
        cid = p.stem[-3:]
        b = json.loads(p.read_text(encoding="utf-8"))
        changed = edit(cid, b)
        if changed:
            text = dump(b)
            assert json.loads(text) == b
            p.write_text(text, encoding="utf-8")
            print(cid, ", ".join(changed))
            total += len(changed)
    print(f"{total} edits")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
