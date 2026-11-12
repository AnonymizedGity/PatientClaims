# Common case schema (v1)

One format for every dataset used in the dialogue simulation (DDXPlus, MedQA-CS,
AgentClinic, MedCaseReasoning). It splits each case into three layers: what the
patient knows, what the clinical environment can show on the doctor's request,
and the evaluator-only gold.

Each dataset release has four JSONL files (one line per case, joined by
`case_id`) and a manifest:

| File | Who may read it |
|---|---|
| `<dataset>_patient.jsonl` | the patient simulator |
| `<dataset>_environment.jsonl` | deterministic environment, on the doctor's request |
| `<dataset>_gold.jsonl` | evaluator only |
| `<dataset>_qc.jsonl` | humans and audit tools only, never a conversational model |
| `manifest.json` | dataset-level settings (e.g. open or closed world) |

Validate with `python data/conversion/validate_cases.py <release_dir>`.

## Patient

```json
{"case_id": "medqa-cs-001", "dataset": "medqa_cs",
 "demographics": {"age": 46, "sex": "male"},
 "opening": ["f001"],
 "facts": [
  {"id": "f001", "item": "chest pain", "text": "I have chest pain.",
   "polarity": "present", "category": "symptom", "system": "cardiovascular", "time": "current"},
  {"id": "f003", "item": "chest pain: radiation", "parent": "f001", "attribute": "radiation",
   "value": ["neck", "upper back", "left arm"], "complete": true,
   "text": "It goes to my neck, my upper back and my left arm.",
   "polarity": "present", "category": "symptom", "system": "cardiovascular"},
  {"id": "f010", "item": "vomiting", "aliases": ["throwing up"], "text": "I haven't vomited.",
   "polarity": "absent", "category": "symptom", "system": "gastrointestinal"}
 ]}
```

| Field | Required | Meaning |
|---|---|---|
| `case_id`, `dataset` | yes | |
| `demographics` | yes | `age` (years, integer) and `sex` (`male`/`female`) |
| `opening` | yes | ids of the facts the patient states first (the chief complaint); all must be `present` |
| `facts[].id` | yes | case-local, stable: `f001`, `f002`, … |
| `facts[].item` | yes | what the fact is about, **without the answer**, in short lay-readable words (`vomiting`, `chest pain: onset`, `father's health`). Questions are matched to these. |
| `facts[].text` | yes | the answer in the patient's own voice (first person), keeping every qualifier from the source |
| `facts[].polarity` | yes | `present` or `absent`. A fact that is not listed is **unknown** (open world), unless the manifest declares a closed-world catalogue. |
| `facts[].category` | yes | `symptom`, `medical_history`, `medication`, `family_history`, `habit_exposure`, `social_background` (see below) |
| `facts[].system` | for symptoms | `general`, `cardiovascular`, `respiratory`, `gastrointestinal`, `genitourinary`, `reproductive`, `musculoskeletal`, `neurological`, `psychiatric`, `skin`, `ent`, `eye`, `endocrine`, `hematologic` |
| `facts[].parent`, `facts[].attribute` | for attributes of another fact | `parent` is the id of the finding it describes; `attribute` is one of `onset`, `duration`, `course`, `frequency`, `timing`, `severity`, `location`, `radiation`, `character`, `aggravating`, `relieving`, `context`, `quantity`, `appearance`, `treatment_response`, `other` |
| `facts[].value` | optional | typed value: a number (scales, counts), a string, or a list of strings |
| `facts[].scale` | with a numeric scale value | `[min, max]`, e.g. `[0, 10]`, so `"value": 3` is unambiguous |
| `facts[].key` | closed world: required; open world: optional | dataset-level item key shared across cases (the catalogue key in a closed world, e.g. `E_201`) |
| `facts[].complete` | optional, lists only | `true` = the list is exhaustive, so an unlisted value may be denied; otherwise unlisted values stay unknown |
| `facts[].time` | optional | `current`, `historical`, `recurrent`, `resolved`, relative to the encounter |
| `facts[].aliases` | optional | lay synonyms of `item` (`throwing up`, `heartburn`) |
| `facts[].pattern` | optional | `true` for a combined statement that must not be split ("worse lying down and better sitting up"); a "No" to it denies the combination, not each part |

Categories match the simulator's open questions:

