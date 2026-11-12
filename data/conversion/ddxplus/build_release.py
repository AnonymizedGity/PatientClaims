"""Build the DDXPlus release in the common case schema (closed world).

Input: the frozen adult test pool (data/conversion/pools/ddxplus, 3,875 rows), the question catalogue
(catalogue.json: questions, groups, value glosses) and texts.py (labels, aliases, first-person texts).
Output: release/ddxplus_{patient,environment,gold,qc}.jsonl, ddxplus_catalogue.json, manifest.json.
Deterministic, no model calls.

Usage: python -I build_release.py
"""
import ast
import csv
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
from texts import (APPLIES_TO, ATTRIBUTE, BANDS, CATEGORY, EYE, GROUP_CATEGORY, GROUP_SYSTEM, INTENSITY, INVERTED,  # noqa: E402
                   LOCATION, PATHOLOGY_ALIASES, PATTERN, SYSTEM, TEXTS)

POOL = HERE.parent / "pools" / "ddxplus"
CATALOGUE = HERE / "catalogue.json"
OUT = HERE / (sys.argv[1] if len(sys.argv) > 1 else "release")   # output folder

OPEN_WORLD = ["E_209", "E_150"]          # defaults that are not a usable "No"
LOCATION_ITEMS = {"E_55", "E_57", "E_133", "E_152"}
CHARACTER = {"stabbing, like a knife": "stabbing (like a knife)"}
# answered_by: target item <- recorded positives that make its default "No" false. Every present source answers,
# in fact order. Each implication was reviewed by hand.
IMPLIES = {
    "E_104": ("E_102",), "E_175": ("E_144",), "E_76": ("E_82",), "E_83": ("E_172", "E_38"), "E_0": ("E_116",),
    "E_41": ("E_40", "E_73"),
    "E_201": ("E_45", "E_203", "E_202", "E_77", "E_166"),      # cough: blood, fits, whoop, sputum, vomiting after coughing
    "E_177": ("E_157", "E_93"),                                # numbness anywhere: limbs and mouth, feet
    "E_174": ("E_162", "E_32"),                                # weight loss or lost appetite: weight loss, decreased appetite
    "E_161": ("E_32",),                                        # lost appetite or full quickly: decreased appetite
    "E_159": ("E_43",),                                        # lost consciousness: seizure with loss of consciousness or absence
    "E_176": ("E_156", "E_84", "E_83"),                        # limb or face weakness: one-sided face, both limbs, face or eyes
    "E_124": ("E_101", "E_46"),                                # asthma: hospital stay or attacks for asthma
    "E_123": ("E_72", "E_31"),                                 # COPD: flare-ups, severe COPD
    "E_34": ("E_37",),                                         # active cancer: metastatic cancer
    "E_87": ("E_142",),                                        # asthma in the family: mother with asthma
    "E_53": ("E_33", "E_216", "E_220", "E_14"),                # pain: pain modifiers, chest pain at rest
    "E_151": ("E_9", "E_30"),                                  # swelling anywhere: swollen or painful nodes, swollen belly
    "E_178": ("E_45", "E_210", "E_179"),                       # unusual bleeding: coughing up, vomiting, passing blood
    "E_89": ("E_88",),                                         # constant tiredness: too tired for usual activities
    "E_148": ("E_211",),                                       # nausea: repeated vomiting or retching
    "E_155": ("E_164",),                                       # palpitations: very irregular heartbeat
    "E_129": ("E_92",),                                        # skin problem: cheeks suddenly red
}
IMPLIES["E_176"] += ("E_90",)                                  # limb or face weakness: weakness worse with fatigue
IMPLIES["E_83"] += ("E_156",)                                  # face or eye weakness: one-sided face weakness
IMPLIES["E_53"] += ("E_97", "E_144")                           # pain: sore throat, widespread muscle pain
# When E_53 is answered by such facts, they also give the pain's place; its other details are unknown (an empty list),
# never the defaults ("I'd rate it 0 out of 10").
PAIN_PLACE = {"E_97", "E_144", "E_14"}
PAIN_DETAILS = ("E_54", "E_56", "E_57", "E_58", "E_59")
THROAT = re.compile(r"\b(tonsils?|pharynx|throat|palate|larynx)\b", re.I)
PAIN_PLACES = {i["id"]: i for i in json.loads(CATALOGUE.read_text(encoding="utf-8"))["items"]}["E_55"]["values"]


