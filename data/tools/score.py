"""Diagnosis-name matcher: `name` occurs in `text` as a whole word, case-insensitive; a plural -s/-es also
matches. simulator/sim/compile_tests.py uses it to label the findings that name the gold diagnosis or an
alias (`data/tests`). Dialogues are scored with scoring/score.py, which matches in the same way.
"""
import re


def matches(name: str, text: str) -> bool:
    return bool(re.search(r"(?<![a-z0-9])" + re.escape(name.lower()) + r"(?:s|es)?(?![a-z0-9])", text.lower()))