- `symptom`: complaints, review of systems, and their attributes
- `medical_history`: past and chronic illnesses, surgeries, hospitalisations, allergies, OB/GYN history, sexual-health history (STIs), screening and vaccinations
- `medication`: current and past medicines, supplements, hormonal or device contraception (pill, patch, ring, IUD, implant, injection)
- `family_history`: relatives' health
- `habit_exposure`: tobacco, alcohol, drugs, caffeine, diet, exercise, sleep habits, sexual activity and non-hormonal contraception (condoms, withdrawal, a partner's vasectomy), travel, sick contacts, occupational and environmental exposures
- `social_background`: occupation, living situation, relationships, safety and abuse, stressors, the patient's own understanding and wishes

Writing rules:

- One fact = one answerable statement. Split mixed answers ("nauseated but didn't vomit" gives nausea `present` + vomiting `absent`).
- An `item` names a finding that can be present or absent, so that `polarity` answers a yes/no question about it. A normal state is that finding absent: "I have a good appetite" is item `loss of appetite`, `absent`, not item `appetite`, `present`.
- A child fact has its parent's `category` (and `system`). "Tylenol isn't working anymore" is a child of the Tylenol fact (`medication`, attribute `treatment_response`) or of the symptom it fails to relieve (`symptom`, attribute `relieving`).
- Polarity follows meaning, not wording: "I have no appetite" is `present`.
- Never turn a missing answer into `absent`.
- Attributes of a symptom are child facts with `parent`, not free text inside the parent.
- A zero on a symptom-intensity scale means the symptom is not there: write it `absent`, keeping `value: 0` and `scale` (e.g. itch 0/10 → "It doesn't itch."). Other scales keep `present` (pain localisation precision 0/10 means diffuse pain).
- A blanket denial ("no other symptoms", "no significant medical history") is one `absent` fact with a standard item: `other symptoms`, `other <scope>` (`other skin problems`, `other physical symptoms`), `chronic medical problems` (no history at all) or `other medical problems` (history with exceptions). It answers only the open question it summarises ("anything else?", "any medical problems?"), never a question about a specific finding: that stays unknown unless the record lists it.
- `opening` may include child facts when the chief complaint itself names the attribute ("severe chest pain" → the pain and its severity).
- `system` conventions: sleep complaints are `general`; breast complaints are `reproductive`.

Closed-world datasets only:

- `answered_by` (optional, patient record): `{catalogue key: [fact ids]}` for catalogue items whose default "No" contradicts the case's own positives. The listed facts answer the question instead. Example: sore throat → the pain facts that place the pain in the tonsils and pharynx; "cough?" → coughing up blood. An empty list makes the item unknown; use that only when no recorded fact answers the question. Give the reason in `qc.flags`.

## Environment

```json
{"case_id": "medqa-cs-001", "findings": [
  {"id": "x001", "kind": "vital", "name": "heart rate", "aliases": ["pulse"], "result": "90/min, regular", "initial": true},
  {"id": "x007", "kind": "exam", "system": "cardiovascular", "name": "heart auscultation",
   "result": "Regular rhythm; normal S1 and S2; no murmurs, rubs or gallops."}
]}
```

| Field | Required | Meaning |
|---|---|---|
| `findings[].id` | yes | case-local: `x001`, … |
| `findings[].kind` | yes | `vital`, `exam`, `test` |
| `findings[].name` | yes | what a doctor would request: one vital parameter, one examination step, or one test |
| `findings[].result` | yes | exactly what the doctor is told; `Result not documented` or `pending` when that is the source's state. A bedside examination returns the finding, not the examiner's interpretation ("positive: nystagmus on head turn", not "… suggestive of BPPV"); written reports (imaging, pathology, ECG) keep their conclusions. |
| `findings[].system` | for exams | same vocabulary as patient `system` |
| `findings[].aliases` | optional | other names for the request (`BP`, `pulse`, `CBC`) |
| `findings[].time` | optional | when the result applies (`on admission`, `hospital day 4`) for datasets with a hospital course |
| `findings[].initial` | optional | `true` = shown to the doctor at the start (OSCE door information) |

An empty `findings` list means the dataset has no objective data; the environment then reports every request as unavailable.

## Gold

```json
{"case_id": "medqa-cs-001", "diagnosis": "Myocardial ischemia or infarction",
 "aliases": ["myocardial infarction", "MI", "heart attack", "acute coronary syndrome"],
 "differential": [{"rank": 1, "diagnosis": "Myocardial ischemia or infarction",
                   "evidence": ["Pressure-like substernal chest pain"]},
                  {"rank": 2, "diagnosis": "Cocaine-induced myocardial ischemia"}]}
```

| Field | Required | Meaning |
|---|---|---|
| `diagnosis` | yes | the reference diagnosis (for differential-only sources, rank 1) |
| `aliases` | yes | names a scorer should accept as this diagnosis: synonyms, abbreviations, lay names, and more specific forms that fall entirely within it (e.g. `hepatitis A` for viral hepatitis). Never broader terms (`hypoglycemia` for insulin-induced hypoglycemia); leave partial credit to the judge. Exception: the everyday or current name clinicians use for this condition counts as a synonym (`pancreatic cancer` for pancreatic adenocarcinoma, `somatic symptom disorder` for somatization disorder). May be empty only if none exist. |
| `differential` | optional | ranked list: `rank`, `diagnosis`, optional `aliases`, optional `evidence` (source findings), optional `probability` (the source's score, e.g. DDXPlus) |
| `other_considerations` | optional | `[{diagnosis, note}]`, other diagnoses the source discusses |
| `reasoning` | optional | reference reasoning text (MedCaseReasoning) |

## QC

Everything needed to audit the conversion, kept away from the conversational models:

```json
{"case_id": "medqa-cs-001",
 "fact_sources": {"f001": ["cc"], "f002": ["medqa-cs-001-p001", "medqa-cs-001-p002"]},
 "quotes": {"f002": "Forty minutes ago."},
 "flags": {"f025": ["Only in the student note."]},
 "finding_sources": {"x007": {"source": "patient_note", "source_text": "Heart: Apical impulse not displaced; RRR; ..."}},
 "leakage": [],
 "source_issues": ["..."], "notes": ["..."],
 "extras": {"acting_notes": ["..."], "patient_questions": ["..."]}}
```

`extras` holds dataset material that some simulators may use but controlled
experiments must not receive by default (standardized-patient acting notes,
scripted patient questions).

## Manifest

```json
{"dataset": "medqa_cs", "schema": "case_schema v1", "world": "open", "cases": 35,
 "source": "...", "notes": "..."}
```

`world` is `open` (unlisted = unknown) or `closed`. For `closed`, `catalogue`
names the question catalogue whose unlisted items default to "No", and
`open_world_items` lists catalogue items excluded from that default (DDXPlus:
E_209, E_150).

## Catalogue (closed-world datasets)

`<dataset>_catalogue.json` describes every question the dataset records, so a
record-blind controller can map any doctor question to a key and code can
answer it, including the default "No":

```json
{"dataset": "ddxplus", "items": [
  {"key": "E_53", "item": "pain related to the reason for consulting", "aliases": ["hurt"],
   "category": "symptom", "system": "general", "value_type": "binary",
   "absent_text": "I don't have any pain."},
  {"key": "E_56", "item": "pain: intensity", "parent": "E_53", "attribute": "severity",
   "category": "symptom", "system": "general", "value_type": "scale", "scale": [0, 10]},
  {"key": "E_217", "item": "symptoms: worse lying down and better sitting up", "pattern": true,
   "category": "symptom", "system": "general", "value_type": "binary",
   "absent_text": "That pattern doesn't fit my symptoms."}
]}
```

| Field | Meaning |
|---|---|
| `key`, `item`, `aliases`, `category`, `system`, `parent`, `attribute`, `pattern` | as for patient facts |
| `question` | the source questionnaire wording (for reference; questions are matched to `item` and `aliases`) |
| `value_type` | `binary`, `scale`, `categorical` or `list` |
| `scale` | `[min, max]` for `scale` items |
| `options` | allowed values for `categorical` and `list` items: `{code: patient wording}` |
| `default` | the source's default value code (what an unrecorded item means) |
| `present_text` | first-person "Yes"; for `list`, `scale` and `categorical` items a template with `{values}`, `{value}` or `{n}`. Case facts carry the filled-in `text`. |
| `bands` | optional, `scale` items: `[{min, max, text}]` wording used instead of the number ("It came on slowly" for 0–3); the fact keeps the number in `value` |
| `absent_text` | how the patient says "No" when the item is not in the case record: a plain first-person negation that keeps the question's scope ("I don't cough up coloured sputum, or more sputum than usual", not "no sputum"; never "That pattern ... doesn't fit me", which readers invert) |
| `applies_to` | optional: `female` or `male` for items about one sex only (periods, pregnancy); for the other sex the item is not applicable |

Resolution of a catalogue item for one case:

0. The item has `applies_to` and the case's sex differs: **not applicable** (never a default "No").
1. The case lists a fact with this `key`: use the fact.
2. The key is in the case's `answered_by`: answer with the listed facts (an empty list = unknown).
3. The key is in the manifest's `open_world_items`: unknown.
4. The item's `parent` resolves to absent: **not applicable** (never unknown, never "No"). Example: pain location when there is no pain.
5. Otherwise: absent, worded with `absent_text`.
