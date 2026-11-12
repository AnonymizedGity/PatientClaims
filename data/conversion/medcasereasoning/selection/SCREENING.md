# MedCaseReasoning test split: screening for dialogue simulation

Goal: choose test-split cases that suit our simulation and the common case schema
([case_schema.md](../../case_schema.md)). In the simulation an AI doctor interviews a
simulated patient, who answers only from the case's patient facts; the doctor can request vital
signs, examinations and tests, answered from the case's findings; the doctor then gives a diagnosis,
scored against the gold. So a good case has:

1. an adult patient who can tell their own story at presentation;
2. a real interview to conduct: several patient-reportable facts beyond the chief complaint;
3. objective data the doctor can request;
4. one presentation and its workup, so the diagnosis does not depend on what happened after
   treatment or weeks later;
5. a diagnosis an expert could reach from the case text, which the patient does not already know.

Input: `batches/batch_<n>.jsonl`, one case per line: `idx`, `test_index`, `pmcid`,
`final_diagnosis`, `diagnostic_reasoning`, `case_prompt`. Judge from `case_prompt`; use the gold
fields only to judge inferability and leakage. Do not look up the articles.

Output: `screen/batch_<n>.jsonl`, one JSON object per input case, same order, exactly these keys:

| Key | Values | Meaning |
|---|---|---|
| `idx` | int | copied |
| `pmcid` | str | copied |
| `age` | int or null | age at presentation |
| `sex` | `male`, `female`, null | |
| `specialty` | see list below | domain of the gold diagnosis |
| `setting` | `outpatient`, `emergency`, `inpatient_onset`, `referral` | where the presented episode starts. `inpatient_onset`: the problem starts during a hospital stay for something else. `referral`: transferred or referred with workup already done |
| `can_converse` | bool | the patient is alert and can give their own history at presentation (false for coma, intubation, severe confusion, history only from relatives) |
| `patient_facts` | int | distinct patient-reportable facts in the prompt: each symptom, each attribute (onset, duration, character, location, triggers…), each pertinent negative, each past illness, surgery, medication, allergy, family-history item, habit, exposure, social item |
| `objective_findings` | int | distinct requestable results: each vital sign, examination finding, lab test or panel, imaging study, ECG, endoscopy, pathology, genetic test |
| `time_structure` | `single_episode`, `staged_workup`, `course_dependent` | `single_episode`: history plus exams and tests at one presentation lead to the diagnosis. `staged_workup`: more tests over days or weeks of the same workup, each of which a doctor could order; no dependence on treatment response. `course_dependent`: the diagnosis relies on response to treatment, later deterioration, recurrence after discharge, surgery findings after a failed treatment, autopsy, or other events that cannot be framed as an orderable test |
| `leakage` | `none`, `test_result`, `history` | `test_result`: a test result names or nearly names the diagnosis (acceptable: it is the test's answer). `history`: the patient's own history, prior diagnosis or presentation names or nearly names it (e.g. "known X", a previous episode diagnosed as X, the diagnosis named in the referral) |
| `inferable` | `high`, `medium`, `low` | could an expert reach the gold diagnosis or an accepted synonym from the prompt? |
| `decisive_evidence` | `history`, `exam`, `lab`, `imaging`, `pathology`, `genetic`, `other` | what clinches the diagnosis |
| `label_issue` | str or null | problems with the gold label: vague, compound, a complication or finding rather than the disease, more specific than the evidence allows, or contradicted by the prompt |
| `image_dependence` | bool | key findings given only as a reference to a figure or image, without a text description |
| `verdict` | `include`, `maybe`, `exclude` | see rules |
| `reason` | str | one sentence: the main reason for the verdict |

Specialties: `cardiology`, `pulmonology`, `gastroenterology_hepatology`, `nephrology_urology`,
`endocrinology`, `hematology_oncology`, `infectious_disease`, `rheumatology_immunology`,
`neurology`, `psychiatry`, `dermatology`, `ent_dental_eye`, `obstetrics_gynecology`,
`surgery_trauma`, `toxicology`, `general_internal_medicine`, `other`.

Verdict rules:

- `exclude` if any of: `can_converse` false; `time_structure` = `course_dependent`;
  `leakage` = `history`; `inferable` = `low`; `patient_facts` < 5; `objective_findings` = 0;
  `image_dependence` true for the decisive finding.
- `include` if all of: `can_converse`; `patient_facts` >= 8; `objective_findings` >= 3;
  `time_structure` is `single_episode` or `staged_workup`; `inferable` is `high` or `medium`;
  `leakage` is `none` or `test_result`; `label_issue` null.
- `maybe` otherwise (e.g. 5–7 patient facts, a label issue, an inpatient onset where the patient can
  still talk).

Count facts honestly: "a 45-year-old man with fever and cough for 3 days" is 3 facts (fever,
cough, duration). Exam and test values do not count as patient facts.

Check your file with `python -I data/conversion/medcasereasoning/selection/check_screen.py <n>`.