def place(gloss):
    if gloss in LOCATION:
        return LOCATION[gloss]
    m = re.match(r"^(right|left) (.+)$", gloss)
    side, rest = (m.group(1) + " ", m.group(2)) if m else ("", gloss)
    rest = re.sub(r"\s*\(.*\)$", "", rest)
    if rest.startswith(("back of the ", "side of the ", "top of the ", "palm side of the ")):
        head, tail = rest.split(" the ", 1)
        return f"the {head} of my {side}{tail}".replace(" of of", " of")
    return f"my {side}{rest}"


def join(parts):
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def build_catalogue(src):
    items, by_key = [], {}
    for it in src["items"]:
        k = it["id"]
        label, aliases, yes, no = TEXTS[k]
        parent = it["parent"]
        if parent:
            cat, system = by_key[parent]["category"], by_key[parent].get("system")
        else:
            cat = CATEGORY.get(k) or GROUP_CATEGORY.get(it["group"], "symptom")
            system = None
            if cat == "symptom":
                system = SYSTEM.get(k) or ("eye" if k in EYE else GROUP_SYSTEM[it["group"]])
        if it["data_type"] == "B":
            vtype, options, scale = "binary", None, None
        elif it["data_type"] == "M":
            vtype, scale = "list", None
            options = {c: (place(g) if k in LOCATION_ITEMS else CHARACTER.get(g, g)) for c, g in it["values"].items() if c != it["default"]}
        elif not it["values"]:
            vtype, options, scale = "scale", None, [0, 10]
        else:
            vtype, scale = "categorical", None
            options = {c: g for c, g in it["values"].items() if c != it["default"]}
        entry = {"key": k, "question": it["question"], "item": label, "aliases": aliases, "category": cat}
        if system:
            entry["system"] = system
        if parent:
            entry.update(parent=parent, attribute=ATTRIBUTE[k])
        if k in PATTERN:
            entry["pattern"] = True
        entry["value_type"] = vtype
        if scale:
            entry["scale"] = scale
        if options:
            entry["options"] = options
        entry["default"] = it["default"]
        entry["present_text"] = yes
        if k in BANDS:
            entry["bands"] = [{"min": lo, "max": hi, "text": t} for lo, hi, t in BANDS[k]]
        if k in APPLIES_TO:
            entry["applies_to"] = APPLIES_TO[k]
        entry["absent_text"] = no
        items.append(entry)
        by_key[k] = entry
    return {"dataset": "ddxplus", "source": src["source"],
            "note": "Questions, groups and value glosses from catalogue.json; item labels, aliases, "
                    "first-person present_text (a template for list, scale and categorical items) and absent_text "
                    "written for the common schema. Resolution order: case_schema.md, Catalogue.",
            "items": items}, by_key


def parse(tokens, cat):
    record = {}
    for t in tokens:
        if "_@_" in t:
            k, v = t.split("_@_")
            if cat[k]["value_type"] == "list":
                record.setdefault(k, []).append(v)
            else:
                record[k] = v
        else:
            record[t] = True
    return record


def fact_for(k, value, cat):
    """(polarity, text, typed value, value phrases or None) for one recorded item, or None if it says nothing."""
    e = cat[k]
    vt = e["value_type"]
    if vt == "binary":
        if k in INVERTED:
            return "absent", e["absent_text"], None
        return "present", e["present_text"], None
    if vt == "list":
        codes = [c for c in value if c != e["default"]]
        if not codes:
            if k == "E_57":
                return "absent", e["absent_text"], None
            return None
        names = [e["options"][c] for c in codes]
        if k in LOCATION_ITEMS:
            body = join(names) + (", and nowhere else" if len(names) > 1 else "")
            text = e["present_text"].replace("{values}", body)
            if len(names) == 1:
                text = text.replace("It's in ", "It's only in ").replace("It's on ", "It's only on ").replace(
                    "It spreads to ", "It only spreads to ")
        else:
            text = e["present_text"].replace("{values}", join(names))
        return "present", text, names
    if vt == "scale":
        n = int(value)
        if n == 0 and k in INTENSITY:
            return "absent", e["absent_text"], 0
        if k in BANDS:
            return "present", next(t for lo, hi, t in BANDS[k] if lo <= n <= hi), n
        return "present", e["present_text"].replace("{n}", str(n)), n
    # categorical
    if value == e["default"]:
        if k in ("E_131", "E_135"):
            return "absent", e["absent_text"], None
        return None
    meaning = e["options"][value]
    if meaning == "Y":
        return "present", e["present_text"], None
    return "present", e["present_text"].replace("{value}", meaning), meaning


