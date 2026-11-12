# MedCaseReasoning (test split) → common case schema

Target format: [case_schema.md](../case_schema.md). Read it fully first.
Worked example: `bundles/mcr-test-03768.json`, built from `source/mcr-test-03768.json`.
The AgentClinic rules ([../agentclinic/CONVERSION.md](../agentclinic/CONVERSION.md))
apply wherever this file does not say otherwise; read its Patient facts and Environment sections.

Each case is a published case report condensed into one narrative (`case_prompt`). The source file
(`source/<case>.json`) splits it into numbered sentences `s001…`, and gives `final_diagnosis`,
`diagnostic_reasoning` and `selection` (screening notes, including `narrative_conclusion` and
`leakage`). Nothing else from the article is used.

Output: `bundles/<case>.json` = `{"patient", "environment", "gold", "qc"}`, `dataset`
`"medcasereasoning"`. Both must print OK:

```
python -I data/conversion/validate_cases.py --bundles data/conversion/medcasereasoning/bundles <case>
python -I data/conversion/medcasereasoning/check_coverage.py <case>
```

Treat every warning as a question: fix it, or justify it in `qc.notes`.

## The index visit (time cut)

The simulated encounter is one visit: the presentation the case opens with (the "index visit").
Write `qc.notes` entry `"Index visit: …"` saying which visit it is.

- **Patient facts** are what the patient experienced or was told up to and at the index visit:
  symptoms and their attributes, earlier illnesses and diagnoses they were given, earlier visits and
  treatments ("my GP gave me antibiotics and they didn't help"), medications, allergies, family
  history, habits, exposures, travel, occupation and social facts.
- **Findings** are every vital sign, examination and test result in the prompt, including tests done
  days or weeks later in the same workup, and results from before the index visit. Give `time` to
  any finding not from the index visit (`"hospital day 3"`, `"2 weeks later"`, `"2 years before
  presentation"`). If the patient was told what an earlier test showed, that diagnosis is also a
  `medical_history` fact.
- **Later examinations** in the same workup (a repeat neurological examination hours or days
  later, an eye examination on day 9, an orthostatic test on day 6) are findings with `time`,
  including when they show the illness progressing.
- **Not part of the case:** treatment given during the workup, the response to it, ICU
  interventions (intubation), therapeutic procedures and outcomes. List those sentences (or say
  which part of a mixed sentence) in `qc.excluded_sentences` / `qc.notes`.
- **Vital signs given only in words** ("vital signs were normal / stable"): one record per
  standard parameter (temperature, blood pressure, heart rate, respiratory rate) with that word;
  no oxygen saturation unless the source mentions it.
- **Blanket results** ("rest of the examination unremarkable", "routine laboratory tests within
  normal limits") are one record whose `name` states the scope ("rest of the physical
  examination", "routine laboratory tests"), so the doctor sees what the source actually said.
- **Symptoms that start after the index visit** are not facts (exclude with a reason). If the
  selection note says the case is best framed at a later visit, use that visit as the index and say
  so in the "Index visit" note.
- Tests mentioned without a result ("cultures were obtained", "a biopsy was performed") are not
  findings; mention them in `qc.notes`.

## Clinician reasoning in the narrative

Sentences that interpret rather than report ("the constellation was suggestive of X", "the
differential included…", "X was considered", "presumed X and treated") are not findings and not
facts: exclude them with a reason. When a sentence mixes a result and an interpretation, the finding
keeps the result and drops the interpretation, except inside a written report (a radiology or
pathology impression keeps its conclusion; list it in `qc.leakage` if it names the gold).
`selection.narrative_conclusion` true means at least one such sentence names the diagnosis.

## Patient facts

As in AgentClinic: one answerable statement per fact, first person, lay words with clinical terms
in `aliases`, every qualifier kept, `polarity` by meaning, attributes as child facts with the
parent's category and system, blanket denials with the standard items (`other symptoms`,
`chronic medical problems`, `other medical problems`).

- **Signs the patient can notice** (drooping eyelids, slurred speech, a lump, a rash, yellow eyes,
  weak arms) are facts in the patient's words *and* stay in the examination finding with the
  examiner's measurement. Signs only an examiner can find (reflexes, murmurs, 4/5 strength,
  tachycardia, organ size) are findings only.
