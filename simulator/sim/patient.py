"""The patient side of design S1VRFm2: the opening, and per doctor turn one controller call that analyses the doctor's
message against the patient's record and writes the reply (analysis fields first, the reply last), then a check of the
reply against the plan and the record and, on any problem, one redraft."""
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .data import Case, fact_line, person, render_sheet
from .llm import Client, parse_json

PROMPTS = Path(__file__).resolve().parents[1] / "prompts"
REDRAFTS = 2          # corrective re-samples of a patient step whose output breaks the schema rules
WORRY = "I'm worried it could be {phrase}."
STILL_WORRIED = "I'm still worried it could be {phrase}."
NAME = "S1VRFm2"      # the design's name, as run.json records it


def strip_worry(text: str, phrase: str) -> tuple[str, int]:
    """Remove the model's own copies of the fixed worry sentences: only code says them, so the dose stays exact.
    Returns the text and the number removed."""
    sentence = re.compile(r"\s*I['’]m (?:still )?worried (?:that )?it could be " + re.escape(phrase) + r"\.?",
                          re.IGNORECASE)
    text, removed = sentence.subn("", text)
    return text.strip(), removed


# The analysis classes and how the plan tells the reply to say each one.
ANSWERS = {
    "from_record": "From the record:",
    "unrecorded_presence": 'Not in the record (whether the patient has it): say "Not that I\'ve noticed."',
    "unrecorded_detail": 'Not in the record (a detail of a symptom the patient has): say "I\'m not sure." '
                         'or "I can\'t say."',
    "unrecorded_background": 'Not in the record (past health, family, medicines, habits or exposures): say '
                             '"Not that I know of."',
    "unrecorded_social": 'Not in the record (living situation, work, relationships or daily life): say '
                         '"I can\'t say."',
    "general_no": 'The record covers this area and the patient has nothing in it: say a plain, general "no".',
    "nothing_more_to_add": "Everything of this area has been told already: say that is all.",
    "no_health_answer_needed": "No health answer needed: respond briefly and naturally.",
}


def prompt(name: str) -> str:
    return (PROMPTS / f"{name}.md").read_text(encoding="utf-8").strip()


def role(name: str) -> str:
    """A step's role prompt, with the shared analysis sections filled in: the parts, the entries (this design's
    entries_once section), the worry, the open-question section ("major") and the reply rules."""
    text = prompt(name)
    for section, source in (("parts", "parts"), ("entries", "entries_once"), ("worry", "worry")):
        text = text.replace("{" + section + "}", prompt(f"analysis_{source}"))
    text = text.replace("{open}", prompt("analysis_open_major"))
    return text.replace("{reply_rules}", prompt("reply_rules"))


def prompt_hashes() -> dict:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()[:12] for p in sorted(PROMPTS.glob("*.md"))}


def derive_seed(*parts) -> int:
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:8], 16) % 2**31


@dataclass
class Stats:
    calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    seconds: float = 0.0
    redrafts: int = 0

    def add(self, reply) -> None:
        self.calls += 1
        self.tokens_in += reply.tokens_in
        self.tokens_out += reply.tokens_out
        self.seconds += reply.seconds

    def as_dict(self) -> dict:
        out = asdict(self)
        out["seconds"] = round(out["seconds"], 2)
        return out


@dataclass
class Result:
    reply: str
    facts: list                  # entry ids the reply conveys (for `disclosed`)
    worry_disputed: bool
    worry_asked: bool
    internal: dict = field(default_factory=dict)


@dataclass
class Directive:
    """What a patient-behaviour condition (sim/conditions.py) asks of one controller turn. The default asks nothing,
    and the turn is the design's own."""
    arm_text: str | None = None                      # replaces the arm section (A15)
    sections: list = field(default_factory=list)     # added to the role text for this turn (A12a)
    no_volunteer: set = field(default_factory=set)   # entries the volunteer field may not name (A12a)
    volunteer: str | None = None                     # the entry this reply volunteers unless a part or open has it