def build_case(meta, row, cat, order):
    cid = meta["case_id"]
    tokens = ast.literal_eval(row["EVIDENCES"])
    record = parse(tokens, cat)
    positive = {}
    for k, v in record.items():
        e = cat[k]
        if e.get("parent"):
            continue
        f = fact_for(k, v, cat)
        if f and (f[0] == "present" or k in INVERTED):
            positive[k] = f
    initial = row["INITIAL_EVIDENCE"]
    assert initial in positive, (cid, initial)
    keys = [initial] + [k for k in order if k in positive and k != initial]
    facts, fid_of, sources = [], {}, {}

    def add(k, f, parent_fid=None):
        e = cat[k]
        pol, text, value = f
        fid = f"f{len(facts) + 1:03d}"
        fact = {"id": fid, "key": k, "item": e["item"]}
        if e["aliases"]:
            fact["aliases"] = e["aliases"]
        fact["text"] = text
        fact["polarity"] = pol
        fact["category"] = e["category"]
        if e.get("system"):
            fact["system"] = e["system"]
        if parent_fid:
            fact.update(parent=parent_fid, attribute=e["attribute"])
        if value is not None:
            fact["value"] = value
        if e["value_type"] == "scale":
            fact["scale"] = e["scale"]
        if e["value_type"] == "list" and isinstance(value, list):
            fact["complete"] = True
        if e.get("pattern"):
            fact["pattern"] = True
        facts.append(fact)
        fid_of[k] = fid
        sources[fid] = [t for t in tokens if t == k or t.startswith(k + "_@_")]

    for k in keys:
        add(k, positive[k])
        if positive[k][0] != "present":
            continue
        for child in order:
            if cat[child].get("parent") == k and child in record:
                f = fact_for(child, record[child], cat)
                if f:
                    add(child, f, fid_of[k])

    opening = fid_of[initial]
    notes = []
    if positive[initial][0] != "present":
        # The recorded initial evidence is a reassurance (E_150 "able to pass stools or gas", 11 inguinal-hernia rows):
        # the patient opens with the first present symptom instead.
        opening = next(f["id"] for f in facts if f["polarity"] == "present" and "parent" not in f and f["category"] == "symptom")
        notes.append(f"The recorded initial evidence {initial} is not a complaint; the opening is the first present symptom ({opening}).")
    answered_by, reasons = {}, {}
    present = {k for k in fid_of if facts[int(fid_of[k][1:]) - 1]["polarity"] == "present"}
    for k, partners in IMPLIES.items():
        hits = sorted((p for p in partners if p in present), key=lambda p: fid_of[p])
        if k not in record and hits:
            answered_by[k] = [fid_of[p] for p in hits]
            reasons[k] = (f"Default 'No' to {k} ({cat[k]['item']}) would contradict the recorded "
                          + ", ".join(f"{p} ({cat[p]['item']})" for p in hits) + "; those facts answer it.")
    if "E_53" in answered_by:
        places = [fid_of[k] for k in sorted(PAIN_PLACE & present, key=lambda k: fid_of[k])]
        answered_by["E_55"] = places
        reasons["E_55"] = ("The pain is recorded only through " + ", ".join(places or ["a modifier"]) + "; that fact gives its place."
                           if places else "The pain is recorded only through a modifier; its place is not recorded (unknown).")
        for child in PAIN_DETAILS:
            answered_by[child] = []
            reasons[child] = "The pain is recorded only through other items; this detail of it is not recorded (unknown, not the default)."
    if "E_97" not in record and "E_53" in present and "E_55" in present:
        if any(THROAT.search(PAIN_PLACES[c]) for c in record["E_55"] if c in PAIN_PLACES):
            answered_by["E_97"] = [fid_of["E_53"], fid_of["E_55"]]
            reasons["E_97"] = "Default 'No' to a sore throat would contradict the recorded pain in the throat; the pain and its places answer it."
    if "E_151" not in record and "E_132" in fid_of and facts[int(fid_of["E_132"][1:]) - 1]["polarity"] == "present":
        answered_by["E_151"] = sorted(set(answered_by.get("E_151", [])) | {fid_of["E_132"]})
        reasons["E_151"] = ("Default 'No' to swelling would contradict the skin lesion recorded as swollen; the lesion's swelling answers it"
                            + (" (with the other swelling facts)." if len(answered_by["E_151"]) > 1 else "."))
        if "E_133" in fid_of and facts[int(fid_of["E_133"][1:]) - 1]["polarity"] == "present":
            answered_by["E_152"] = [fid_of["E_133"]]
            reasons["E_152"] = ("Swelling location: the swelling is the skin lesion's, so the lesion's location answers it "
                                "(not the default 'can't say').")

    sex = {"M": "male", "F": "female"}[row["SEX"]]
    assert not any(APPLIES_TO.get(f["key"], sex) != sex for f in facts), (cid, "item of the other sex recorded")
    patient = {"case_id": cid, "dataset": "ddxplus",
               "demographics": {"age": int(row["AGE"]), "sex": {"M": "male", "F": "female"}[row["SEX"]]},
               "opening": [opening], "facts": facts}
    if answered_by:
        patient["answered_by"] = answered_by
    differential = ast.literal_eval(row["DIFFERENTIAL_DIAGNOSIS"])
    gold = {"case_id": cid, "diagnosis": row["PATHOLOGY"], "aliases": PATHOLOGY_ALIASES[row["PATHOLOGY"]],
            "differential": [{"rank": i, "diagnosis": name, **({"aliases": PATHOLOGY_ALIASES[name]} if PATHOLOGY_ALIASES.get(name) else {}),
                              "probability": round(p, 4)} for i, (name, p) in enumerate(differential, 1)]}
    qc = {"case_id": cid, "fact_sources": sources, "flags": reasons,
          "source": {"pool_row_zero_based": meta["source_row_index_zero_based"], "source_values_sha256": meta["source_values_sha256"],
                     "initial_evidence": initial, "evidence_tokens": tokens},
          "notes": notes, "extras": {}}
    dropped = sorted({t.split("_@_")[0] for t in tokens} - set(fid_of))
    if dropped:
        qc["notes"].append("Recorded tokens with no fact: " + ", ".join(dropped)
                           + " (defaults, or attributes of an item that is not present).")
    return patient, {"case_id": cid, "findings": []}, gold, qc


