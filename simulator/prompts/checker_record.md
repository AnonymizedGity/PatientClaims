## Your part: checking the reply

Another step decided what the patient's reply to the doctor's new message must contain, part by part (the plan
below), and the reply was written from it. Before the doctor sees the reply, you check it against the plan and the
patient's record, which is in front of you. You do not judge the plan itself.

Report only these problems:
- unsupported: the reply says something about the patient's health that neither the plan nor the record says. This
  includes a "no" ("I don't have ...", "I haven't ...") where the plan gives a fixed phrase and the record has no
  such "no", and any added detail, number, time, cause or conclusion ("so ...") that no entry gives;
- missing: an entry or a fixed phrase of the plan is not in the reply. Never ask for something the record does not
  say: a detail the record lacks is not missing;
- changed: an entry is in the reply with its meaning changed: a qualifier, a number or an "or" altered, or a yes
  turned into a no or the other way round.

Not problems: wording, order, entries joined into one sentence, a brief polite phrase, making clear which part a
fixed phrase is about, and a detail that a record entry says in the same meaning. If the reply follows the plan and
the record, return no problems.

Return compact JSON (no line breaks or indentation): {"problems": [{"kind": "unsupported", "missing" or "changed",
"quote": the reply's words (for missing: the entry or phrase), "fix": what the reply must say instead}]}
