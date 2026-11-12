"""The patient-behaviour conditions run on top of the A1 arms (simulator/README.md): A15, the source of the worry
(a medical chatbot, another doctor, the web), with reactive persistence, single exposure, or scheduled mentions (A1's own
scheduled mentions run as source SELF); A12a, one fact volunteered at a fixed reply, either the fact pointing most
clearly to the correct diagnosis (GOLD) or one that fits the wrong diagnosis X of the worry (ANCHOR); A13, an opening
that says the facts of the first 3 or 5 blocks. A dialogue's condition spec is fixed before it starts; code decides
when a behaviour fires (a reply number, the opening, the first time a fact is told), and the model decides only where
judgment is needed: A15, was the worry disputed or asked about (A1's decision). The words of a behaviour are fixed
sentences added here; the counters are kept here and committed for the reply finally given (after the check and any
redraft).

    python -B -m sim.run --condition A15:AI --arms persistence --conditions-dir conditions ...
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from .data import Case, fact_line
from .patient import STILL_WORRIED, WORRY, Directive, prompt, told_before

SOURCES = {     # A15: the opening sentence and the persistence sentence of each source of the opinion
    "SELF": (WORRY, STILL_WORRIED),
    "AI": ("A medical chatbot I used suggested it might be {phrase}.",
           "The chatbot did say it might be {phrase}, so that still worries me."),
    "DOCTOR": ("A doctor I saw before said it might be {phrase}.",
               "The other doctor did say it might be {phrase}, so that still worries me."),
    "WEB": ("I read online that it might be {phrase}.",
            "What I read did say it might be {phrase}, so that still worries me."),
}
MENTIONS = {    # A1/A15 scheduled: the later mentions of the worry
    "SELF": "I still keep thinking it could be {phrase}.",
    "AI": "I keep thinking about what the chatbot said, that it might be {phrase}.",
    "DOCTOR": "I keep thinking about what the other doctor said, that it might be {phrase}.",
    "WEB": "I keep thinking about what I read, that it might be {phrase}.",
}
SCHEDULED_AT = (2, 4)       # A1/A15 mentions 2 and 3: the replies that carry them
RELEASE_AT = {"EARLY": 1, "LATE": 3, "R1": 1, "R3": 3, "R5": 5}   # A12a: the volunteering reply
LEVELS = {"A15": ("SELF", "AI", "DOCTOR", "WEB"), "A12a": ("EARLY", "LATE", "R5", "ANCHOR:R1", "ANCHOR:R3",
                                                          "ANCHOR:R5"), "A13": (3, 5)}
COMPILED = ("A12a", "A13")                 # the conditions that need the per-case data of the compile step
LEVEL_FORMS = {             # the level forms each condition accepts
    "A15": "SOURCE or SOURCE:S2|S3", "A12a": "EARLY|LATE|R5 or ANCHOR:R1|R3|R5", "A13": "3|5"}


def level_params(pattern: str, raw: str) -> tuple[object, dict]:
    """A level's name and what it does."""
    up = raw.strip().upper()
    parts = up.split(":")
    bad = SystemExit(f"{pattern} has the levels {LEVEL_FORMS[pattern]}, not {raw!r}")
    if pattern == "A15":
        sched = re.fullmatch(r"S([23])", parts[1]) if len(parts) == 2 else None
        if parts[0] not in SOURCES or len(parts) > 2 or (len(parts) == 2 and not sched):
            raise bad
        return up, {"source": parts[0], "scheduled": int(sched.group(1)) if sched else 0}
    if pattern == "A12a":
        anchor = parts[0] == "ANCHOR"
        release = parts[1] if anchor and len(parts) == 2 else (parts[0] if not anchor and len(parts) == 1 else "")
        if release not in RELEASE_AT or (anchor and release not in ("R1", "R3", "R5")):
            raise bad
        return up, {"target": "ANCHOR" if anchor else "GOLD", "at_reply": RELEASE_AT[release]}
    if up not in ("3", "5"):
        raise bad
    return int(up), {"blocks": int(up)}


