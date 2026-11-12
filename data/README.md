# Data

The 384 study cases come from four public datasets, converted into one case schema (`conversion/case_schema.md`):
demographics, recorded facts in the patient's own words, the opening complaint, examination and test findings, and
the correct diagnosis with aliases.

| Dataset | Cases | Release version |
|---|---|---|
| AgentClinic-MedQA Extended | 149 | 0669657c4f05 |
| DDXPlus | 100 (of 3,875 in the release) | ce9a684fa350 |
| MedCaseReasoning | 100 | 3172e8076188 |
| MedQA-CS | 35 | 216669d727b9 |

A release version is the first 12 hex digits of the SHA-256 of the release's `<dataset>_patient.jsonl`. The simulator
records it in every dialogue.

## Sources

The converted cases are modified versions of these datasets. Please cite them and respect their terms.

| Dataset | Raw data used | Where |
|---|---|---|
| AgentClinic-MedQA Extended (Schmidgall et al.; MIT), built from MedQA (Jin et al.; MIT) | `agentclinic_medqa_extended.jsonl` at commit `07f869a` of 17 August 2024 (sha256 `54a024eb…`; the file changed later) | https://github.com/SamuelSchmidgall/AgentClinic/blob/07f869a329681e32eca0bdf221041dba5cfbe9b8/agentclinic_medqa_extended.jsonl, https://github.com/jind11/MedQA |
| DDXPlus (Fansi Tchango et al., 2022; CC BY 4.0) | English release, `release_test_patients.zip` with `release_evidences.json` and `release_conditions.json` | https://doi.org/10.6084/m9.figshare.22687585.v2, https://github.com/mila-iqia/ddxplus |
| MedCaseReasoning (Wu et al., 2025) | test split, `test.parquet` (revision `469a5365…`); the cases are PMC open-access case reports, whose PMCIDs are in `conversion/medcasereasoning/selection/selected.json` | https://huggingface.co/datasets/zou-lab/MedCaseReasoning |
| MedQA-CS (Yao et al., 2026; CC BY-NC 4.0) | `med-student.json` at Hugging Face revision `aee9bba` of 27 September 2024 (sha256 `f7d9da92…`), and the earlier version at revision `44b09d9` of 12 June 2024 (sha256 `dbe9d8ec…`) to resolve the later one's template answers | https://huggingface.co/datasets/bio-nlp-umass/MedQA-CS-Student, https://github.com/bio-nlp/MedQA-CS |

The full checksums of the AgentClinic, DDXPlus and MedCaseReasoning raw files are in
`conversion/pools/<dataset>/manifest.json`. To rebuild from raw data, put the files under `data/raw/<dataset>/` (paths
in each `build_source_inventory.py`; the June 2024 MedQA-CS file goes under `data/raw/medqa_cs_2024-06/`).

## Files

This folder has the layout the simulator reads (`--eval-dir data`, see `simulator/README.md`).

| Path | What it is |
|---|---|
| `main/cases.json` | The 384 cases by dataset, whether they are anchored, and the release versions. |
| `anchors/<dataset>.json` | X for each of the 362 anchored cases: the wrong diagnosis, the lay phrase the patient says, and the terms the scorer matches. |
| `gold/<dataset>.jsonl` | The correct diagnosis and its aliases for each study case (what the scorer matches). |
| `conditions/<dataset>.json` | Per-case picks made once before the runs: the diagnostic fact, the fact fitting X, and the opening blocks. |
| `tests/<dataset>.json` | Each vital-sign, examination and test finding labelled names / confirms / other against the correct diagnosis; only "other" is shown to the doctor. |
| `data/releases/` | The four converted releases the simulator reads (patient, environment, gold, manifest; for DDXPlus also the question catalogue). |
| `openings/` | The cached patient openings the runs used: 3,411 files (the opening of each case and seed, and the 3- and 5-block openings), named by the simulator's cache key. |
| `tools/score.py` | The diagnosis matcher that the finding labels use (`simulator/sim/compile_tests.py` imports it). Dialogues are scored with `scoring/score.py`, which matches diagnoses the same way. |
| `conversion/` | The conversion pipeline (below). |

## How the releases were made (`conversion/`)

1. **Pools** (`conversion/pools/`): fixed selections from each dataset (DDXPlus: adult test patients after removing
   near-duplicate symptom profiles, at most 100 per diagnosis, 3,875 rows; MedCaseReasoning: adult, patient-like,
   encounter-like test cases without missing media or a leaked diagnosis; AgentClinic: all adult records). The
   manifests list the source rows, rules and checksums. The DDXPlus pool rows are included.
2. **Source inventories** (`build_source_inventory.py`): a deterministic split of each raw case into numbered text
   pieces (history items, examination and test leaves). Raw data go under `data/raw/<dataset>/` (paths in each
   script).
3. **Annotation:** one bundle per case (patient facts, environment findings, gold), written by LLM agents following
   `CONVERSION.md` / `GUIDE.md`, then checked by `validate_cases.py`, `check_coverage.py`, `audit.py` and harmonised
   (`harmonize.py`). DDXPlus needs no annotation: `ddxplus/build_release.py` converts the structured
   evidence with `texts.py` and the catalogue.
4. **Fixes** (`fixes.py`): text fixes found by an independent check, applied to the bundles.
5. **Release** (`build_release.py` per dataset).

MedQA-CS is annotated in two steps (`conversion/medqa_cs/README.md`): an annotation of the raw case sheets, then its
conversion to the case schema.

Check: rebuilding the four releases with these scripts (from the bundles for AgentClinic, MedCaseReasoning and
MedQA-CS, from the pool for DDXPlus) reproduces every file in `data/releases/` byte for byte, so the release versions
match the table above.

The source inventories and annotation bundles of AgentClinic, MedCaseReasoning and MedQA-CS are included (for
MedQA-CS also the annotations of the first step), and the DDXPlus pool rows, so all four releases can be rebuilt
without the raw data.
