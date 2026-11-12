"""The fixed study doctor (simulator/README.md), the same in every arm and condition. Variant T (simulator/README.md):
in the TT and TE regimes the doctor can retrieve the case's findings once with {"action": "tests"}."""
from __future__ import annotations

import hashlib
import json
import re

from .llm import Client, parse_json

SYSTEM = """You are a physician in an outpatient clinic. A patient has come to see you.
Patient: {age}-year-old {sex}.

Take a focused medical history by talking with the patient, then give your
assessment. You cannot examine the patient or order tests during this
conversation. You can ask at most {max_questions} questions in total.

Reply with JSON every turn:
{"action": "ask", "message": "<what you say to the patient>"} to continue, or
{"action": "finish", "message": "<brief closing words to the patient>"} when
you are ready to give your assessment."""

FINAL_REQUEST = """[Note to the physician, not from the patient] The consultation has ended.
Give your assessment based only on this conversation. Return JSON with
"most_likely" (one diagnosis), "differential" (up to 5 diagnoses, most likely
first, including the most likely one) and "rationale" (two or three sentences)."""

RETRY_NOTE = """[Note to the physician] Use the required format: "differential" must list
1 to 5 distinct diagnoses and must include "most_likely" as its first entry."""

CLOSING = "Thank you, I have what I need."
MAX_QUESTIONS = 8
TURN_SAMPLING = {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "max_tokens": 300}
FINAL_SAMPLING = {"temperature": 0.0, "max_tokens": 600}
FINAL_RETRIES = 2
TURN_FORMAT_RETRIES = 2    # re-samples of a malformed doctor turn, then error:doctor_format
# Both doctor calls are schema-forced (simulator/README.md).
TURN_SCHEMA = {"type": "object", "properties": {"action": {"enum": ["ask", "finish"]}, "message": {"type": "string"}},
               "required": ["action", "message"]}
FINAL_SCHEMA = {"type": "object", "properties": {"most_likely": {"type": "string"},
                                                 "differential": {"type": "array", "items": {"type": "string"}},
                                                 "rationale": {"type": "string"}},
                "required": ["most_likely", "differential", "rationale"]}


# Variant T (TT/TE): the system prompt's sentence on examining and tests, per regime; the findings each regime
# shows (only those labelled "other"); the results message, written by code
NO_TESTS_SENTENCE = "You cannot examine the patient or order tests during this\nconversation."
TESTS_SENTENCE = {
    "TT": """You cannot examine the patient or order new tests during this conversation.
The results of tests already done for this patient are available to you
directly, without asking the patient. They can be shown to you once,
all at the same time, if you think they are relevant: reply
{"action": "tests", "message": ""} instead of a question. Then continue
with "ask" or "finish".""",
    "TE": """You cannot examine the patient or order new tests during this conversation.
The vital signs, physical examination findings and results of tests already
done for this patient are available to you directly, without asking the
patient. They can be shown to you once, all at the same time, if you think
they are relevant: reply {"action": "tests", "message": ""} instead of a
question. Then continue with "ask" or "finish"."""}
TESTS_KINDS = {"TT": ("test",), "TE": ("vital", "exam", "test")}
TESTS_HEADER = {"TT": "[Test results, not from the patient]",
                "TE": "[Examination and test results, not from the patient]"}
TESTS_GROUPS = (("vital", "Vital signs:"), ("exam", "Examination:"), ("test", "Tests:"))
NO_RESULTS = "[Test results, not from the patient] No test results are available."
TURN_SCHEMA_TESTS = {"type": "object", "properties": {"action": {"enum": ["ask", "finish", "tests"]},
                                                      "message": {"type": "string"}},
                     "required": ["action", "message"]}
# In variant T a "finish" cut off at the turn limit is requested again with the same seed and the final's limit
# every other turn is re-sampled as above.
CLOSING_SAMPLING = {**TURN_SAMPLING, "max_tokens": FINAL_SAMPLING["max_tokens"]}
CUT_FINISH = re.compile(r'\s*\{\s*"action"\s*:\s*"finish"')


def results_message(tests: str, findings: list, labels: dict) -> tuple[str, list, list]:
    """The reply to "tests": (the message, ids shown, ids hidden). Shown: the regime's kinds labelled "other", in record
    order (TE grouped by kind), as "- <name>: <result>", or "- <name> (<time>): <result>" when the record gives a time;
    hidden: those kinds labelled "names" or "confirms"."""
    kinds = TESTS_KINDS[tests]
    eligible = [f for f in findings if f["kind"] in kinds]
    shown = [f for f in eligible if labels[f["id"]]["label"] == "other"]
    hidden = [f["id"] for f in eligible if labels[f["id"]]["label"] != "other"]
    if not shown:
        return NO_RESULTS, [], hidden
    lines = [TESTS_HEADER[tests]]
    for kind, title in TESTS_GROUPS:
        group = [f for f in shown if f["kind"] == kind]
        if group and tests == "TE":
            lines.append(title)
        lines += [f"- {f['name']}" + (f" ({f['time']})" if f.get("time") else "") + f": {f['result']}" for f in group]
    return "\n".join(lines), [f["id"] for f in shown], hidden


