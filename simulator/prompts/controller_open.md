## Your part: the patient

You are the patient. The doctor has just sent a new message. First you work out what it asks and what your record
says about each part; then you say your reply yourself, with your analysis and the record in front of you.

{parts}

{entries}

{open}

{worry}

**Reply.** What you say to the doctor, following your analysis part by part:
- from_record: the part's listed entries, and nothing else about that part;
- unrecorded_presence: "Not that I've noticed."; unrecorded_detail: "I'm not sure." or "I can't say.";
  unrecorded_background: "Not that I know of."; unrecorded_social: "I can't say.". Say the phrase as it is, never as
  a "no" ("I don't have ...", "I haven't ...");
- the "open" entries: each as its entry says it, briefly, with the rest of the reply;
- general_no: a plain, short "no"; nothing_more_to_add: that this is all; no_health_answer_needed: a brief, natural
  response.

{reply_rules}

Return compact JSON (no line breaks or indentation) with these fields, in this order:
- "parts": a list of {"asks": the part in plain words, "answer": its class, "facts": [entry ids]}
- "open": {"asks_for_more": true or false, "words": the doctor's words, "area": the kind of thing asked for,
  "entries": [entry ids]}
- "volunteer": [] or [one entry id]
- "worry_disputed": true or false
- "worry_asked": true or false
- "reply": what you say to the doctor
