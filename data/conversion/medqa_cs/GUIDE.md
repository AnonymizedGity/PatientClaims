# MedQA-CS annotation guide

Goal: turn each adult MedQA-CS OSCE case into three access-separated parts for a
doctor–patient dialogue simulation:

- **patient** — what the standardized patient (SP) knows and can say;
- **clinical environment** — objective findings the doctor gets only by examining;
- **gold** — the examiner's differential, for the evaluator only.

Read the whole guide and the worked example `annotations/medqa-cs-001.json` before starting.

## Inputs and outputs

- Input per case: `source/medqa-cs-XXX.json` (built deterministically from
  `data/raw/medqa_cs/`). Fields:
  - `chief_complaint` — the opening Q/A.
  - `qa[]` — ordered Q/A pairs with fixed ids `medqa-cs-XXX-pNNN`.
  - `doorway_vital_signs` — vitals given before the encounter.
  - `sp_notes`, `challenging_questions` — SP acting sheet.
  - `patient_note_history` — the model student note (HPI/ROS/PMH/SH/FH).
  - `exam_lines[]` — the note's physical-exam lines, ids `medqa-cs-XXX-eNNN`.
  - `gold_target`, `gold_additional_diagnosis` — examiner key.
  - `raw_opening` — the full raw sheet, for checking only.
- Output per case: `annotations/medqa-cs-XXX.json` — UTF-8, 2-space indent,
  schema below.
- Check: `python -I validate.py medqa-cs-XXX` must print OK. Treat every warning
  as a question to answer, not something to silence.
- Never use the `output` / model-prediction fields of the raw JSON.

## Schema

```json
{
  "case_id": "medqa-cs-001",
  "demographics": {"name": "Joseph Shorr", "age": 46, "sex": "male", "setting": "emergency department"},
  "opening_fact": {"text": "I have chest pain.", "source_ids": ["cc"]},
  "patient_facts": [
    {"id": "medqa-cs-001-f001", "source_ids": ["medqa-cs-001-p001"],
     "category": "symptoms", "subtype": "hpi", "assertion": "present", "temporality": "current",
     "text": "Chest pain began 40 minutes ago.", "quote": "Forty minutes ago."}
  ],
  "excluded_source_ids": [],
  "persona": {"acting_notes": ["..."], "patient_questions": ["..."]},
  "clinical_environment": {
    "vital_signs": [{"id": "v001", "source": "doorway", "name": "Blood pressure", "finding": "165/85 mm Hg", "source_text": "BP: 165/85 mm Hg"}],
    "physical_examination": [{"id": "x001", "source": "patient_note", "exam_ids": ["medqa-cs-001-e003"], "system": "Neck", "name": "Jugular veins", "finding": "No jugular venous distension", "source_text": "Neck: No ND, no bruits."}],
    "investigations": []
  },
  "excluded_exam_ids": [],
  "gold": {
    "differential": [{"rank": 1, "diagnosis": "Myocardial ischemia or infarction", "history_findings": ["..."], "exam_findings": []}],
    "additional_considerations": [{"diagnosis": "Aortic dissection", "rationale": "..."}],
    "leakage_check": "none"
  },
  "qc": {"source_issues": ["..."], "annotator_notes": ["..."]}
}
```

### Patient facts

One record = one atomic clinical statement.

