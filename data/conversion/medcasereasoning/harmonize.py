"""Cross-batch harmonisation of the MedCaseReasoning bundles (explicit, reviewed edits; idempotent).

Run after all batches pass both validators; the edits come from scan.py and the batch reports.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUNDLES = HERE / "bundles"

# Scope-level denials are blanket denials: standard "other <scope> symptoms" items.
ITEMS = {
    "01919": {"f018": ("neurological symptoms", "other neurological symptoms"),
              "f020": ("autonomic symptoms", "other autonomic symptoms")},
    "13891": {"f014": ("autonomic symptoms", "other autonomic symptoms")},
    "02548": {"f019": ("stomach or bowel problems", "other stomach or bowel symptoms")},
    "13248": {"f008": ("stomach or bowel symptoms", "other stomach or bowel symptoms")},
    "10805": {"f005": ("other gastrointestinal symptoms", "other stomach or bowel symptoms")},
    "11842": {"f013": ("breathing or chest symptoms", "other breathing or chest symptoms")},
    "06156": {"f017": ("general symptoms", "other whole-body symptoms")},
    "07236": {"f017": ("other general symptoms", "other whole-body symptoms")},
}

# "Progressive" in front of a list of symptoms applies to all of them: one standalone fact.
COURSE = {"10584": "f002", "11154": "f002", "11842": "f002"}

# "Vital signs were stable/normal" as one record: one record per standard parameter.
VITALS = {"13891": "x001", "14153": "x001"}
PARAMS = [("blood pressure", ["BP"]), ("heart rate", ["pulse", "HR"]), ("temperature", ["temp"]),
          ("respiratory rate", ["breathing rate", "RR"])]

GOLD_ALIASES = {
    "01508": (["prolactinoma"], "'Prolactinoma' is the everyday clinical name; the imaging shows the size."),
}


def edit(cid, b):
    changed = []
    q = b["qc"]
    facts = {f["id"]: f for f in b["patient"]["facts"]}
    for fid, (old, new) in ITEMS.get(cid, {}).items():
        f = facts[fid]
        if f["item"] == new:
            continue
        assert f["item"] == old and f["polarity"] == "absent", (cid, fid, f["item"])
        f["item"] = new
        changed.append(f"{fid}.item")
    if cid in COURSE:
        f = facts[COURSE[cid]]
        if "parent" in f:
            assert f["attribute"] == "course", (cid, f)
            for k in ("parent", "attribute"):
                del f[k]
            f.update({"item": "course of the symptoms", "text": "These have all been getting worse.", "system": "general"})
            q.setdefault("flags", {})[f["id"]] = ["'Progressive' stands before the whole list of presenting symptoms, so it is one "
                                   "standalone fact for all of them (harmonisation)."]
            changed.append(f"{f['id']} standalone course")
    if cid in VITALS:
        xs = b["environment"]["findings"]
        x = next(x for x in xs if x["id"] == VITALS[cid])
        if x["name"] == "vital signs":
            n = max(int(y["id"][1:]) for y in xs)
            src, flags = q["finding_sources"][x["id"]], q.get("finding_flags", {}).get(x["id"])
            x.update({"name": PARAMS[0][0], "aliases": PARAMS[0][1]})
            for i, (name, aliases) in enumerate(PARAMS[1:], 1):
                new = {"id": f"x{n + i:03d}", "kind": "vital", "name": name, "aliases": aliases, "result": x["result"]}
                xs.append(new)
                q["finding_sources"][new["id"]] = dict(src)
                if flags:
                    q.setdefault("finding_flags", {})[new["id"]] = list(flags)
            q.setdefault("notes", []).append(
                "Harmonisation: the single 'vital signs' record was split into one record per standard parameter "
                "with the source's word; no oxygen saturation, which the source does not mention.")
            changed.append("vitals split")
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
    for p in sorted(BUNDLES.glob("mcr-test-*.json")):
        cid = p.stem[len("mcr-test-"):]
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
