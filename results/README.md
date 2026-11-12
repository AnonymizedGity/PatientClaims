# Results

## `scores/`: one row per dialogue

One file per doctor and setting, `<set>.jsonl.gz`, read by `analysis/paper_numbers.py` and rebuilt from the dialogues
by `scoring/build_scores.py`.

| Set | Doctor | Setting | Cases |
|---|---|---|---|
| `hist_qwen` | Qwen3.8-27B | history only | 384 |
| `hist_medgemma27b` | MedGemma 27B | history only | 384 |
| `hist_medgemma4b` | MedGemma 1.5 4B | history only | 384 |
| `tests_qwen` | Qwen3.8-27B | test results available (+T) | 249 (AgentClinic, MedCaseReasoning) |
| `tests_exam_qwen` | Qwen3.8-27B | vital signs, examination and test results (+T+E) | 284 (also MedQA-CS) |
| `tests_medgemma27b` | MedGemma 27B | +T | 249 |
| `tests_exam_medgemma27b` | MedGemma 27B | +T+E | 284 |

The patient is Qwen3.8-27B in every run. Three seeds per case and arm.

Fields:

| Field | Meaning |
|---|---|
| `run` | Run folder: `S4Fm2_<setting prefix>_<arm>__s<seed>` |
| `arm` | The arm (table below) |
| `case_id`, `dataset`, `seed` | |
| `complete`, `stop_reason` | A final differential exists and the dialogue ended normally (`doctor_finished` or `max_questions`); incomplete dialogues count as misses |
| `gold`, `gold_rank` | The correct diagnosis and its rank in the final differential (1-5, null = not listed) |
| `anchor`, `anchor_rank` | X and its rank (null for unanchored cases or when not listed) |
| `unmatched` | The other differential entries, in order |
| `worry_turns` | Patient turns that voiced the worry about X |
| `turns_after_worry`, `disputed_turns` | Doctor turns after the first worry, and those the patient-side controller marked as disputing it |
| `tests_requested`, `tests_shown`, `tests_hidden` | +T and +T+E only: whether the doctor requested the findings; how many were shown and how many withheld (findings that name or establish the diagnosis) |

Arms (run-folder suffix, as named in the paper):

| Arm | In the paper |
|---|---|
| `control` | Control |
| `A1_single`, `A1_sched2`, `A1_sched3`, `A1_persistence` | Own worry: one, two or three mentions, reactive |
| `A15_<SRC>_single`, `A15_<SRC>_sched2`, `A15_<SRC>_sched3`, `A15_<SRC>` | Source (`SRC` = `WEB`, `AI`, `DOCTOR`): the same four doses |
| `A12a_anchor_R1` | Fact fitting X (volunteered at reply 1) |
| `A12a_EARLY` | Diagnostic fact (volunteered at reply 1) |
| `A13_5` | Full opening |
| `A12a_anchor_R3`, `A12a_anchor_R5`, `A12a_LATE`, `A12a_R5`, `A13_3` | Not reported in the paper: the same facts at reply 3 or 5, and a 3-block opening. They belong to the same multiple-comparison families as the three arms above, so the paper's adjusted p and q values include them. |

## `dialogues_<set>.tar.xz`: the dialogues

The full dialogues of these runs, one archive per doctor and setting (the sets above): 158,361 dialogues in 525 run
folders, of which 127,281 are in the 20 reported arms (120,930 in the analysis, after leaving out the cases where X
already leads in the control arm) and 31,080 in the sibling arms. Unpacked they take 2.3 GB:

```bash
mkdir -p results/dialogues
for f in results/dialogues_*.tar.xz; do tar -xJf "$f" -C results/dialogues; done
```

Each run folder holds `run.json` (models, release versions, and the openings and label files under `data/`) and
`dialogues/<case>__<patient arm>__s<seed>.json` (patient arm: `control`, `single_exposure` or `persistence`; the
condition is in the run name), with every turn, the patient-side analysis and check of each reply, and the final
differential. `python scoring/build_scores.py results/dialogues --check` rebuilds
every score row from them; all 158,361 match the files in `scores/`.
