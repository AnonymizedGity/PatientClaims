"""Reviewer harmonisation pass over the MedQA-CS bundles (after the four conversion batches).

Each edit is listed explicitly and logged in the case's qc.notes. Rules applied
(also in ../case_schema.md):
1. An item names a finding; a normal state is that finding absent
   ("appetite: I have a good appetite" -> "loss of appetite", absent).
2. A child fact has its parent's category (and system, for symptoms).
3. Contraception: hormonal or device methods are `medication`; condoms,
   withdrawal and a partner's vasectomy are `habit_exposure`.
4. A numeric score on a 0-10 scale carries `scale: [0, 10]`.
"""
import json
import sys
from pathlib import Path

BUNDLES = Path(__file__).resolve().parent / "bundles"
NOTE = "Harmonisation pass: "

FINDING_ITEMS = {  # case: {fact: (new item, aliases)} -> polarity absent
    "015": {"f019": ("loss of appetite", ["poor appetite"])},
    "034": {"f008": ("loss of appetite", ["poor appetite"])},
    "039": {"f012": ("loss of appetite", ["poor appetite"])},
    "028": {"f006": ("feeling unwell today", ["how you feel today"])},
}
CHILD_CATEGORY = {"023": ["f051"], "027": ["f047"], "028": ["f012", "f016"]}
CATEGORY = {"005": {"f039": "habit_exposure"}}
SCALE_0_10 = {
    "001": ["f005"], "003": ["f005"], "009": ["f018"], "010": ["f005"], "013": ["f006"], "014": ["f007"],
    "020": ["f012"], "021": ["f008", "f014"], "024": ["f009"], "027": ["f017"], "028": ["f011"],
    "031": ["f005"], "043": ["f024"],
}
# 5. Blanket denials use the standard items (chronic medical problems / other medical problems).
ITEM = {
    "003": {"f027": "chronic medical problems"}, "005": {"f035": "chronic medical problems"},
    "009": {"f041": "chronic medical problems"}, "010": {"f030": "chronic medical problems"},
    "012": {"f029": "chronic medical problems"}, "016": {"f030": "chronic medical problems"},
    "015": {"f040": "other medical problems"}, "028": {"f030": "other medical problems"},
}
# 6. Sleep complaints (and their children) have system general.
SYSTEM_GENERAL = {"027": ["f030", "f031"], "029": ["f001", "f002", "f003", "f004", "f005", "f006", "f007", "f008", "f009", "f014"],
                  "033": ["f008", "f009"]}


def main():
    cases = sorted({*FINDING_ITEMS, *CHILD_CATEGORY, *CATEGORY, *SCALE_0_10, *ITEM, *SYSTEM_GENERAL})
    for num in cases:
        path = BUNDLES / f"medqa-cs-{num}.json"
        b = json.loads(path.read_text(encoding="utf-8"))
        facts = {f["id"]: f for f in b["patient"]["facts"]}
        log = []
        for fid, (item, aliases) in FINDING_ITEMS.get(num, {}).items():
            f = facts[fid]
            log.append(f"{fid} '{f['item']}' ({f['polarity']}) -> '{item}' (absent)")
            f["item"], f["polarity"] = item, "absent"
            f["aliases"] = sorted(set(f.get("aliases", [])) | set(aliases))
        for fid in CHILD_CATEGORY.get(num, []):
            f, parent = facts[fid], facts[facts[fid]["parent"]]
            log.append(f"{fid} category {f['category']} -> {parent['category']} (parent {parent['id']})")
            f["category"] = parent["category"]
            if parent.get("system"):
                f["system"] = parent["system"]
            else:
                f.pop("system", None)
            if f["category"] == "medication" and f.get("attribute") == "other":
                f["attribute"] = "treatment_response"
        for fid, cat in CATEGORY.get(num, {}).items():
            log.append(f"{fid} category {facts[fid]['category']} -> {cat}")
            facts[fid]["category"] = cat
        for fid in SCALE_0_10.get(num, []):
            f = facts[fid]
            assert isinstance(f.get("value"), (int, float)) and 0 <= f["value"] <= 10, (num, fid)
            f["scale"] = [0, 10]
        if SCALE_0_10.get(num):
            log.append("scale [0, 10] added to " + ", ".join(SCALE_0_10[num]))
        for fid, item in ITEM.get(num, {}).items():
            log.append(f"{fid} item -> '{item}' (blanket denial)")
            facts[fid]["item"] = item
        if SYSTEM_GENERAL.get(num):
            log.append("system general (sleep) for " + ", ".join(SYSTEM_GENERAL[num]))
            for fid in SYSTEM_GENERAL[num]:
                facts[fid]["system"] = "general"
        b["qc"]["notes"] = [n for n in b["qc"].get("notes", []) if not n.startswith(NOTE)] + [NOTE + "; ".join(log) + "."]
        path.write_text(json.dumps(b, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"medqa-cs-{num}: " + "; ".join(log))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