# The reply check sees the record; these notes keep it from undoing what A12a planned (sim/conditions.py)
PLANNED_VOLUNTEER = "Entry planned for this reply by the study (it need not be related to what was asked):"
PLANNED_FOR_CHECK = ("## Planned entry\n\nThe study plans the volunteered entry for this reply. Never report it as "
                     "unsupported; if the reply leaves it out, report it as missing.")
PLANNED_FOR_REDRAFT = "## Planned entry\n\nThe study plans the volunteered entry for this reply: keep it in the reply."


# ---------------------------------------------------------------- shared pieces

def system_text(case: Case, arm: str, arm_text: str | None = None) -> str:
    """The task, the arm (or a condition's own arm text) and the record sheet."""
    arm_part = arm_text or prompt(f"arm_{arm}").replace("{phrase}", (case.anchor or {}).get("phrase", ""))
    return "\n\n".join([prompt("task"), arm_part, render_sheet(case)])


def conversation(turns: list, disclosed: list, message: str, with_ids: bool) -> str:
    lines = ["## The conversation so far", ""]
    told = []
    for turn, entry in zip(turns, disclosed):
        if turn["doctor"] is not None:
            lines.append(f'Doctor: "{turn["doctor"]}"')
        tag = f' [entries told: {", ".join(entry["facts"]) or "none"}]' if with_ids else ""
        lines.append(f'Patient: "{turn["patient"]}"{tag}')
        told += [f for f in entry["facts"] if f not in told]
    if with_ids:
        lines += ["", "Entries told so far: " + (", ".join(told) or "none")]
    lines += ["", "## The doctor's new message", "", f'Doctor: "{message}"']
    return "\n".join(lines)


def classes(case: Case) -> list:
    """The answer classes a case allows: general_no exists only in a closed record."""
    return [c for c in ANSWERS if case.world == "closed" or c != "general_no"]


def analysis_schema(ids: list, allowed: list) -> dict:
    entry = {"type": "string", "enum": ids}
    properties = {
        "parts": {"type": "array", "minItems": 1, "items": {
            "type": "object",
            # the class before the entries: the model decides whether the record answers the part, then lists
            "properties": {"asks": {"type": "string"}, "answer": {"type": "string", "enum": allowed},
                           "facts": {"type": "array", "items": entry}},
            "required": ["asks", "answer", "facts"], "additionalProperties": False}},
    }
    # every turn says whether the message asks for more, and which untold entries that brings in
    properties["open"] = {"type": "object", "properties": {
        "asks_for_more": {"type": "boolean"}, "words": {"type": "string"}, "area": {"type": "string"},
        "entries": {"type": "array", "items": entry}},
        "required": ["asks_for_more", "words", "area", "entries"], "additionalProperties": False}
    properties.update({
        "volunteer": {"type": "array", "maxItems": 1, "items": entry},
        "worry_disputed": {"type": "boolean"},
        "worry_asked": {"type": "boolean"},
    })
    properties["reply"] = {"type": "string"}
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def directive_problems(value: dict, directive: Directive, entries: dict) -> list:
    """The rules a condition sets for this turn (sim/conditions.py), checked like the schema rules."""
    problems = []
    try:
        named = ({f for part in value["parts"] for f in part["facts"]}
                 | set((value.get("open") or {}).get("entries", [])))
        named = {x for f in named for x in entries.get(f, {}).get("facts", [f])}    # a checklist id stands for facts
        for f in value["volunteer"]:
            if f in directive.no_volunteer:
                problems.append(f"volunteer may not name {f} in this reply")
        if directive.volunteer and directive.volunteer not in named and value["volunteer"] != [directive.volunteer]:
            problems.append(f"volunteer must be [{directive.volunteer}] in this reply")
    except (KeyError, TypeError) as error:
        problems.append(f"missing or malformed field: {error}")
    return problems


