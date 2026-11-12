"""Cross-case consistency scan of the AgentClinic bundles (read-only report for the harmonisation pass).

Usage: python scan.py [section ...]   sections: catchall meta gold signs normal contra scale exam_dx opening systems
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC, BUNDLES = HERE / "source", HERE / "bundles"

META = re.compile(r"not (mentioned|provided|reported|specified|documented|noted|described|available)|did not (report|mention)"
                  r"|no mention|unknown|non-?contributory|none (reported|mentioned|noted)|no (notable|significant|pertinent|relevant|other|additional|further)",
                  re.I)
CATCH = re.compile(r"\b(other|additional|further|any|anything|else)\b", re.I)
NORMAL = re.compile(r"\b(normal|fine|good|healthy|regular|well|okay|ok|stable|unchanged|balanced|usual)\b", re.I)
CONTRA = re.compile(r"contracept|condom|\bpills?\b|\biud\b|vasectomy|withdrawal|birth control|\bocp|implant|depo|\bpatch\b|\bring\b", re.I)
SIGN = re.compile(r"pallor|icterus|petechia|hepatomegaly|splenomegaly|murmur|tachycardi|bradycardi|hypotensi|hypertensi"
                  r"|lymphadenopathy|tender|nystagmus|reflex|ataxi|rigidity|clubbing|cyanosis|edema|effusion|crackles|wheez|bruit"
                  r"|appears|disorganized|agitation|flat affect|posture|position|sounds", re.I)


def load():
    for p in sorted(BUNDLES.glob("agentclinic-medqa-ext-*.json")):
        b = json.loads(p.read_text(encoding="utf-8"))
        s = json.loads((SRC / p.name).read_text(encoding="utf-8"))
        s["text"] = {f["fact_id"]: f["text"] for f in s["fragments"]}
        s["text"]["cc"] = s["chief_complaint"] or ""
        yield p.stem[-3:], b, s


def src_text(b, s, fid):
    return " | ".join(s["text"].get(x, x) for x in b["qc"]["fact_sources"].get(fid, []))


def fmt(f):
    return f"{f['id']} [{f['polarity']}/{f['category']}/{f.get('system', '-')}] item={f['item']!r} text={f['text']!r}"


def main():
    want = set(sys.argv[1:])
    on = lambda name: not want or name in want
    cases = list(load())
    systems = Counter()
    for cid, b, s in cases:
        facts, findings, qc = b["patient"]["facts"], b["environment"]["findings"], b["qc"]
        for f in facts:
            st = src_text(b, s, f["id"])
            if on("catchall") and f["polarity"] == "absent" and not f.get("parent") and CATCH.search(f["item"]):
                print(f"catchall {cid} {fmt(f)}")
            if on("meta") and META.search(st) and f["polarity"] == "absent":
                hits = [s["text"][x] for x in qc["fact_sources"][f["id"]] if x in s["text"] and META.search(s["text"][x])]
                print(f"meta     {cid} {fmt(f)}\n           src: {' | '.join(h[:200] for h in hits)}")
            if on("normal") and f["polarity"] == "present" and NORMAL.search(f["text"]) and not f.get("parent"):
                print(f"normal   {cid} {fmt(f)}")
            if on("contra") and CONTRA.search(f["item"] + " " + f["text"]):
                print(f"contra   {cid} {fmt(f)}")
            if on("scale") and (re.search(r"\d+\s*(/|out of)\s*10\b", f["text"]) or "value" in f and isinstance(f["value"], (int, float))):
                print(f"scale    {cid} {fmt(f)} value={f.get('value')} scale={f.get('scale')}")
            if on("signs") and f["category"] == "symptom" and SIGN.search(f["item"] + " " + f["text"]):
                print(f"signs    {cid} {fmt(f)}")
            if f["category"] == "symptom" and not f.get("parent"):
                systems[(f.get("system"), f["item"].split(":")[0])] += 1
        if on("meta"):
            for x in qc.get("excluded_sources", []):
                print(f"excluded {cid} {x['id']}: {s['text'].get(x['id'], '')[:160]!r} -- {x['reason'][:120]}")
        if on("gold"):
            print(f"gold     {cid} {b['gold']['diagnosis']!r} aliases={b['gold']['aliases']}  (source {s['correct_diagnosis']!r})")
        if on("exam_dx"):
            words = {w for w in re.findall(r"[a-z]{5,}", s["correct_diagnosis"].lower())} - {"acute", "chronic", "syndrome", "disease", "disorder", "infection", "induced", "secondary", "primary"}
            for x in findings:
                if x["kind"] == "exam" and any(re.search(rf"\b{w}", x["result"].lower()) for w in words):
                    print(f"exam_dx  {cid} {x['id']} {x['name']!r}: {x['result'][:200]!r}")
        if on("opening"):
            op = [f for f in facts if f["id"] in b["patient"]["opening"]]
            kids = [f["id"] for f in op if f.get("parent")]
            print(f"opening  {cid} n={len(op)} children={kids} cc={s['chief_complaint']!r} -> {[f['text'] for f in op]}")
    if on("systems"):
        for (sysname, item), n in sorted(systems.items()):
            if re.search(r"sleep|breast|insomnia|fatigue|tired|weight|fever|mood|anx|memory|confus", item, re.I):
                print(f"systems  {sysname:16} {item} ({n})")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
