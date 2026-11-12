# MedCaseReasoning test-split selection

Goal: test-split cases that suit the dialogue simulation and the common case schema
([case_schema.md](../../case_schema.md)).

| Step | Cases | How |
|---|---:|---|
| Test split | 897 | raw `test.parquet` |
| Adult candidate pool | 493 | the screen in `data/conversion/pools/medcasereasoning` (adult, encounter-like, no gold in prompt, single label) |
| First screen | 205 include, 91 maybe, 197 exclude | [SCREENING.md](SCREENING.md): five agents read every prompt; rule-based verdict (`check_screen.py`) |
| Second look | 128 kept of 205 | [SECOND_LOOK.md](SECOND_LOOK.md): reliable historian, interview value, gold fit, course problems; specialty and diagnosis keys normalised |
| Reviewer drops | 125 | inpatient onset (292); 175 and 234 after reading the medium-inferability picks (`select.py`) |
| Selected | 100 | `select.py 100`: round-robin over specialties by score, one case per disease |

`selected.json` holds the 100 cases with `idx`, `test_index` = the dataset's own index (the `Unnamed: 0` column of
`test.parquet`, used in the case ids `mcr-test-<index>`), `pmcid`, the screening scores and notes.

For conversion: cases with `narrative_conclusion` true contain a clinician's sentence naming the
diagnosis outside a test report; drop it. Cases with `leakage` = `test_result` have a test whose
result names the diagnosis; keep it as that test's answer and list it in `qc.leakage`.
