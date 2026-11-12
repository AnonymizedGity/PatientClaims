# MedQA-CS (35 adult cases)

Each adult OSCE case is split into what the patient knows, the clinical environment, and the evaluator-only gold, in
two steps done by LLM agents and checked by scripts: an annotation of the raw case sheet ([GUIDE.md](GUIDE.md)), then
its conversion to the common case schema ([CONVERSION.md](CONVERSION.md), [../case_schema.md](../case_schema.md)).

| Step | File | What it does |
|---|---|---|
| 1 | `build_source_inventory.py` → `source/` | Deterministic split of the raw case sheets: Q/A script (`pNNN` ids), doorway vitals, SP notes, student note, exam lines (`eNNN` ids), gold. |
| 2 | `annotations/` | One annotation per case, following `GUIDE.md` (case 001 is the worked example). |
| 3 | `validate.py` | Schema, enums, full coverage of every Q/A and exam id, doorway vitals present, no review commentary in findings. |
| 4 | `audit.py` | Quotes are exact substrings of the cited answers; polarity candidates; per-batch habits. |
| 5 | `fix_env_commentary.py` | Review commentary moved from `finding` to `flags`. |
| 6 | `confirm_templates.py` | Checks template answers against the June 2024 release (see below). |
| 7 | `bundles/` | One case-schema bundle per case, converted from the annotation following `CONVERSION.md`; checked by `../validate_cases.py --bundles` and `check_coverage.py`. |
| 8 | `harmonize.py`, `../fixes.py` | Explicit, logged edits across the bundles. |
| 9 | `build_release.py` | Writes the release: `medqa_cs_{patient,environment,gold,qc}.jsonl` and `manifest.json`. |

Rebuild the release from the bundles: `python build_release.py OUT_FOLDER`.

## Source versions

`data/raw/medqa_cs/med-student.json` is the Hugging Face release of 27 September 2024. It is an LLM-reworded version
of the June 2024 upload (`data/raw/medqa_cs_2024-06/`), with about 93–96% text similarity per case. The rewording
replaced short "No." / "None." answers with stock phrases ("No, I do not.", "No changes.", …), 92 times across 8 adult
cases. The June release shows that all 92 were plain denials, and the facts built on them are annotated as denials and
flagged as confirmed. The annotation is based on the September release; the June text is used only for this check.
