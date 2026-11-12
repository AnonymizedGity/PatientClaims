# Patient-Supplied Diagnostic Hypotheses in LLM Medical Consultations

Code, data and results for the paper *Patient-Supplied Diagnostic Hypotheses in LLM Medical Consultations: Effects on
Diagnostic Decisions* (WWW '27 short paper, under review).

An LLM doctor takes a history from an LLM-simulated patient, then returns a ranked differential
of up to five diagnoses. Between arms only the patient changes: it names a plausible but wrong diagnosis X (as its own
worry, or attributed to the web, an AI chatbot or another doctor), volunteers a recorded fact fitting X, volunteers a
recorded fact pointing to the correct diagnosis, or opens with a fuller account. Three doctors (Qwen3.8-27B, MedGemma
27B, MedGemma 1.5 4B), 384 cases from four datasets, three seeds, and for two doctors two more settings in which the
doctor can request test results (+T) or vital signs, examination and test results (+T+E).

## Contents

| Folder | What it holds |
|---|---|
| `simulator/` | The patient simulator and the doctor protocol, as used for every run (see `simulator/README.md`). |
| `data/` | The case list, X for each case, the per-case picks, the test-finding labels, the converted cases, the cached openings, and the conversion pipeline (see `data/README.md`). |
| `scoring/` | Scoring of a dialogue (rank of the correct diagnosis and of X), and the build of the per-dialogue score files from the dialogues. |
| `results/scores/` | One row per dialogue of every run the paper uses (see `results/README.md`). |
| `results/dialogues_<set>.tar.xz` | The dialogues themselves, one archive per doctor and setting (see `results/README.md`). |
| `analysis/` | `paper_numbers.py`: every number in the paper's tables and text, from the score files. |
| `audit/` | The two checks of the simulated patient that the paper cites. |

## Reproducing the paper's numbers

```bash
pip install -r requirements.txt
python analysis/paper_numbers.py
```

This writes `analysis/output/paper_numbers.md`: Tables 1-3 and each number in the text, recomputed, next to the value
printed in the paper (a few minutes; the mixed models take most of it). Point estimates and p-values are exact.
Bootstrap confidence intervals depend on the random draws and can differ from the published ones in the last digit.

To rebuild the score files from the dialogues and check them against the shipped ones:

```bash
mkdir -p results/dialogues
for f in results/dialogues_*.tar.xz; do tar -xJf "$f" -C results/dialogues; done
python scoring/build_scores.py results/dialogues --check
```

## Statistics in brief

- All comparisons are paired: the same cases and seeds with and without the intervention.
- Top-1 accuracy (primary): mixed logistic models with a random intercept per case (`analysis/stats.py`), odds ratios,
  Holm-adjusted across the levels of each intervention. The changes in percentage points are differences on
  case-seed pairs.
- Other outcomes (exploratory): Wilcoxon signed-rank tests on per-case means, case-bootstrap CIs (5,000 resamples),
  Benjamini-Hochberg within each intervention or outcome.
- Cases where X is ranked first in at least two of three control seeds are left out of every comparison involving X,
  per doctor and setting.
- The fact and opening interventions each have sibling levels that the paper does not report (the fact at reply 3 or
  5, a 3-block opening). They are part of the same correction families, so their scores are included.
