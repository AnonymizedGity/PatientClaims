# Second look at the included cases

The first screen ([SCREENING.md](SCREENING.md)) passed 205 of 493 test cases. This pass reads each
of them again with stricter questions, because the cases will be used for patient-persona
experiments: an AI doctor interviews a simulated patient (who answers only from the case's
patient facts), requests exams and tests (answered from the case's findings), and gives a diagnosis.
A good case needs a reliable patient, an interview that matters, and a gold label that is the right
answer to the presentation.

Input: `second_look/input_<n>.jsonl` (`idx`, `pmcid`, `final_diagnosis`, `diagnostic_reasoning`,
`case_prompt`, and `first_screen`, the first-pass fields). Read every `case_prompt` in full.

Output: `second_look/part_<n>.jsonl`, one JSON object per input case, same order, exactly these keys:

| Key | Values | Meaning |
|---|---|---|
| `idx` | int | copied |
| `pmcid` | str | copied |
| `reliable_historian` | bool | the patient can give a coherent, trustworthy account of their own illness at presentation. False for active psychosis or mania, intoxication, delirium, marked cognitive impairment, or a story told mainly by others |
| `interview_value` | `high`, `medium`, `low` | how much the history contributes. `high`: symptoms, timeline, exposures, medications, travel or family history carry key diagnostic clues. `medium`: the history frames the problem and directs testing, but tests decide. `low`: the history is little more than the presenting complaint and a list of earlier procedures or admissions; everything else is tests |
| `gold_fit` | `good`, `weak` | `weak` when the gold is not the right final answer to this presentation: a trivial or incidental finding, a complication when the case is about the underlying disease (or the reverse), narrower or broader than the case supports, or not the main problem of the case |
| `narrative_conclusion` | bool | the prompt contains a clinician's conclusion or impression, outside a test report, that names or nearly names the gold ("the constellation was suggestive of botulism"). Conversion will drop it; it does not exclude the case |
| `course_problem` | bool | the diagnosis needs events after the first presentation that a doctor could not order as a test (treatment response, later deterioration, findings that appear days later), missed by the first screen |
| `dx_key` | str | canonical short disease name, lower case, no abbreviations, singular, without "syndrome"/"disease" unless part of the name, so duplicates across cases match (`adult-onset still disease`, `cerebral salt wasting`, `histoplasmosis`) |
| `specialty` | see conventions | the specialty under the conventions below (may differ from the first screen) |
| `keep` | bool | `reliable_historian` and `interview_value` != `low` and `gold_fit` = `good` and not `course_problem` |
| `note` | str | one sentence: the main strength or the reason it is not kept |

Specialty values: `cardiology`, `pulmonology`, `gastroenterology_hepatology`, `nephrology_urology`,
`endocrinology`, `hematology_oncology`, `infectious_disease`, `rheumatology_immunology`,
`neurology`, `psychiatry`, `dermatology`, `ent_dental_eye`, `obstetrics_gynecology`,
`surgery_trauma`, `toxicology`, `general_internal_medicine`.

Conventions (so the same disease gets the same specialty everywhere):

- Tumours go to the organ: lung → pulmonology; GI tract, liver, pancreas → gastroenterology_hepatology;
  kidney, bladder, prostate, testis → nephrology_urology; uterus, cervix, ovary, breast →
  obstetrics_gynecology; skin → dermatology; brain, spinal cord, nerves → neurology; thyroid,
  pituitary, adrenal, neuroendocrine hormone syndromes → endocrinology; eye, ear, nose, throat,
  mouth, jaw → ent_dental_eye; bone and soft tissue → surgery_trauma. Blood cancers, histiocytic
  disorders and cancer of unknown primary → hematology_oncology.
- Infections → infectious_disease, except infections confined to the eye (→ ent_dental_eye).
- Disorders caused by a drug, toxin or envenomation → toxicology.
- Sarcoidosis, vasculitis, connective-tissue and autoinflammatory diseases → rheumatology_immunology.
- Electrolyte and acid–base disorders → nephrology_urology. Functional and somatic-symptom
  disorders → psychiatry.

Check your file with `python -I data/conversion/medcasereasoning/selection/check_second.py <n>`.