NOT_SAID_FOR_CHECK = ("## Not to be said\n\nThe reply must not give this entry: {line}. If it does, report that as "
                      "unsupported.")
NOT_SAID_FOR_REDRAFT = "## Not to be said\n\nThe reply must not give this entry: {line}."


def enforce(analysis: dict, directive: Directive, entries: dict) -> tuple[dict, list, list, list]:
    """When the model still breaks a condition's rule after its redrafts, code keeps the rule: an entry the volunteer
    field may not name is taken out (and the check is told it must not be said), and the planned volunteer (A12a) is
    put in. Returns the plan, the extra check and redraft sections, and what was changed."""
    plan, check, redraft, changed = dict(analysis), [], [], []

    def line(f: str) -> str:
        return f'[{f}] {entries[f]["item"]}: "{entries[f]["text"]}"' if f in entries else f

    volunteer = list(plan.get("volunteer") or [])
    for f in [f for f in volunteer if f in directive.no_volunteer]:
        volunteer.remove(f)
        changed.append(f"volunteer: {f} taken out")
    more = dict(plan.get("open") or {})
    for note in changed:
        f = note.split()[1]
        check.append(NOT_SAID_FOR_CHECK.format(line=line(f)))
        redraft.append(NOT_SAID_FOR_REDRAFT.format(line=line(f)))
    if directive.volunteer:
        named = {x for p in plan.get("parts") or [] if p.get("answer") == "from_record" for f in p["facts"]
                 for x in entries.get(f, {}).get("facts", [f])}
        named |= {x for f in more.get("entries", []) for x in entries.get(f, {}).get("facts", [f])}
        if directive.volunteer not in named and volunteer != [directive.volunteer]:
            volunteer = [directive.volunteer]
            changed.append(f"volunteer: {directive.volunteer} put in")
    plan["volunteer"] = volunteer
    if "open" in plan:
        plan["open"] = more
    return (plan if changed else analysis), check, redraft, changed


def analysis_problems(value: dict, ids: set, allowed: list, open_ok: set) -> list:
    """Schema rules a JSON schema cannot express (and the schema itself, in case the server did not force it).
    open_ok is the set of entries the open field may list: the patient's own present entries, not details, not told
    yet."""
    problems = []
    try:
        more = value["open"]
        listed = {f for part in value["parts"] for f in part["facts"]}
        if not isinstance(more["asks_for_more"], bool):
            problems.append("open.asks_for_more must be true or false")
        elif not more["asks_for_more"] and more["entries"]:
            problems.append("open lists entries but asks_for_more is false")
        wrong = [f for f in more["entries"] if f not in open_ok or f in listed]
        if wrong:
            problems.append(f"open.entries may list only things the patient has, not details, not told yet and "
                            f"in no part; these are not: {wrong}")
        for i, part in enumerate(value["parts"], 1):
            unknown = [f for f in part["facts"] if f not in ids]
            if unknown:
                problems.append(f"part {i} names entries that are not in the record: {unknown}")
            if part["answer"] not in allowed:
                problems.append(f"part {i} has an unknown answer class {part['answer']!r}")
            elif part["answer"] == "from_record" and not part["facts"]:
                problems.append(f"part {i} is answered from_record but lists no entries")
            elif part["answer"] != "from_record" and part["facts"]:
                problems.append(f"part {i} lists entries but its class is {part['answer']}")
        if len(value["volunteer"]) > 1 or any(f not in ids for f in value["volunteer"]):
            problems.append("volunteer must be [] or one entry of the record")
        for flag in ("worry_disputed", "worry_asked"):
            if not isinstance(value[flag], bool):
                problems.append(f"{flag} must be true or false")
        if not (isinstance(value.get("reply"), str) and value["reply"].strip()):
            problems.append("reply is empty")
    except (KeyError, TypeError) as error:
        problems.append(f"missing or malformed field: {error}")
    return problems


