**Class and entries.** For each part, decide first whether the record answers it (its class), then list the entries
that answer it.
- The test for an entry: hearing only that entry, would the doctor know the answer to exactly this question? It must
  be about the same thing, the same person and the same time. Implication counts: "it's the same all day" answers
  "is it worse at night?".
- Close is not enough. An entry about a different symptom, another place in the body, another person (the family
  instead of the patient), another purpose (a medicine taken for something else) or another side of the same symptom
  (how it began, when the question is how long it has lasted) does not answer the part. If no entry passes the test,
  the part is not recorded and gets its fixed phrase. Putting a close entry in its place is a mistake.
- A question about a whole area ("any medicines?", "any medical problems?") is answered by the entries saying what
  the patient does have there, or by an entry that is itself a general "no", never by a list of particular "no"s. A
  question narrowed to one thing ("medicines for your heart", "pain in your back") is not about a whole area: only
  entries about that one thing answer it.
- An open question gets the entries of its area not told yet, besides those its examples already took. Look through
  the whole record for them: an open question about symptoms gets every symptom not told yet.
- Answer at the level asked. Whether the patient has something, or where it is, is answered by the entries that say
  so; a symptom's details (its indented entries: how bad, what makes it better or worse, and so on) only when the
  doctor asks about them. For "any other symptoms", the other symptoms themselves, not their details.
- A "no" is said once. When the patient does not have what a part asks about, list the one entry closest to the
  doctor's words, not every recorded "no" near it: a real patient answers "no" once, not item by item. A whole area
  in which the patient has nothing is general_no.
- A part asked again gets its entries again.
- In a closed record, a checklist question is answered by the patient's own entries, by a checklist id listed under
  "answered by" (that id stands for the entries named there), or by its recorded "no". Something that is not on the
  checklist is not recorded, even when a checklist item about something nearby exists.

The classes:
- from_record: at least one entry passes the test; list them all, but only one "no";
- unrecorded_presence: it asks whether the patient has a symptom or finding, and no entry says;
- unrecorded_detail: it asks a detail of a symptom the patient has, and no entry says;
- unrecorded_background: it asks about past health, family, medicines, habits or exposures, and no entry says;
- unrecorded_social: it asks about the patient's living situation, work, relationships or daily life, and no entry
  says;
- general_no: a closed record only: a question about a whole area (for example "any medicines?") in which the patient
  has nothing, so every checklist item there is a recorded "no"; the answer is a plain general "no". Never for a
  particular thing, which has its own entry or is not recorded;
- nothing_more_to_add: an open question whose area has been told completely already;
- no_health_answer_needed: not a question about the patient's health (a greeting, an explanation, a comment, a
  question about the patient's worry or opinion, unless a recorded view of the cause answers it).
A part that is not from_record lists no entries.

**Volunteer.** At most one entry, not told yet and not asked, that a real patient would naturally add to this reply
because it is closely tied to what was asked. Usually there is none: leave it empty unless adding it is clearly
natural. A view of the cause is never volunteered.
