"""Loading the per-dialogue scores (results/scores/<set>.jsonl.gz) into the structure the analysis uses.

Each score row is one dialogue: run folder, arm, case, seed, whether it finished, the gold's and X's rank in the
final differential (1-5, null = not listed), the other entries in order, and the dispute marks.
"""
import gzip
import json
import os
import re
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCORES = os.path.join(ROOT, "results", "scores")

# Setting x doctor. "hist": history only; "tests": test results available (+T); "tests_exam": vital signs,
# examination and test results available (+T+E).
SETS = {
    "hist_qwen": ("Hist.", "Qwen3.8-27B"),
    "hist_medgemma27b": ("Hist.", "MedGemma 27B"),
    "hist_medgemma4b": ("Hist.", "MedGemma 1.5 4B"),
    "tests_qwen": ("+T", "Qwen3.8-27B"),
    "tests_exam_qwen": ("+T+E", "Qwen3.8-27B"),
    "tests_medgemma27b": ("+T", "MedGemma 27B"),
    "tests_exam_medgemma27b": ("+T+E", "MedGemma 27B"),
}
HIST = ["hist_qwen", "hist_medgemma27b", "hist_medgemma4b"]

# Arm (run-folder suffix) -> (intervention family, level). The family is the multiple-comparison family:
# Holm (top-1, mixed model) and BH (other outcomes) are applied across the levels of one family.
SOURCES = {"AI": "AI chatbot", "WEB": "Web", "DOCTOR": "Another doctor"}
DOSES = [("single", "one mention"), ("sched2", "two mentions"), ("sched3", "three mentions"), ("", "reactive")]
LEVELS = {
    "A1_single": ("own", "one mention"),
    "A1_sched2": ("own", "two mentions"),
    "A1_sched3": ("own", "three mentions"),
    "A1_persistence": ("own", "reactive"),
    **{f"A15_{s}{'_' + d if d else ''}": ("source", f"{lab}, {dl}") for s, lab in SOURCES.items() for d, dl in DOSES},
    "A12a_anchor_R1": ("fact_x", "reply 1"),
    "A12a_anchor_R3": ("fact_x", "reply 3"),
    "A12a_anchor_R5": ("fact_x", "reply 5"),
    "A12a_EARLY": ("fact_gold", "reply 1"),
    "A12a_LATE": ("fact_gold", "reply 3"),
    "A12a_R5": ("fact_gold", "reply 5"),
    "A13_5": ("opening", "full opening (5 blocks)"),
    "A13_3": ("opening", "3 blocks"),
}
# The arms the paper reports. The other levels (fact at reply 3 or 5, 3-block opening) belong to the same
# correction families and are kept only for that.
PAPER_ARMS = ["control", "A1_single", "A1_sched2", "A1_sched3", "A1_persistence",
              *[f"A15_{s}{'_' + d if d else ''}" for s in SOURCES for d, _ in DOSES],
              "A12a_anchor_R1", "A12a_EARLY", "A13_5"]
# Families whose comparisons leave out the cases where X already leads in the control arm.
ANCHORED = {"own", "source", "fact_x"}


def source_arms(source):
    """The four dose levels of one source: 'own' (the patient's own worry) or AI / WEB / DOCTOR."""
    if source == "own":
        return ["A1_single", "A1_sched2", "A1_sched3", "A1_persistence"]
    return [f"A15_{source}{'_' + d if d else ''}" for d, _ in DOSES]


def norm(s):
    """Normalised diagnosis string, for comparing top diagnoses across dialogues."""
    return " ".join(re.sub(r"[^\w\s/'-]", " ", s.lower()).replace("_", " ").split())


def record(r):
    done = bool(r["complete"])
    g = r.get("gold_rank")
    x = r.get("anchor_rank")
    g = int(g) if g not in (None, "", "None") else None
    x = int(x) if x not in (None, "", "None") else None
    un = r.get("unmatched") or []
    if done and g == 1:
        key = "GOLD"
    elif done and x == 1:
        key = "X"
    elif done and un:
        key = norm(un[0])
    else:
        key = None
    gr = g if done else None
    rec = {"done": done, "g": g, "x": x, "key": key, "seed": r["seed"],
           "top1": int(done and g == 1), "top5": int(done and g is not None and g <= 5),
           "anchor_in": int(done and x is not None), "anchor_first": int(done and x == 1),
           # X ranked first while the gold is not (an entry can match both): Table 1's "First"
           "x_top": int(done and x == 1 and g != 1),
           "top1_wo_x": int(bool(done and (g == 1 or (g == 2 and x == 1)))),
           "off": int(gr is None)}
    if r.get("disputed_turns") is not None:
        rec["disputed"] = int(r["disputed_turns"] > 0)
    if r.get("tests_requested") is not None:
        rec["requested"] = r["tests_requested"]
    return rec


def load(name):
    """arm -> (case, seed) -> record."""
    data = {}
    with gzip.open(os.path.join(SCORES, name + ".jsonl.gz"), "rt", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            data.setdefault(r["arm"], {})[(r["case_id"], r["seed"])] = record(r)
    return data


def x_first_cases(control):
    """Cases where X is ranked first in at least two of the three control seeds."""
    n = Counter(k[0] for k, v in control.items() if v["anchor_first"])
    return {c for c, k in n.items() if k >= 2}


def dataset_of(case):
    for prefix, name in (("agentclinic", "agentclinic"), ("mcr", "medcasereasoning"), ("medqa-cs", "medqa_cs"),
                         ("ddxplus", "ddxplus")):
        if case.startswith(prefix):
            return name
    return "other"