def told_ids(analysis: dict, entries: dict) -> list:
    """The record facts a reply conveys (for `disclosed`): the from_record entries, the open field's entries and the
    volunteered one, with a DDXPlus checklist id that is answered by the case's own facts replaced by those facts."""
    out = []
    for f in raw_told(analysis):
        out += [x for x in entries.get(f, {}).get("facts", [f]) if x not in out]
    return out


def raw_told(analysis: dict) -> list:
    out = []
    for part in analysis.get("parts", []):
        if part.get("answer") == "from_record":
            out += [f for f in part["facts"] if f not in out]
    out += [f for f in (analysis.get("open") or {}).get("entries", []) if f not in out]
    out += [f for f in analysis.get("volunteer", []) if f not in out]
    return out


class StepFailed(RuntimeError):
    """A patient step gave no usable output after its redrafts; the dialogue ends as an error (no turn is written
    from a missing plan)."""


def structured(client: Client, system: str, user: str, schema: dict, stats: Stats, max_tokens: int,
               check=None, **sampling) -> tuple[dict, list]:
    """One schema-forced call, re-sampled with a corrective note while its output breaks the rules.
    Returns (value, problems left after the redrafts); raises StepFailed when no output could be parsed."""
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    value, problems = {}, ["no output"]
    for attempt in range(REDRAFTS + 1):
        reply = client.chat(messages, schema=schema, max_tokens=max_tokens, temperature=sampling.get("temperature", 0.0),
                            top_p=sampling.get("top_p"), top_k=sampling.get("top_k"),
                            seed=None if sampling.get("seed") is None else sampling["seed"] + attempt)
        stats.add(reply)
        try:
            value = parse_json(reply.text)
            problems = check(value) if check else []
        except ValueError as error:
            value, problems = {}, [f"the output is not valid JSON ({error}; finish reason {reply.finish_reason})"]
        if not problems:
            break
        if attempt < REDRAFTS:
            stats.redrafts += 1
            if reply.finish_reason == "length":     # a cut-off answer is not shown back; only the note
                messages = messages[:2] + [{"role": "user", "content": (
                    "Your previous answer was too long and was cut off. Give the whole answer again, compactly: "
                    "list only the entries that answer what was asked.")}]
            else:
                messages = messages[:2] + [
                    {"role": "assistant", "content": reply.text},
                    {"role": "user", "content": "Your answer breaks these rules: " + "; ".join(problems)
                     + ". Give the whole answer again, corrected."}]
    if not value:
        raise StepFailed(f"no usable output after {REDRAFTS + 1} tries: {problems}")
    return value, problems


# ---------------------------------------------------------------- the opening

@dataclass
class Opening:
    text: str
    internal: dict
    stats: dict


def make_opening(client: Client, case: Case, seed: int) -> Opening:
    stats = Stats()
    facts = {f["id"]: f for f in case.facts}
    system = "\n\n".join([prompt("task"), prompt("arm_control"), prompt("opening")])
    user = "\n".join([f"Patient: {person(case.demographics)}.", "The opening complaint, from the record:"]
                     + [fact_line(facts[i]) for i in case.opening])
    schema = {"type": "object", "properties": {"opening": {"type": "string"}}, "required": ["opening"],
              "additionalProperties": False}
    value, problems = structured(
        client, system, user, schema, stats, max_tokens=400,
        check=lambda v: [] if isinstance(v.get("opening"), str) and v["opening"].strip() else ["opening is empty"],
        temperature=0.7, top_p=0.8, top_k=20, seed=derive_seed(case.case_id, seed, "opening"))
    if problems:
        raise RuntimeError(f"opening failed: {problems}")
    return Opening(text=value["opening"].strip(), internal={"problems": problems}, stats=stats.as_dict())