- `category`: `symptoms` (anything about the presenting problem and current or
  recent symptoms, including review of systems) or `history_and_exposures`
  (everything else: PMH, PSH, meds, allergies, family, social, sexual, OB/GYN,
  exposures, travel, prevention, the patient's concerns and plans).
- `subtype`: one of `hpi, ros, pmh, psh, medications, allergies, family,
  social, sexual, ob_gyn, exposures, preventive, functional, concerns, other`.
- `assertion`: `present` or `absent`. There is **no separate negatives list**;
  polarity is this field.
- `temporality`: relative to **the encounter (the OSCE visit)**: `current`
  (true now, including chronic conditions still active or treated), `recurrent`
  (repeating episodes), `historical` (a past event or past state), `resolved`
  (was present, explicitly over now), `unclear`.
- `text`: concise third-person clinical statement in English. No "Patient
  reports …" boilerplate. Keep every qualifier the source gives: duration,
  onset, frequency, severity, location, radiation, quality, triggers, relief,
  quantities, ages, dates.
- `quote`: the verbatim answer fragment that supports the fact (shortest exact
  substring that carries it).
- `source_ids`: the `pNNN` ids it comes from, `cc` for the chief complaint, or
  `note` for a fact found only in `patient_note_history`. Several ids are fine
  when a fact needs several answers.
- `from_note: true` is required when `note` is a source.
- Optional `flags: [..]` for anything a reviewer should look at.

## Rules

1. **Coverage.** Every `qa` id must appear in at least one fact. Do not use
   "unclassified". If an answer really carries no clinical content, list it in
   `excluded_source_ids` with a reason. This should be very rare.
2. **Polarity by meaning, not by words.** `absent` means a clinical item is
   stated to be not there (denied symptom, no allergy, never had surgery, no
   family history of X, does not smoke). Sentences that contain "no/not/never"
   but describe something that *is* there are `present`:
   - "I have no appetite" → anorexia, **present**;
   - "I don't feel like eating because of the nausea" → present;
   - "Benadryl used to help, but not anymore" → present (treatment no longer
     effective);
   - "Not very severe" (earlier episodes) → present severity attribute;
   - "I always cheat on the diet" / "not very compliant" → present;
   - "I haven't had sex for 3 months because of the pain" → present
     (pain-related avoidance);
   - "I didn't call the police because I was embarrassed" → present context
     fact, category `history_and_exposures`, subtype `other`.
3. **Split mixed answers.** "I feel nauseated, but I didn't vomit" gives nausea
   present + vomiting absent. A list of denials ("No. Cough, wheezing, stomach
   pain.") gives one absent fact per item.
4. **Do not drop qualifiers.** "Two bowel movements a week for the past 6
   months" must keep "for the past 6 months". "Cough for several years" must
   end up in the cough's symptom facts.
5. **Temporality must make sense at the visit.** Hypertension on a diuretic is
   `current` even though it was diagnosed years ago. Laxatives stopped when the
   diarrhea started are `resolved`. A quit-smoking history is `resolved` for
   current smoking plus `historical` for pack-years. Family history is
   `historical` unless it is an ongoing condition of a living relative
   (`current`).
6. **Don't invent; flag source errors.** If an answer does not fit its question
   (case 004 p026: surgery question answered "No medications."), record only
   what the patient literally said. You may resolve it from
   `patient_note_history` (e.g. "PSH: none") with `source_ids: ["...p026",
   "note"]`, `from_note: true` and a `flags` entry. Always add a
   `qc.source_issues` entry.
7. **Patient note as backup.** Use `patient_note_history` to resolve ambiguity.
   Add a fact that exists only there when it is something the patient would
   know (`source_ids: ["note"]`, `from_note: true`). Never copy clinician
   interpretations or diagnoses from the note into patient facts.
8. **Patient voice only.** Patient facts are what the SP can report. No exam
   findings, no measured values the patient would not know, no clinical labels
   the patient would not use unless the patient said them (a diagnosis the
   patient was given before is fine: "told he had infectious mononucleosis").
9. **Opening fact** = the chief-complaint answer, in the patient's words, with
   stage directions removed. "(holds chest, left side)" moves to
   `persona.acting_notes`. If the chief-complaint answer is not a complaint
   (e.g. "No." for a check-up), use the visit reason from `opening_scenario`
   and say so in `annotator_notes`.
10. **Persona.** `acting_notes`: behavior and stage directions from `sp_notes`
    and the script. `patient_questions`: the challenging questions plus scripted
    questions the SP asks ("What's an ECG?"). Keep the SP's wording.

### Clinical environment

- One atomic finding per record. `system` = the body-system label from the line
  (HEENT, Neck, Chest, Heart, Abdomen, Extremities, Neuro, Skin, General, …).
  `name` = what was examined or measured. `finding` = the result in plain
  clinical English (expand abbreviations: ND/JVD → jugular venous distension,
  RRR → regular rate and rhythm, BS → bowel sounds, WNL → within normal limits).
- `vital_signs`: one record per parameter. Include **all doorway vitals**
  (`source: "doorway"`, ids `v001…`) **and** any vitals in the note's exam
  (`source: "patient_note"` with `exam_ids`). Keep both even when they repeat or
  disagree, and note disagreements in `qc.source_issues`. "VS: WNL" is one
  record: name "Vital signs", finding "Within normal limits".
- `physical_examination`: ids `x001…`. Every `exam_lines` id must be covered.
- **`finding` is exactly what the simulated doctor is told.** Commentary
  ("OCR artifact", "recorded as", "side not stated") goes in a `flags` list
  on the record and in `qc.source_issues`, never in `finding`.
- **Damaged or unclear source:**
  - A near-certain correction ('@ BS x 4' → bowel sounds present in all four
    quadrants) is written as the corrected finding and explained in `flags`.
  - An unreadable result, or one with no stated direction ("Babinski sign
    bilaterally", "8 Dix-Hallpike"), becomes exactly `Result not documented`,
    with the explanation in `flags`. Never guess "present" or "absent".
  - An explicit but implausible statement ("Babinski sign present
    bilaterally" next to an otherwise normal neuro exam) keeps the source
    wording, and the doubt goes in `flags`.
- **SP-simulated findings.** If `sp_notes` tells the SP to show a finding on
  examination ("Show pain when the examinee checks for CVA tenderness on the
  right", "Pretend to have LUQ tenderness"), add a physical-examination record
  with `source: "sp_notes"` and no `exam_ids`, even if the note's exam also has
  it.
- `investigations`: test results only (labs, imaging, ECG, …). MedQA-CS notes
  rarely contain results. Planned workup is **not** a result; leave it out.
  Usually this list is empty.

### Gold

- `differential`: the examiner's ranked diagnoses from `gold_target`. Keep the
  source diagnosis wording, cleaning only text artifacts (e.g. "Physical &am
  Finding(s)"). `history_findings` / `exam_findings` are lists of the source's
  supporting bullets; drop "N/A".
- `additional_considerations`: one record per diagnosis in
  `gold_additional_diagnosis`, with its rationale shortened to one or two
  sentences.
- `leakage_check`: `"none"`, or a list of patient-fact ids whose text names or
  clearly gives away a gold diagnosis, with a short reason. Legitimate history
  (e.g. "father died of colon cancer") is not leakage, but list it if it names
  the rank-1 diagnosis.

### QC

- `source_issues`: every problem in the source you noticed: answers that don't
  match their questions, contradictions between the script and the note,
  missing vitals, typos that change meaning, ambiguous findings, and gold
  evidence that the patient script does not support.
- `annotator_notes`: decisions a reviewer should know about.

## Style

- English for all `text`/`finding` values. Keep drug names and numbers exact.
- Prefer several small facts over one long one. Do not create two facts that say
  the same thing (paraphrase duplicates). When one answer supports a fact that
  another answer already gave, add its id to the existing fact's `source_ids`.
- Fact ids `f001…` in order of appearance; environment ids `v001…`, `x001…`,
  `i001…`.