def added_sentence(replies: list, sentence: str) -> str:
    """The arm text's note on a sentence code adds at fixed replies (prompts/cond_added_sentence.md)."""
    return prompt("cond_added_sentence").replace("{sentence}", sentence)


def strip_sentences(text: str, sentences) -> tuple[str, int]:
    """Remove the model's own copies of a condition's fixed sentences: only code says them, so the dose stays exact.
    Returns the text and the number removed."""
    removed = 0
    for sentence in sentences:
        body = re.escape(sentence.rstrip(".?!")).replace("'", "['’]")
        text, n = re.subn(r"\s*" + body + r"[.?!]?", "", text, flags=re.IGNORECASE)
        removed += n
    return text.strip(), removed


@dataclass
class Condition:
    """One condition level for a whole run, with the compile step's per-case data where it needs them."""
    pattern: str
    level: object
    data: dict           # dataset -> the compiled file (A12a, A13)
    files: dict          # dataset -> {"path", "sha256"} of that file
    params: dict         # what the level does (level_params)

    @classmethod
    def parse(cls, text: str, conditions_dir: Path | None, datasets) -> "Condition":
        pattern, _, raw = text.partition(":")
        if pattern not in LEVELS:
            raise SystemExit(f"unknown condition {pattern!r}; known: {sorted(LEVELS)}")
        level, params = level_params(pattern, raw)
        data, files = {}, {}
        if pattern in COMPILED:
            if conditions_dir is None:
                raise SystemExit(f"{pattern} needs the compiled per-case data: give --conditions-dir")
            for dataset in datasets:
                path = conditions_dir / f"{dataset}.json"
                raw_bytes = path.read_bytes()
                data[dataset] = json.loads(raw_bytes)
                files[dataset] = {"path": str(path), "sha256": hashlib.sha256(raw_bytes).hexdigest()[:12]}
        return cls(pattern, level, data, files, params)

    @property
    def name(self) -> str:
        return f"{self.pattern}:{self.level}"

    def arms(self) -> tuple:
        """A15 reactive runs both A1 arms; scheduled A1/A15 builds on single exposure (its reactive sentence off)."""
        if self.pattern == "A15":
            return ("single_exposure",) if self.params["scheduled"] else ("persistence", "single_exposure")
        return ("control",)

    def case_data(self, case: Case) -> dict:
        compiled = self.data[case.dataset]
        if compiled.get("release") != case.release:
            raise SystemExit(f"{case.dataset}: the compiled data are for release {compiled.get('release')}, "
                             f"the run uses {case.release}")
        return compiled["cases"][case.case_id]

    def applies(self, case: Case, arm: str) -> bool:
        """A15 runs on the anchored cases, A12a on those with a target (ANCHOR: anchored cases with an anchor fact),
        A13 on every case."""
        if arm not in self.arms():
            return False
        if self.pattern == "A15":
            return bool(case.anchor)
        if self.pattern == "A12a":
            return bool(self.target(case))
        return True

    def target(self, case: Case) -> str | None:
        """A12a: the GOLD target, or the ANCHOR one (a present fact that fits X; anchored cases only)."""
        if self.params["target"] == "GOLD":
            return self.case_data(case)["a12a"]["target"]
        return (self.case_data(case).get("a12a_anchor") or {}).get("target") if case.anchor else None


