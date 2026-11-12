# MedQA-CS: converting the annotation to the common case schema

Target format: [case_schema.md](../case_schema.md). Read it first.
Worked example: `bundles/medqa-cs-001.json`. Compare it with its inputs,
`source/medqa-cs-001.json` and `annotations/medqa-cs-001.json`.

The annotation made under [GUIDE.md](GUIDE.md) is called "v1" below and in the bundles' notes.

## Inputs per case

- `annotations/<case>.json`: the **validated v1 annotation**. Its clinical
  decisions were checked and reviewed: polarity (`assertion`), temporality,
  coverage of every source answer, source issues, flags, leakage and the
  June-2024 confirmations. Keep them unless one is clearly wrong; if you change
  one, say why in `qc.notes`.
- `source/<case>.json`: the source inventory (Q/A script, doorway vitals, SP
  notes, student note, exam lines, gold). Use it for wording and for checking.

## Output per case

`bundles/<case>.json` = `{"patient": …, "environment": …, "gold": …, "qc": …}`, each
part exactly as in the schema. Then both of these must print OK:

```
python -I data/conversion/validate_cases.py --bundles data/conversion/medqa_cs/bundles <case>
python -I data/conversion/medqa_cs/check_coverage.py <case>
```

Treat every warning as a question to answer. Fix it, or justify it in `qc.notes`.

## Patient facts

- **`item`** is a short, answer-free label for what the fact is about. Start
  from the source topic and question, then:
  - split questions that cover several items ("nausea or vomiting" gives `nausea` + `vomiting`);
  - name children as `<parent item>: <aspect>` (`chest pain: severity`, `smoking: how much`);
  - use the patient's everyday words where natural (`high blood pressure`, `stomach pain`);
  - never put the answer in the label (`blood in urine: color`, not `bright red blood`).
- **`text`** is the answer in the first person, as the patient would say it.
  Keep every qualifier: numbers, durations, frequency words, "sometimes", "a little",
  sides, lists. Don't use clinical words the patient didn't use ("hematuria",
  "dysuria"); they belong in `aliases` if anywhere. A diagnosis the patient was
  told about may be named. Remove stage directions; they go in `qc.extras.acting_notes`.
- **One fact = one answerable statement.** Split mixed answers. Do not merge
  different items into one fact. Do not create two facts that say the same thing.
- **Attributes as children.** Onset, duration, course, frequency, timing,
  severity, location, radiation, character, aggravating, relieving, context,
  quantity, appearance, treatment_response and other become separate facts with
  `parent` + `attribute`. This applies to symptoms, to earlier episodes (a
  parent fact "earlier episodes of …") and to habits (smoking amount and duration,
  last drug use).
- **`value`** only for a clean number (a 0–10 score, a count) or a list
  (locations, triggers). **`complete: true`** only when the list fully answers
  an open question ("where does it go?" with the whole list).
- **`polarity`**: copy from v1 (`assertion`). Meaning, not wording, decides.
- **`category`** from the v1 `subtype`:

  | v1 subtype | category |
  |---|---|
  | hpi, ros | `symptom` |
  | pmh, psh, allergies, ob_gyn, preventive | `medical_history` |
  | medications, hormonal or device contraception | `medication` |
  | family | `family_history` |
  | tobacco, alcohol, drugs, caffeine, diet, exercise, sleep habits, sexual activity, condoms/withdrawal/partner's vasectomy, travel, exposures | `habit_exposure` |
  | occupation, living situation, relationships, safety/abuse, stressors, concerns, plans | `social_background` |

  A v1 `social` or `other` fact goes to `habit_exposure` or
  `social_background` by its content. Functional limits ("can't climb stairs")
  are `symptom`.
- **`system`** for every `symptom` fact, children included (use the parent's system).
- **`time`**: copy v1 temporality (`current`, `historical`, `recurrent`,
  `resolved`); omit it when v1 says `unclear`.
- **`aliases`**: 0–3 everyday synonyms where a doctor or patient might use other
  words. Don't pad.
- **`opening`**: the fact id(s) of the chief complaint. Use the visit reason
  when the chief-complaint answer is not a complaint, as v1 does.
- Fact ids `f001…` in a sensible interview order: complaint, its attributes,
  associated symptoms, earlier episodes, history, medications, family, habits, social.

## Environment

- **Vital signs**: one record per parameter (blood pressure, heart rate,
  respiratory rate, temperature, oxygen saturation, weight/BMI if given).
  Doorway vitals get `"initial": true`. If the note's exam repeats a parameter
  with the same value, cite both sources in one record. If it gives a
  different value, keep the doorway record and add `"<parameter> on recheck"`
  from the note, plus a source issue. Note-only vitals (e.g. "VS: WNL") become
  `name: "vital signs"` with result `Within normal limits`.
- **Exams**: one record per thing a doctor would ask to examine. Usually that is
  one body region or system: general appearance, eyes, ears, nose and throat,
  neck, lungs, heart, abdomen, back, extremities, skin, a specific joint. Split
  the neurological exam into mental status, cranial nerves, motor strength,
  sensation, reflexes, coordination and gait. Named special tests (Murphy,
  McBurney, Rovsing, psoas, straight-leg raise, Spurling, Lhermitte, Romberg,
  Dix-Hallpike, Weber, Rinne, Babinski, Homans, Kernig/Brudzinski) each get
  their own record.
- **`result`**: exactly what the doctor is told, in plain clinical English with
  abbreviations expanded. Keep v1's decisions on damaged source text
  (near-certain correction, `Result not documented`, or the source wording for
  an implausible but explicit statement). Doubts go in `qc.finding_flags`,
  never in `result`.
- **SP-simulated findings** (the actor is told to show tenderness, pain on
  movement…) are part of the result of the matching exam record. When the
  student note's exam contradicts the actor's simulated finding, the simulated
  finding wins, because it is what the examinee would find. Record the conflict in
  `qc.source_issues`. Pure behavior (looks anxious, coughs, refuses eye
  contact) stays in `qc.extras.acting_notes`, unless the note's exam also
  records it as a finding.
- `kind: "test"` only for actual results. MedQA-CS usually has none, and a
  planned workup is not a result.

## Gold

- `diagnosis`: rank-1 diagnosis from v1 (source wording).
- `aliases`: standard synonyms, abbreviations and common lay names that a scorer
  should accept (usually 3–10). Don't include broader or different diagnoses.
- `differential`: v1 ranks; `evidence` = v1 history findings, then exam
  findings prefixed "Exam: "; add `aliases` for ranks 2–3 as well.
- `other_considerations`: v1 `additional_considerations` as `{diagnosis, note}`.

## QC

- `fact_sources`: v1 source ids (full ids, `cc`, `note`) for every new fact.
- `quotes`: the v1 quote for each fact (shortest exact supporting fragment; join several with " / ").
- `flags`: v1 flags, re-keyed to the new fact ids, plus any new doubts.
- `finding_sources`: `{source, source_text, exam_ids}` per finding, where
  `source` is `doorway`, `patient_note`, `sp_notes`, or a combination joined with " + ".
- `finding_flags`: doubts about findings, keyed by finding id.
- `leakage`: v1 leakage entries re-keyed to the new fact ids (`[]` if none).
- `source_issues`, `notes`: v1 `source_issues` and `annotator_notes`, plus any conversion notes.
- `extras`: `acting_notes` and `patient_questions` from v1 `persona`, plus the
  stage directions you removed.
- `excluded_sources`, `excluded_exam_lines`: v1 exclusions as `[{id, reason}]`.