- **Explicit negatives** in the prompt ("denied", "no history of", "no fever") are `absent` facts;
  examination negatives stay in the finding text.
- **Collateral history** ("his wife reported…") becomes "My wife says…".
- `demographics`: age and sex only. Ethnicity, country of origin, pregnancy status, occupation and
  living situation are facts.
- `opening`: the facts of the presenting complaint of the index visit.
- **"Progressive" (or a duration) in front of a list of symptoms** applies to all of them: one
  standalone fact ("These have all been getting worse."), not a child of the first symptom.
- **Scope-level denials** ("denied neurological symptoms", "no GI complaints") are blanket
  denials: item `other <scope> symptoms`, no aliases naming specific symptoms.
- A diagnosis name in a fact only when the patient was told it (an earlier diagnosis); otherwise
  describe the experience. Any gold word left in a fact goes in `qc.leakage` with the reason.

## Environment

As in AgentClinic: one `vital` record per parameter; examinations grouped by region (inspection,
palpation, percussion, auscultation in one record), neurological components separate, named
special tests separate; one record per orderable test.

- Group a panel when two or more of its members are reported: complete blood count, metabolic
  panel / electrolytes, liver function tests, coagulation, lipid panel, thyroid function,
  urinalysis, arterial blood gas, cardiac enzymes, iron studies, CSF analysis (cell count, protein,
  glucose), autoimmune serology, viral serology. Members go in the `result` ("hemoglobin 8.3 g/dL;
  WBC 81,000/mm3") and in `aliases`.
- Imaging: one record per study. Pathology: one per specimen. ECG, EEG, EMG/nerve conduction,
  echocardiography, endoscopy: one each. Cultures: one per specimen type.
- `result`: exactly what the doctor is told, the source's values and wording, no review commentary
  (that goes in `qc.finding_flags`). "Unremarkable" stays "Unremarkable".
- `name` must not reveal the diagnosis. A bedside examination returns the finding, not the
  interpretation; written reports keep their conclusions. A result naming the gold goes in
  `qc.leakage`.
- No `initial` (nothing is shown at the door).

## Gold

- `diagnosis`: the source `final_diagnosis`, cleaned only for readability (`CerebralSaltWasting` →
  `Cerebral salt wasting`, capitalisation, obvious typos).
- `aliases`: per the schema (synonyms, abbreviations, everyday names, more specific forms; never
  broader terms except the everyday or current clinical name).
- `reasoning`: the source `diagnostic_reasoning`, verbatim.
- No `differential`.

## QC

- `fact_sources`: `{fact id: [sentence ids]}` for every fact.
- `finding_sources`: `{finding id: {"sentences": [sentence ids], "source_text": "<exact text>"}}`;
  `source_text` is the exact supporting text (several parts joined with `" / "`).
- `quotes`: shortest exact supporting text for facts with numbers, qualifiers or wording that
  could be disputed.
- `excluded_sentences`: `[{"id", "reason"}]` for sentences that support nothing.
- Every sentence must be cited by a fact or finding, or excluded.
- `flags`, `finding_flags`, `leakage` (`[{"fact_id" or "id", "reason"}]`), `source_issues`,
  `notes` (with the "Index visit" note), `extras` (`{}` unless needed).

## Harmonisation

After all batches pass, `scan.py` lists cross-case inconsistencies and `harmonize.py` applies the
reviewed edits (blanket-denial labels, shared "progressive" attributes, vital signs given only in
words, everyday gold names). Then `build_release.py` writes `release/`.