def main():
    src = json.loads(CATALOGUE.read_text(encoding="utf-8"))
    catalogue, cat = build_catalogue(src)
    order = [i["key"] for i in catalogue["items"]]
    manifest_rows = json.loads((POOL / "manifest.json").read_text(encoding="utf-8"))["records"]
    csv.field_size_limit(10 ** 8)
    rows = list(csv.DictReader((POOL / "source_records" / "ddxplus_test_adult_deduplicated_capped_3875.csv").open(encoding="utf-8")))
    assert len(rows) == len(manifest_rows)
    OUT.mkdir(exist_ok=True)
    parts = ("patient", "environment", "gold", "qc")
    handles = {p: (OUT / f"ddxplus_{p}.jsonl").open("w", encoding="utf-8") for p in parts}
    stats = {"cases": 0, "facts": 0, "child_facts": 0, "absent_facts": 0, "cases_with_answered_by": 0, "answered_by_entries": 0}
    seen = set()
    for meta, row in zip(manifest_rows, rows):
        assert meta["pathology"] == row["PATHOLOGY"] and meta["case_id"] not in seen
        seen.add(meta["case_id"])
        out = build_case(meta, row, cat, order)
        for p, obj in zip(parts, out):
            handles[p].write(json.dumps(obj, ensure_ascii=False) + "\n")
        facts = out[0]["facts"]
        stats["cases"] += 1
        stats["facts"] += len(facts)
        stats["child_facts"] += sum("parent" in f for f in facts)
        stats["absent_facts"] += sum(f["polarity"] == "absent" for f in facts)
        stats["cases_with_answered_by"] += bool(out[0].get("answered_by"))
        stats["answered_by_entries"] += len(out[0].get("answered_by", {}))
    for h in handles.values():
        h.close()
    (OUT / "ddxplus_catalogue.json").write_text(json.dumps(catalogue, ensure_ascii=False, indent=1), encoding="utf-8")
    manifest = {"dataset": "ddxplus", "schema": "case_schema v1 (data/conversion/case_schema.md)", "world": "closed",
                "catalogue": "ddxplus_catalogue.json", "open_world_items": OPEN_WORLD, "cases": stats["cases"],
                "source": "DDXPlus v2 English test split (CC-BY 4.0): the frozen pool of 3,875 adult, deduplicated rows "
                          "(data/conversion/pools/ddxplus/manifest.json). case_id = the pool's id.",
                "notes": "Patient facts are the recorded positives (and explicit negatives of a present symptom's attributes); every "
                         "other catalogue item resolves through the catalogue (default 'No' with absent_text, answered_by, open-world "
                         "items, or not applicable when its parent is absent or, for items with `applies_to`, for the other sex). No objective findings: environment findings are empty.",
                "stats": stats}
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(stats, indent=1))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