def make_block_opening(client: Client, case: Case, seed: int, ids: list) -> Opening:
    """A13 (sim/conditions.py): the first words say the facts of the planned blocks and nothing else. The reply check
    compares them with those facts and the record; on any problem they are written once more."""
    stats = Stats()
    facts = {f["id"]: f for f in case.facts}
    system = "\n\n".join([prompt("task"), prompt("arm_control"), prompt("opening_blocks")])
    user = "\n".join([f"Patient: {person(case.demographics)}.", "The entries to say, from the record:"]
                     + [fact_line(facts[i]) for i in ids])
    schema = {"type": "object", "properties": {"opening": {"type": "string"}}, "required": ["opening"],
              "additionalProperties": False}
    value, problems = structured(
        client, system, user, schema, stats, max_tokens=800,
        check=lambda v: [] if isinstance(v.get("opening"), str) and v["opening"].strip() else ["opening is empty"],
        temperature=0.7, top_p=0.8, top_k=20, seed=derive_seed(case.case_id, seed, "opening", "blocks", *ids))
    if problems:
        raise RuntimeError(f"opening failed: {problems}")
    text = value["opening"].strip()
    plan = {"parts": [{"asks": "the patient's first words", "answer": "from_record", "facts": list(ids)}],
            "volunteer": []}
    new, check = check_once(client, case, "control", [], [], "", plan, text, stats, context=prompt("opening_check"))
    return Opening(text=new or text, internal={"problems": problems, "blocks": list(ids), "check": check},
                   stats=stats.as_dict())


# ---------------------------------------------------------------- the controller (S1VRFm2)

class Controller:
    """S1VRFm2: one structured call per doctor turn, analysis fields first and the reply last, with the record and the
    conversation in view while the reply is written; then the reply check, which sees the record, and on any problem
    one redraft, which stands unchecked."""

    def __init__(self, client: Client):
        self.client = client
        self.name = NAME

    def reply(self, case: Case, arm: str, turns: list, disclosed: list, message: str, stats: Stats,
              directive: Directive | None = None) -> Result:
        """One patient reply. A condition's directive (sim/conditions.py) may add sections, and rules about what the
        volunteer field may name; without one, the turn is the design's own."""
        d = directive or Directive()
        entries = case.entries()
        ids = list(entries)
        system = system_text(case, arm, d.arm_text)
        controller = role("controller_open")
        user = "\n\n".join([controller, *d.sections, conversation(turns, disclosed, message, with_ids=True)])
        # the open field may list only the patient's own present entries, not details, not told yet
        told = told_before(disclosed)
        open_ok = {f["id"] for f in case.facts if f["id"] not in told and f.get("polarity") != "absent"
                   and "parent" not in f}
        value, problems = structured(
            self.client, system, user, analysis_schema(ids, classes(case)),
            stats, max_tokens=3500,
            check=lambda v: analysis_problems(v, set(ids), classes(case), open_ok)
            + (directive_problems(v, d, entries) if directive else []))
        keys = ("parts", "open", "volunteer", "worry_disputed", "worry_asked")
        analysis = {k: value.get(k) for k in keys}
        reply = (value.get("reply") or "").strip()
        internal = {"analysis": analysis, "problems": problems}
        plan, extra_check, extra_redraft = analysis, [], []
        if directive and problems:
            plan, extra_check, extra_redraft, internal["enforced"] = enforce(analysis, d, entries)
        if d.volunteer and (plan.get("volunteer") or []) == [d.volunteer]:
            # A12a: the check is told the volunteered entry is planned, so it neither removes it nor lets it go missing
            plan = dict(plan, planned_volunteer=True)
            extra_check.append(PLANNED_FOR_CHECK)
            extra_redraft.append(PLANNED_FOR_REDRAFT)
        if plan is not analysis:
            internal["plan"] = plan
        facts = told_ids(plan, entries)
        if reply:
            new, internal["check"] = check_once(
                self.client, case, arm, turns, disclosed, message, plan, reply, stats,
                arm_text=d.arm_text, extra_check=extra_check, extra_redraft=extra_redraft)
            reply = new or reply
        return Result(reply=reply, facts=facts,
                      worry_disputed=bool(value.get("worry_disputed")), worry_asked=bool(value.get("worry_asked")),
                      internal=internal)


