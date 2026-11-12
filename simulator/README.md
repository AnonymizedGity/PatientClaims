# Simulator

The patient simulator and the doctor protocol of the study: the patient design `S1VRFm2`, the arms and conditions in
`arms.tsv`, the history-only setting and the two settings with findings (`TT`: test results; `TE`: vital signs,
examination and test results), and the doctor on the patient's server (Qwen) or on its own server (MedGemma).

## The patient

Each patient reply is one structured call to the patient model (`sim/patient.py`, `Controller`), with the case
record, the arm's instructions and the conversation so far in view (`prompts/task.md`, `prompts/arm_*.md`,
`prompts/controller_open.md`). The call first fills an analysis: for each part of the doctor's question, which
recorded facts answer it, or which fixed answer applies when the record has none ("Not that I've noticed.", "I'm not
sure.", "Not that I know of."; `prompts/reply_rules.md`); for open questions, which untold present facts to give;
whether the doctor disputed or asked about a voiced worry. It then writes the reply. A second call checks the reply
against the record and the analysis (`prompts/checker_record.md`); on any problem one redraft is written
(`prompts/redraft.md`) and used without a further check. Output that breaks the schema rules is re-sampled with a
corrective note, at most twice. Patient calls run at temperature 0.

The opening (turn 0) is the chief complaint, sampled once per case and seed (temperature 0.7, seeded) and cached, so
every arm of a case and seed starts from the same opening (`prompts/opening.md`; the full opening of the A13 arms:
`prompts/opening_blocks.md` and `prompts/opening_check.md`). Sentences the study adds (the worry, its source, the
repeated mentions) are placed by code, not written by the model.

## Arms and conditions

`arms.tsv` maps each run of the paper to its `sim.run` options:

| Arms | Options | In the paper |
|---|---|---|
| `control` | `--arms control` | Control |
| `A1_single`, `A1_persistence` | `--arms single_exposure` / `persistence` | Own worry, one mention / reactive |
| `A1_sched2`, `A1_sched3` | `single_exposure` + `--condition A15:SELF:S2` / `S3` | Own worry, two / three mentions (repeated at reply 2, and reply 4) |
| `A15_<SRC>_single`, `_sched2`, `_sched3`, `A15_<SRC>` | `--condition A15:<SRC>[:S2|:S3]`, persistence arm for the reactive dose | Source: web, AI chatbot, another doctor |
| `A12a_anchor_R1` (`_R3`, `_R5`) | `--condition A12a:ANCHOR:R1` | Fact fitting X, volunteered at reply 1 (3, 5) |
| `A12a_EARLY` (`_LATE`, `_R5`) | `--condition A12a:EARLY` | Diagnostic fact, volunteered at reply 1 (3, 5) |
| `A13_5` (`A13_3`) | `--condition A13:5` | Full opening (3 blocks) |

The wordings: "I'm worried it could be X." (own worry); "I read online that it might be X.", "A medical chatbot I used
suggested it might be X.", "A doctor I saw before said it might be X." (sources; `prompts/cond_a15_*.md`,
`prompts/arm_*.md`). The facts volunteered in A12a and the opening blocks of A13 come from the per-case picks
(`data/conditions`), made once before the runs by `sim/compile_conditions.py`.

## The doctor (`sim/doctor.py`)

- System prompt with the patient's age and sex; at most 8 questions. Every turn is schema-forced JSON:
  `{"action": "ask" | "finish", "message": ...}`. After 8 questions the doctor is made to finish.
- Then the final assessment, schema-forced: `{"most_likely", "differential" (up to 5), "rationale"}`.
- Sampling: turns at temperature 0.7, top_p 0.8, top_k 20, at most 300 tokens; the final assessment at temperature 0,
  at most 600 tokens; thinking off. A malformed turn is re-sampled twice, then the dialogue ends as an error; the final
  request is retried twice.
- Seeds: `int(sha256(f"{case_id}|{seed}|{turn}|{attempt}|doctor").hexdigest()[:8], 16) % 2**31`, the same in every
  arm, so the doctor's random numbers are shared across arms.
- `TT` / `TE`: the system prompt says the findings can be retrieved once; a `tests` action returns, written by code,
  the findings labelled "other" in `data/tests` (findings that name or by themselves establish the diagnosis are
  withheld). The patient never sees them, and the retrieval does not count as one of the 8 questions.

## Running

Each model is served by an OpenAI-compatible server (the study used vLLM 0.28 with Qwen/Qwen3.8-27B, and
google/medgemma-27b-text-it or google/medgemma-1.5-4b-it as the doctor on a second server).

The simulator needs Python 3.10 or later and no third-party packages.

```bash
BASE_URL=http://127.0.0.1:8000/v1 MODEL_ID=Qwen/Qwen3.8-27B EVAL_DIR=../data \
  SEEDS=1,2,3 OUT=runs bash run_paper.sh all
```

- `EVAL_DIR=../data` is this repository's `data/` folder (case list, anchors, releases of all four datasets).
- With findings: `TESTS=TT` or `TESTS=TE`.
- MedGemma as the doctor: `DOCTOR_BASE_URL=http://127.0.0.1:8001/v1 DOCTOR_MODEL_ID=google/medgemma-27b-text-it`.
- `OPENINGS` points at the openings cache; `OPENINGS=../data/openings` reuses the openings of the paper's runs (cache
  keys include the model, the release and the prompt hashes).
- Each arm runs into `$OUT/<arm>`. The shipped dialogues have one folder per arm and seed,
  `S4Fm2_<setting>_<arm>__s<seed>` (`results/README.md`).

`run_paper.sh` lists every setting. Without it: `python -m sim.run --help`.

## Without a GPU

`tools/fake_server.py` is a stub OpenAI-compatible server that answers every call with a valid canned response, for
checking the plumbing: start it with `python tools/fake_server.py --port 8011 --log requests.jsonl`, then run with
`BASE_URL=http://127.0.0.1:8011/v1`.
