"""Aggregate the screening batches and pick a specialty-balanced set of convenient cases.

Usage: python select.py [target_size]     (default 100)
Writes screen_all.jsonl (every screened case with its rule verdict) and selected.json.
"""
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from check_screen import rule_verdict  # noqa: E402

# Reviewer drops after reading the selected medium-inferability cases.
MANUAL_DROP = {
    175: "benign metastasizing leiomyoma: no pathology in the prompt, so nothing separates it from metastatic leiomyosarcoma",
    234: "intussusception: CT shows no obstruction and the intussusception itself is never imaged; the gold rests on later findings",
}
TIME = {"single_episode": 2, "staged_workup": 1}
INFER = {"high": 2, "medium": 1}
LEAK = {"none": 1, "test_result": 0}


def why_excluded(r):
    out = []
    if not r["can_converse"]:
        out.append("patient cannot give the history")
    if r["time_structure"] == "course_dependent":
        out.append("depends on the hospital course")
    if r["leakage"] == "history":
        out.append("diagnosis known from history")
    if r["inferable"] == "low":
        out.append("not inferable")
    if r["patient_facts"] < 5:
        out.append("fewer than 5 patient facts")
    if r["objective_findings"] == 0:
        out.append("no objective data")
    if r["image_dependence"]:
        out.append("decisive finding only in an image")
    return out


def score(r):
    """Higher is more convenient: a rich interview, a single presentation, a clearly inferable diagnosis."""
    return (TIME[r["time_structure"]] + INFER[r["inferable"]] + LEAK[r["leakage"]]
            + min(r["patient_facts"], 20) / 5 + min(r["objective_findings"], 12) / 6
            + {"high": 2, "medium": 0}.get(r.get("interview_value"), 0))


def norm_dx(s):
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def main():
    target = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    cand = {json.loads(l)["idx"]: json.loads(l) for l in (HERE / "candidates.jsonl").open(encoding="utf-8")}
    rows = []
    for p in sorted((HERE / "screen").glob("batch_*.jsonl")):
        rows += [json.loads(l) for l in p.open(encoding="utf-8") if l.strip()]
    assert sorted(r["idx"] for r in rows) == sorted(cand), "screen files do not cover every candidate exactly once"
    for r in rows:
        c = cand[r["idx"]]
        r["rule_verdict"] = rule_verdict(r)
        r["test_index"], r["final_diagnosis"] = c["test_index"], c["final_diagnosis"]
    with (HERE / "screen_all.jsonl").open("w", encoding="utf-8") as f:
        for r in sorted(rows, key=lambda r: r["idx"]):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    verdicts = Counter(r["rule_verdict"] for r in rows)
    disagree = sum(r["verdict"] != r["rule_verdict"] for r in rows)
    reasons = Counter(x for r in rows if r["rule_verdict"] == "exclude" for x in why_excluded(r))
    maybe_why = Counter(("5-7 patient facts" if r["patient_facts"] < 8 else
                         "fewer than 3 objective findings" if r["objective_findings"] < 3 else "label issue")
                        for r in rows if r["rule_verdict"] == "maybe")
    inc = [r for r in rows if r["rule_verdict"] == "include"]
    print(f"screened {len(rows)}: {dict(verdicts)} (agent verdict differs from the rules in {disagree})")
    second = {}
    for p in sorted((HERE / "second_look").glob("part_*.jsonl")):
        second.update({json.loads(l)["idx"]: json.loads(l) for l in p.open(encoding="utf-8") if l.strip()})
    if second:
        assert set(second) == {r["idx"] for r in inc}, "second look does not cover every included case"
        why = Counter()
        for r in inc:
            s = second[r["idx"]]
            why.update(k for k, bad in (("unreliable historian", not s["reliable_historian"]),
                                        ("low interview value", s["interview_value"] == "low"),
                                        ("weak gold label", s["gold_fit"] == "weak"),
                                        ("course problem", s["course_problem"])) if bad)
            r.update({k: s[k] for k in ("interview_value", "dx_key", "specialty", "keep", "narrative_conclusion", "note")})
        print(f"second look keeps {sum(r['keep'] for r in inc)} of {len(inc)}; not kept because:", dict(why.most_common()))
        print("inpatient onset dropped:", [r["idx"] for r in inc if r["keep"] and r["setting"] == "inpatient_onset"])
        inc = [r for r in inc if r["keep"] and r["setting"] != "inpatient_onset" and r["idx"] not in MANUAL_DROP]
        print("reviewer drops:", sorted(MANUAL_DROP))
    print("exclusion reasons:", dict(reasons.most_common()))
    print("maybe reasons:", dict(maybe_why.most_common()))
    print("include by specialty:", dict(Counter(r["specialty"] for r in inc).most_common()))
    print("include by setting:", dict(Counter(r["setting"] for r in inc).most_common()))
    print("include by decisive evidence:", dict(Counter(r["decisive_evidence"] for r in inc).most_common()))

    # Round-robin over specialties, best score first; one case per diagnosis.
    pools = defaultdict(list)
    for r in sorted(inc, key=lambda r: (-score(r), r["idx"])):
        pools[r["specialty"]].append(r)
    chosen, seen_dx = [], set()
    while len(chosen) < target and any(pools.values()):
        for sp in sorted(pools, key=lambda s: -len(pools[s])):
            while pools[sp]:
                r = pools[sp].pop(0)
                key = norm_dx(r.get("dx_key") or r["final_diagnosis"])
                if key not in seen_dx:
                    seen_dx.add(key)
                    chosen.append(r)
                    break
            if len(chosen) >= target:
                break
    chosen.sort(key=lambda r: r["idx"])
    out = [{k: r[k] for k in ("idx", "test_index", "pmcid", "final_diagnosis", "specialty", "setting", "age", "sex",
                              "patient_facts", "objective_findings", "time_structure", "leakage", "inferable",
                              "decisive_evidence")}
           | {k: r[k] for k in ("interview_value", "dx_key", "narrative_conclusion", "note") if k in r}
           | {"score": round(score(r), 2)} for r in chosen]
    (HERE / "selected.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"selected {len(out)} of {len(inc)} includes:", dict(Counter(r["specialty"] for r in out).most_common()))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
