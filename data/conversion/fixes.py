"""Data fixes for the open-world releases (MedQA-CS, AgentClinic, MedCaseReasoning).

Found by an independent check of the converted cases. Edits the bundles; the releases are then built from them.
Idempotent; every edit is logged in the case's qc.notes.

1. MedQA-CS: texts that begin with the question's answer word ("Yes,", "No,", "Well, yes,") lose it; texts that are
   fragments without it, or that point back at the question, are rewritten (REWRITE).
2. Text fixes found in early test dialogues, times (MedQA-CS 013 f015-f018 resolved), labels (028 f014).
3. Facts that hid a second answer get their own fact (marriage, a partner, roommates, caffeine).
4. Medicines whose purpose the source states or the case leaves no doubt about say what they are for.
5. Question names shared by several facts (validator items.same_name: 2 / 11 / 29) are removed from those facts,
   so the open question of the area lists them; a fact that owns the name keeps it.
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
NOTE = "Fixes: "
ANSWER_WORD = re.compile(r"^(?:well,\s*)?(?:yes|no)[,.!]\s+", re.I)

REWRITE = {
    "medqa_cs": {
        # text fixes found in early test dialogues
        "009": {"f023": "My belly hurts everywhere.", "f034": "I feel fatigued.",
                "f035": "I haven't seen any blood in my stool, but I haven't used the bathroom since it happened.",
                "f036": "I haven't seen any blood in my urine, but I haven't used the bathroom since it happened.",
                "f047": "I'm sexually active with my girlfriend of 6 months.",
                "f049": "I drink alcohol, but just occasionally during social gatherings."},
        "010": {"f042": "I'm sexually active with my spouse.",
                "f034": "I've been using oral contraceptives for the past 2 years."},
        "022": {"f008": "I notice it when I get up from bed or lie down to sleep, but it can happen anytime.",
                "f040": "I'm sexually active with my wife.",
                "f033": "I take furosemide for my blood pressure.", "f034": "I take captopril for my blood pressure."},
        "026": {"f047": "I'm sexually active with my spouse."},
        "028": {"f014": "My sex drive has diminished, Doc. I'm not as interested in sex as I used to be.",
                "f036": "In general, I take my medications regularly.",
                "f035": "Six months ago, propranolol was added for my blood pressure.",
                "f038": "I take lovastatin for my cholesterol."},
        "035": {"f014": "The voices and the writing don't tell me to hurt myself or anyone else.",
                "f028": "I haven't seen the writing or heard the voices when I wasn't using drugs.",
                "f038": "I use recreational drugs occasionally.", "f045": "I'm sexually active with my girlfriend."},
        "037": {"f044": "I'm sexually active with my spouse.",
                "f033": "I used to take a lot of laxatives for my constipation, like bisacodyl, but I stopped all of them "
                        "when the diarrhea started."},
        # texts that are fragments or point back at the question once the answer word goes
        "008": {"f018": "I don't have chest pain.",
                "f050": "My treatment has been consistent, and I haven't had any problems with it."},
        "011": {"f024": "I don't have chest pain."},
        "012": {"f040": "I've never used illegal drugs.", "f041": "I don't smoke or use any other tobacco."},
        "016": {"f011": "I have some vaginal itching.",
                "f053": "I haven't really experienced any physical, sexual or emotional abuse."},
        "017": {"f013": "I occasionally have ringing in both ears.", "f039": "I'm sexually active, only with my wife."},
        "020": {"f048": "I don't use condoms; I don't like using them."},
        "021": {"f054": "My drinking hasn't affected my relationships.", "f058": "I'm sexually active with my spouse."},
        "034": {"f059": "I haven't had any head injuries or accidents because of my husband."},
        "036": {"f012": "I haven't noticed any blood in my sputum."},
        "039": {"f051": "I'm sexually active with my boyfriend."},
        "043": {"f013": "I haven't had chills.", "f027": "I don't have nausea.", "f028": "I haven't vomited.",
                "f046": "I'm sexually active with my new girlfriend."},
        "044": {"f026": "I don't have nausea.", "f027": "I haven't vomited.", "f028": "I don't have diarrhea.",
                "f029": "I'm not constipated.", "f048": "I'm sexually active with my spouse."},
    },
    "agentclinic": {
        "118": {"f005": "My mother says it's been happening over the past 7 months."},
    },
    "medcasereasoning": {
        "02741": {"f006": "About eight months ago, at the same time as the vertigo, my left ear started to feel full.",
                  "f007": "A hearing test around the time of the vertigo, about eight months ago, showed I had nerve-type "
                          "(sensorineural) hearing loss in my left ear.",
                  "f010": "After the fever with chills, I noticed my gums had become enlarged."},
        "10717": {"f003": "I get dizzy during my spells of palpitations.",
                  "f004": "I feel lightheaded during my spells of palpitations.",
                  "f005": "I sweat during my spells of palpitations.",
                  "f008": "When my blood sugar was checked during my spells of palpitations and dizziness, it went as low "
                          "as 3.5 mmol/L, and it came up with glucose."},
        "13885": {"f006": "The painful joints in my hands are swollen."},
        "02529": {"f010": "I've been treated for the rash with steroid creams and with steroids for the whole body."},
        "12365": {"f008": "Three weeks ago I was started on Simbrinza drops (brimonidine 0.1%/brinzolamide 0.1%) for my "
                          "glaucoma, twice a day in both eyes."},
    },
}
INFERRED_PURPOSE = {("medqa_cs", "022", "f033"), ("medqa_cs", "022", "f034"), ("medqa_cs", "028", "f038")}

FIELDS = {  # (dataset, case): {fid: {field: value}}
    ("medqa_cs", "013"): {f: {"time": "resolved"} for f in ("f015", "f016", "f017", "f018")},
    ("medqa_cs", "028"): {"f014": {"item": "decreased sex drive"}},
}

# New facts for an answer hidden inside another fact: (item, text, category, source fact whose sources it cites).
NEW_FACTS = {
    "medqa_cs": {
        "010": [("marital status", "I'm married.", "f042")], "013": [("marital status", "I'm married.", "f036")],
        "017": [("marital status", "I'm married.", "f039")], "021": [("marital status", "I'm married.", "f058")],
        "022": [("marital status", "I'm married.", "f040")],
        "024": [("marital status", "I've been married for 10 years.", "f043")],
        "026": [("marital status", "I'm married.", "f047")], "037": [("marital status", "I'm married.", "f044")],
        "044": [("marital status", "I'm married.", "f048")],
        "009": [("relationship status", "I have a girlfriend; we've been together for 6 months.", "f047")],
        "035": [("relationship status", "I have a girlfriend.", "f045")],
        "039": [("relationship status", "I have a boyfriend.", "f051")],
        "043": [("relationship status", "I have a new girlfriend.", "f046")],
    },
    "agentclinic": {
        "059": [("living situation", "I live with roommates.", "f001")],
        "144": [("marital status", "I'm married.", "f012"),
                ("caffeine use", "I've tried using caffeine to fix my sleep pattern.", "f002")],
        "185": [("marital status", "I'm married.", "f006")],
        "080": [("last menstrual period", "I haven't had a period since I became pregnant; I'm 30 weeks pregnant now.", "f008")],
    },
}
NEW_CATEGORY = {"marital status": "social_background", "relationship status": "social_background",
                "living situation": "social_background", "caffeine use": "habit_exposure",
                "last menstrual period": "medical_history"}

# Shared question names (validator items.same_name): (case, name) -> fact that keeps it (None: removed from all).
SHARED = {
    "medqa_cs": {("021", "past surgery"): None, ("039", "obesity in the family"): None},
    "agentclinic": {("005", "antibiotics"): None, ("021", "hiv medicines"): None, ("021", "antiretrovirals"): None,
                    ("021", "antibiotics"): None, ("043", "diabetes medicine"): None, ("045", "recent cold"): "f011",
                    ("045", "upper respiratory infection"): "f011", ("077", "diabetes medicine"): None,
                    ("165", "blood pressure medication"): None, ("166", "medications"): None,
                    ("179", "diabetes medication"): None},
    "medcasereasoning": {("00215", "hiv medicines"): None, ("00215", "antiretrovirals"): None,
                         ("00403", "previous surgery"): None, ("00403", "operations"): None,
                         ("00426", "antibiotics"): None, ("00480", "earlier tests"): None, ("01556", "painkillers"): None,
                         ("01598", "surgery"): None, ("01598", "operations"): None, ("01872", "work"): "f014",
                         ("01919", "family history"): None, ("02593", "eye drops"): None, ("03594", "supplements"): None,
                         ("06156", "skin changes"): "f013", ("06180", "immunosuppression"): None,
                         ("06180", "anti-rejection medicines"): None, ("06180", "immunotherapy"): None,
                         ("06180", "checkpoint inhibitor"): None, ("06180", "cancer treatment"): None,
                         ("07087", "warning signs"): None, ("07631", "antibiotics"): None,
                         ("08927", "immunosuppressants"): None, ("08927", "anti-rejection medicine"): None,
                         ("10584", "diabetes medicine"): None, ("10584", "anemia in the family"): None,
                         ("10717", "supplements"): None, ("12090", "benzodiazepine"): None, ("12365", "eye drops"): None,
                         ("13161", "antibiotics"): None},
}

DATASETS = {"medqa_cs": (HERE / "medqa_cs" / "bundles", "medqa-cs-", "indent"),
            "agentclinic": (HERE / "agentclinic" / "bundles", "agentclinic-medqa-ext-", "compact"),
            "medcasereasoning": (HERE / "medcasereasoning" / "bundles", "mcr-test-", "compact")}


def dump(b, style):
    if style == "indent":
        return json.dumps(b, ensure_ascii=False, indent=2)
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


def fix_case(ds, num, b, counts):
    log = []
    facts = b["patient"]["facts"]
    by = {f["id"]: f for f in facts}
    q = b["qc"]
    rewrites = REWRITE.get(ds, {}).get(num, {})
    for fid, text in rewrites.items():
        if by[fid]["text"] != text:
            by[fid]["text"] = text
            log.append(f"{fid} text rewritten")
            counts["rewritten"] += 1
            if (ds, num, fid) in INFERRED_PURPOSE:
                q.setdefault("flags", {}).setdefault(fid, []).append(
                    "Purpose added from the case (the only matching diagnosis); the source answer lists the medicine only.")
    if ds == "medqa_cs":
        for f in facts:
            if f["id"] in rewrites:
                continue
            m = ANSWER_WORD.match(f["text"])
            if m:
                rest = f["text"][m.end():]
                f["text"] = rest[0].upper() + rest[1:]
                log.append(f"{f['id']} answer word removed")
                counts["answer_word"] += 1
    for fid, fields in FIELDS.get((ds, num), {}).items():
        for k, v in fields.items():
            if by[fid].get(k) != v:
                by[fid][k] = v
                log.append(f"{fid} {k} -> {v}")
                counts["fields"] += 1
    for item, text, src in NEW_FACTS.get(ds, {}).get(num, []):
        if any(f["item"] == item and f["text"] == text for f in facts):
            continue
        fid = f"f{max(int(f['id'][1:]) for f in facts) + 1:03d}"
        facts.append({"id": fid, "item": item, "text": text, "polarity": "present", "category": NEW_CATEGORY[item]})
        q["fact_sources"][fid] = list(q["fact_sources"][src])
        q.setdefault("flags", {})[fid] = [f"Split off from {src}, whose text was the only record of it (fix)."]
        log.append(f"{fid} new fact '{item}' from {src}")
        counts["new_facts"] += 1
    for (case, name), owner in SHARED.get(ds, {}).items():
        if case != num:
            continue
        for f in facts:
            if f["id"] == owner:
                continue
            al = f.get("aliases", [])
            keep = [a for a in al if " ".join(a.lower().split()) != name]
            if len(keep) != len(al):
                if keep:
                    f["aliases"] = keep
                else:
                    f.pop("aliases")
                log.append(f"{f['id']} alias '{name}' removed")
                counts["aliases_removed"] += 1
    if log:
        q["notes"] = [n for n in q.get("notes", []) if not n.startswith(NOTE)] + [NOTE + "; ".join(log) + "."]
        counts["cases"] += 1
    return bool(log)


def main():
    for ds, (folder, prefix, style) in DATASETS.items():
        counts = {k: 0 for k in ("cases", "answer_word", "rewritten", "fields", "new_facts", "aliases_removed")}
        for p in sorted(folder.glob(prefix + "*.json")):
            num = p.stem[len(prefix):]
            b = json.loads(p.read_text(encoding="utf-8"))
            if fix_case(ds, num, b, counts):
                text = dump(b, style)
                assert json.loads(text) == b
                p.write_text(text, encoding="utf-8")
        print(ds, counts)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