class Run:
    """A condition in one dialogue: its spec, the directive for each controller turn, the fixed sentences added after
    each reply, and the log."""

    def __init__(self, condition: Condition, case: Case, arm: str):
        self.pattern, self.level, self.case, self.arm = condition.pattern, condition.level, case, arm
        self.params = p = condition.params
        self.entries = case.entries()
        self.phrase = (case.anchor or {}).get("phrase")
        self.payload, self.counters, self.data_file = {}, {}, condition.files.get(case.dataset)
        if self.pattern == "A15":
            opening, still = SOURCES[p["source"]]
            self.payload = {"source": p["source"], "anchor": self.phrase, "opening": opening.format(phrase=self.phrase),
                            "still": still.format(phrase=self.phrase)}
            self.counters = {"persistence_sentences": 0}
            if p["scheduled"]:      # mention 1 is the opening; mentions 2 and 3 at replies 2 and 4
                self.payload.update(scheduled=p["scheduled"], mention=MENTIONS[p["source"]].format(phrase=self.phrase),
                                    at_replies=list(SCHEDULED_AT[:p["scheduled"] - 1]))
                self.counters = {"mentions": 1}
        elif self.pattern == "A12a":
            target = condition.target(case)
            self.payload = {"target": target, "text": self.text(target), "entries": self.standing_for({target}),
                            "release": self.level, "at_reply": p["at_reply"], "target_type": p["target"]}
            self.counters = {"told_at": None, "how": None}
        elif self.pattern == "A13":
            blocks = condition.case_data(case)["a13"]["blocks"]
            facts = []
            for n in range(1, self.level + 1):
                facts += [f for f in blocks.get(str(n), []) if f not in facts]
            self.payload = {"blocks": self.level, "facts": facts, "texts": {f: self.text(f) for f in facts}}
        self.spec = {"pattern": self.pattern, "level": self.level, "payload": self.payload,
                     "counters": dict(self.counters), "data_file": self.data_file}

    def standing_for(self, facts: set) -> list:
        """The entry ids that stand for these facts: the facts themselves and DDXPlus checklist ids answered by them."""
        return [eid for eid, e in self.entries.items() if set(e["facts"]) & facts]

    def text(self, fid: str) -> str:
        return next(f["text"] for f in self.case.facts if f["id"] == fid)

    def entry_line(self, fid: str) -> str:
        fact = next(f for f in self.case.facts if f["id"] == fid)
        return fact_line(fact)

    # ------------------------------------------------------------ the opening

    def opening_ids(self) -> list | None:
        """A13: the facts the first words say (blocks 1..n); otherwise None, the shared opening."""
        return self.payload["facts"] if self.pattern == "A13" else None

    def opening_sentence(self) -> str | None:
        """The fixed sentence after the opening: A15's source sentence (in place of A1's worry)."""
        if self.pattern == "A15":
            return self.payload["opening"]
        return None

    def arm_text(self) -> str | None:
        """A15 replaces the arm section; a sentence code adds at fixed replies is announced, so the model neither
        writes it nor answers against it."""
        if self.pattern == "A15":
            scheduled = self.params["scheduled"]
            if self.params["source"] == "SELF":          # SELF is A1 itself, with A1's own arm text
                text = prompt(f"arm_{self.arm}").replace("{phrase}", self.phrase) if scheduled else None
            else:
                text = prompt(f"cond_a15_{self.arm}").replace("{opening}", self.payload["opening"]).replace(
                    "{still}", self.payload["still"]).replace("{phrase}", self.payload["anchor"])
            if scheduled:
                text += "\n\n" + added_sentence(self.payload["at_replies"], self.payload["mention"])
            return text
        return None

    def opening_log(self, opening_facts: list) -> dict:
        if self.pattern == "A15":
            return {"planned": "source sentence after the opening", "realized": self.payload["opening"]}
        if self.pattern == "A13":
            return {"planned": f"blocks 1-{self.level}", "facts": opening_facts}
        return {}

    # ------------------------------------------------------------ each reply

    def sentences(self) -> list:
        """Every fixed sentence of this condition, for stripping the model's own copies."""
        if self.pattern == "A15":
            return [self.payload["opening"], self.payload["still"]] + (
                [self.payload["mention"]] if self.params["scheduled"] else [])
        return []

    def directive(self, question: int, disclosed: list) -> Directive:
        d = Directive(arm_text=self.arm_text())
        told = told_before(disclosed)
        if self.pattern == "A12a" and self.payload["target"] not in told:
            at = self.payload["at_reply"]
            if at == question:
                d.volunteer = self.payload["target"]
                d.sections.append(prompt("cond_a12a").replace("{entry}", self.entry_line(self.payload["target"])))
            elif question < at:
                d.no_volunteer = set(self.payload["entries"])
        return d

    def strip(self, text: str) -> tuple[str, int]:
        return strip_sentences(text, self.sentences())

    def after(self, question: int, message: str, result, text: str, told: set) -> tuple[str, dict]:
        """The fixed sentences of this reply, added to the model's text; the counters; the log. A15's persistence
        sentence follows A1's rule (a dispute, or a question about the worry)."""
        analysis = result.internal.get("analysis") or {}
        log = {"planned": None, "trigger": None, "realized": None}
        if self.pattern == "A15" and self.params["scheduled"]:
            # scheduled: the mention at its reply, whatever the doctor says (the reactive sentence is off)
            due = question in self.payload["at_replies"]
            log.update(planned=f"mention {self.counters['mentions'] + 1} at reply {question}" if due else None,
                       trigger={"reply": question, "worry_disputed": result.worry_disputed,
                                "worry_asked": result.worry_asked, "doctor": message},
                       x_named_by_model=bool(self.phrase) and self.phrase.lower() in text.lower())
            if due:
                text += " " + self.payload["mention"]
                self.counters["mentions"] += 1
                log["realized"] = self.payload["mention"]
            log["appended"] = due
        elif self.pattern == "A15":
            due = self.arm == "persistence" and (result.worry_disputed or result.worry_asked)
            log.update(planned="persistence sentence if the worry is disputed or asked about" if self.arm ==
                       "persistence" else None,
                       trigger={"worry_disputed": result.worry_disputed, "worry_asked": result.worry_asked,
                                "doctor": message},
                       x_named_by_model=bool(self.phrase) and self.phrase.lower() in text.lower())
            if due:
                text += " " + self.payload["still"]
                self.counters["persistence_sentences"] += 1
                log["realized"] = self.payload["still"]
            log["appended"] = due
        elif self.pattern == "A12a":
            target, at = self.payload["target"], self.payload["at_reply"]
            before = target in told
            if not before:
                log["planned"] = "volunteer the target" if at == question else "not volunteered"
            log["trigger"] = {"reply": question, "told_before": before}
            if not before and target in result.facts:
                parts = {x for p in analysis.get("parts") or [] if p.get("answer") == "from_record"
                         for f in p["facts"] for x in self.entries.get(f, {}).get("facts", [f])}
                opened = {x for f in (analysis.get("open") or {}).get("entries", [])
                          for x in self.entries.get(f, {}).get("facts", [f])}
                how = "asked" if target in parts else "open question" if target in opened else "volunteered"
                self.counters.update(told_at=question, how=how)
                log["realized"] = f"told ({how})"
        log["counters"] = dict(self.counters)
        return text, log

    def end(self, replies: int, stop: str | None) -> dict:
        """The dialogue's condition record: the spec, the final counters, the planned actions not delivered (the
        doctor finished first) and the outcome."""
        undelivered, outcome = [], None
        late = f"the doctor finished after question {replies}"
        if self.pattern == "A15" and self.params["scheduled"]:
            undelivered = [f"mention {k + 2} at reply {r}: {late}"
                           for k, r in enumerate(self.payload["at_replies"]) if r > replies]
            outcome = f"{self.counters['mentions']} of {self.params['scheduled']} mentions"
        elif self.pattern == "A12a":
            at = self.payload["at_reply"]
            if self.counters["told_at"] is None and at > replies:
                undelivered.append(f"volunteer at reply {at}: the doctor finished after question {replies}")
            outcome = ("never told" if self.counters["told_at"] is None
                       else f"told at reply {self.counters['told_at']} ({self.counters['how']})")
        return {**self.spec, "counters": dict(self.counters), "undelivered": undelivered, "outcome": outcome,
                "replies": replies, "stop": stop}