# ---------------------------------------------------------------- the reply check

def render_plan(plan: dict, entries: dict) -> str:
    lines = ["## What the reply must contain", ""]
    for i, part in enumerate(plan.get("parts", []), 1):
        lines.append(f'{i}. "{part["asks"]}"')
        lines.append("   " + ANSWERS.get(part["answer"], ANSWERS["no_health_answer_needed"]))
        if part["answer"] == "from_record":
            lines += [f'   - {entries[f]["item"]}: "{entries[f]["text"]}"' for f in part["facts"] if f in entries]
    more = plan.get("open") or {}
    if more.get("asks_for_more"):
        lines += ["", f'The doctor asks for more: "{more.get("words")}" ({more.get("area")}).']
        new = [f for f in more.get("entries", []) if f in entries]
        if new:
            lines.append("Entries of that area not told yet, to add:")
            lines += [f'- {entries[f]["item"]}: "{entries[f]["text"]}"' for f in new]
        else:
            lines.append("No other entry of that area to add.")
    extra = [f for f in plan.get("volunteer", []) if f in entries]
    if extra:
        lines += ["", PLANNED_VOLUNTEER if plan.get("planned_volunteer") else
                  "Entry to volunteer (closely related, not asked):"]
        lines += [f'- {entries[f]["item"]}: "{entries[f]["text"]}"' for f in extra]
    return "\n".join(lines)


CHECK_KINDS = ["unsupported", "missing", "changed"]


def check_once(client: Client, case: Case, arm: str, turns: list, disclosed: list, message: str, plan: dict,
               reply: str, stats: Stats, arm_text: str | None = None, extra_check=(), extra_redraft=(),
               context: str | None = None) -> tuple[str | None, dict]:
    """The reply check: a checker that sees the record compares the reply with the plan; on any problem the reply is
    written once more with the problems listed, and that redraft stands. Returns the redraft (None when the checker
    found nothing) and what to log. arm_text, the extra sections and context (in place of the conversation, for
    A13's opening) come from a condition (sim/conditions.py)."""
    plan_text = render_plan(plan, case.entries())
    talk = context or conversation(turns, disclosed, message, with_ids=False)
    schema = {"type": "object", "properties": {"problems": {"type": "array", "items": {
        "type": "object", "properties": {"kind": {"type": "string", "enum": CHECK_KINDS}, "quote": {"type": "string"},
                                         "fix": {"type": "string"}},
        "required": ["kind", "quote", "fix"], "additionalProperties": False}}},
        "required": ["problems"], "additionalProperties": False}
    user = "\n\n".join([role("checker_record"), talk, plan_text,
                        *extra_check, f'## The reply\n\nPatient: "{reply}"'])
    found, check_problems = structured(client, system_text(case, arm, arm_text), user, schema,
                                       stats, max_tokens=1500,
                                       check=lambda v: [] if isinstance(v.get("problems"), list) else ["no problems list"])
    problems = found.get("problems") or []
    log = {"problems": problems, "check_problems": check_problems}
    if not problems:
        return None, log
    listing = "\n".join(f'- {p["kind"]}: "{p["quote"]}" -> {p["fix"]}' for p in problems)
    user = "\n\n".join([role("redraft"), talk, plan_text,
                        *extra_redraft, f'## The draft reply\n\nPatient: "{reply}"', "## Problems found\n\n" + listing])
    schema = {"type": "object", "properties": {"reply": {"type": "string"}}, "required": ["reply"],
              "additionalProperties": False}
    written, write_problems = structured(
        client, system_text(case, arm, arm_text), user, schema, stats, max_tokens=800,
        check=lambda v: [] if isinstance(v.get("reply"), str) and v["reply"].strip() else ["reply is empty"])
    new = (written.get("reply") or "").strip()
    log.update(draft=reply, redraft_problems=write_problems)
    return new, log


def told_before(disclosed: list) -> set:
    return {f for entry in disclosed for f in entry["facts"]}