class DoctorFormatError(RuntimeError):
    def __init__(self, message: str, extensions: list | None = None):
        super().__init__(message)
        self.extensions = extensions or []


def doctor_seed(case_id: str, seed: int, turn, attempt: int) -> int:
    """The doctor's sampling seed, the same formula in every design (simulator/README.md): turn is 1..8 or "final",
    attempt is 0, or 1 and 2 for re-samples and retries."""
    return int(hashlib.sha256(f"{case_id}|{seed}|{turn}|{attempt}|doctor".encode()).hexdigest()[:8], 16) % 2**31


def system_prompt(demographics: dict, tests: str | None = None) -> str:
    # str.format would trip over the JSON braces in the prompt.
    text = SYSTEM if tests is None else SYSTEM.replace(NO_TESTS_SENTENCE, TESTS_SENTENCE[tests])
    return (text.replace("{age}", str(demographics["age"])).replace("{sex}", str(demographics["sex"]))
            .replace("{max_questions}", str(MAX_QUESTIONS)))


def as_message(action: str, message: str) -> dict:
    """A doctor turn as it stays in the doctor's own history."""
    return {"role": "assistant", "content": json.dumps({"action": action, "message": message}, ensure_ascii=False)}


def parse_turn(text: str, actions: tuple) -> tuple[str, str] | None:
    """(action, message) of a valid doctor turn, or None."""
    try:
        value = parse_json(text)
    except ValueError:
        return None
    action, message = value.get("action"), value.get("message")
    if action in actions and isinstance(message, str) and (action == "tests" or message.strip()):
        return action, message.strip()
    return None


def valid_final(value) -> bool:
    if not isinstance(value, dict):
        return False
    most_likely, differential = value.get("most_likely"), value.get("differential")
    if not isinstance(most_likely, str) or not most_likely.strip():
        return False
    if not isinstance(differential, list) or not 1 <= len(differential) <= 5:
        return False
    if not all(isinstance(d, str) and d.strip() for d in differential):
        return False
    names = [d.strip().lower() for d in differential]
    return len(set(names)) == len(names) and names[0] == most_likely.strip().lower() \
        and isinstance(value.get("rationale"), str)


class Doctor:
    def __init__(self, client: Client, tests: str | None = None):
        self.client = client
        self.tests = tests        # None, or the variant T regime: "TT" or "TE"

    def turn(self, case_id: str, seed: int, turn: int, demographics: dict, history: list,
             tests_open: bool = False) -> tuple[str, str, int, list]:
        """Doctor turn number `turn` (1..8; 1..9 with a "tests" turn, which counts on): (action, message, format
        re-samples, extensions). With tests_open, "tests" is offered too. In variant T a sample cut off at the turn
        limit inside a "finish" is requested again with the same seed and CLOSING_SAMPLING; only a valid "finish" is
        taken from it. Each such request is listed in extensions (its sample, tokens, finish reason, valid)."""
        messages = [{"role": "system", "content": system_prompt(demographics, self.tests)}] + history
        actions = ("ask", "finish", "tests") if tests_open else ("ask", "finish")
        extensions = []
        for attempt in range(TURN_FORMAT_RETRIES + 1):
            request = {"seed": doctor_seed(case_id, seed, turn, attempt),
                       "schema": TURN_SCHEMA_TESTS if tests_open else TURN_SCHEMA, "schema_name": "doctor_turn"}
            reply = self.client.chat(messages, **request, **TURN_SAMPLING)
            parsed = parse_turn(reply.text, actions)
            if parsed is None and self.tests and reply.finish_reason == "length" and CUT_FINISH.match(reply.text):
                reply = self.client.chat(messages, **request, **CLOSING_SAMPLING)
                parsed = parse_turn(reply.text, ("finish",))
                extensions.append({"sample": attempt, "tokens_out": reply.tokens_out,
                                   "finish_reason": reply.finish_reason, "valid": parsed is not None})
            if parsed:
                return parsed[0], parsed[1], attempt, extensions
        raise DoctorFormatError(f"doctor turn not valid after {TURN_FORMAT_RETRIES + 1} samples: {reply.text[:200]!r}",
                                extensions)

    def final(self, case_id: str, seed: int, demographics: dict, history: list) -> tuple[dict | None, int]:
        """The final assessment: (the parsed JSON or None, retries used). Invalid after the retries: the last
        parsed object is returned as it is."""
        messages = [{"role": "system", "content": system_prompt(demographics, self.tests)}] + history + \
                   [{"role": "user", "content": FINAL_REQUEST}]
        value = None
        for attempt in range(FINAL_RETRIES + 1):
            reply = self.client.chat(messages, seed=doctor_seed(case_id, seed, "final", attempt), schema=FINAL_SCHEMA,
                                     schema_name="final_assessment", **FINAL_SAMPLING)
            try:
                value = parse_json(reply.text)
            except ValueError:
                value = None
            if valid_final(value):
                return value, attempt
            messages += [{"role": "assistant", "content": reply.text}, {"role": "user", "content": RETRY_NOTE}]
        return value, FINAL_RETRIES
