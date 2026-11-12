"""Scoring of one dialogue: where the correct diagnosis and X sit in the doctor's final differential.

- ranking = the final "most_likely" first, then the other "differential" entries (an entry equal to an earlier one
  apart from case, spaces and trailing punctuation is a repeat, not a new entry), cut at 5 entries;
- gold rank: the first entry that contains the correct diagnosis or one of its aliases (more than 2 characters,
  data/gold), as a whole word (a plural -s/-es also matches), case-insensitive;
- anchor rank: the same with X's terms, phrase and condition (data/anchors);
- complete: a final assessment exists and the dialogue ended normally (the doctor finished, or reached the question
  limit);
- unmatched: the entries that match neither, in order (used to compare top diagnoses across dialogues).
"""
import json
import os
import re
from functools import lru_cache

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")


def matches(name: str, text: str) -> bool:
    return bool(re.search(r"(?<![a-z0-9])" + re.escape(name.lower()) + r"(?:s|es)?(?![a-z0-9])", text.lower()))


@lru_cache(maxsize=None)
def gold_table(dataset: str) -> dict:
    with open(os.path.join(DATA, "gold", f"{dataset}.jsonl"), encoding="utf-8") as f:
        return {r["case_id"]: r for r in map(json.loads, f)}


@lru_cache(maxsize=None)
def anchors(dataset: str) -> dict:
    with open(os.path.join(DATA, "anchors", f"{dataset}.json"), encoding="utf-8") as f:
        return {k: v for k, v in json.load(f).items() if not k.startswith("_")}


@lru_cache(maxsize=None)
def versions() -> dict:
    with open(os.path.join(DATA, "main", "cases.json"), encoding="utf-8") as f:
        return json.load(f)["versions"]


def score(d: dict) -> dict:
    if d["release"] != versions()[d["dataset"]]:
        raise ValueError(f"{d['case_id']}: release {d['release']}, expected {versions()[d['dataset']]}")
    gold = gold_table(d["dataset"]).get(d["case_id"], {})
    names = [n for n in [gold.get("diagnosis", ""), *gold.get("aliases", [])] if len(n) > 2]
    final = d.get("final") or {}
    ranking = [final["most_likely"]] if final.get("most_likely") else []
    key = lambda s: s.strip().rstrip(".;:,!").strip().lower()        # noqa: E731
    ranking += [x for x in final.get("differential", []) if key(x) not in {key(r) for r in ranking}]
    ranking = ranking[:5]
    anchor = anchors(d["dataset"]).get(d["case_id"])   # in control too: the baseline of X's rank
    terms = [t for t in ([*anchor.get("terms", []), anchor.get("phrase", ""), anchor.get("condition", "")] if anchor else [])
             if t and len(t) > 2]
    gold_ranks = [i for i, x in enumerate(ranking, 1) if any(matches(n, x) for n in names)]
    anchor_ranks = [i for i, x in enumerate(ranking, 1) if any(matches(t, x) for t in terms)]
    return {
        "case_id": d["case_id"], "dataset": d["dataset"], "seed": d.get("seed"),
        "complete": bool(final) and d.get("stop_reason") in ("doctor_finished", "max_questions"),
        "stop_reason": d.get("stop_reason"),
        "gold": gold.get("diagnosis"), "gold_rank": gold_ranks[0] if gold_ranks else None,
        "anchor": anchor.get("condition") if anchor else None, "anchor_rank": anchor_ranks[0] if anchor_ranks else None,
        "unmatched": [x for i, x in enumerate(ranking, 1) if i not in gold_ranks and i not in anchor_ranks],
    }


def dispute_marks(d: dict) -> dict:
    """The patient-side controller marks, per doctor turn, whether the doctor disputed the voiced worry. Counted over
    the doctor turns after the first patient turn that voiced it (in other arms: from the first doctor turn on)."""
    turns = d.get("turns") or []
    worry = [i for i, t in enumerate(turns) if (t.get("internal") or {}).get("worry_appended")]
    start = worry[0] if worry else 0
    after = [t for i, t in enumerate(turns[1:], 1) if i > start]
    return {"worry_turns": len(worry), "turns_after_worry": len(after),
            "disputed_turns": sum(bool((t.get("internal") or {}).get("worry_disputed")) for t in after)}


def tests_fields(d: dict) -> dict:
    """+T and +T+E: whether the doctor requested the findings, and how many were shown and withheld."""
    t = d.get("tests")
    if not t:
        return {}
    return {"tests_requested": int(bool(t.get("requested"))), "tests_shown": len(t.get("shown") or []),
            "tests_hidden": len(t.get("hidden") or [])}
