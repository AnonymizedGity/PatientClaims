#!/bin/bash
# Run arms of the study with the simulator: first the shared openings (one per case and seed, cached), then each named
# arm in turn. The arms and their sim.run options are listed in arms.tsv (the study's run-folder suffixes).
#
#   BASE_URL=http://127.0.0.1:8000/v1 MODEL_ID=Qwen/Qwen3.8-27B EVAL_DIR=../data \
#   bash run_paper.sh control A1_single A12a_EARLY
#
# Arguments: arm names from arms.tsv, or "all".
# Settings (environment):
#   BASE_URL         the patient model's OpenAI-compatible server (required); the doctor runs there too unless
#                    DOCTOR_BASE_URL is set
#   MODEL_ID         the model behind BASE_URL, recorded in run.json and in the openings' cache key
#   EVAL_DIR         the evaluation files: anchors/, main/cases.json (required)
#   RELEASES         the case releases (default $EVAL_DIR/data/releases)
#   VERSIONS         release version per dataset (default: the versions of the study)
#   TESTS            empty (default: no findings available to the doctor), TT or TE
#   TESTS_DIR        the per-finding labels for TT/TE (sim/compile_tests.py); default $EVAL_DIR/tests
#   DATASETS         default: all four without TESTS; agentclinic,medcasereasoning with TT; also medqa_cs with TE
#   CONDITIONS_DIR   the per-case picks for A12a and A13 (sim/compile_conditions.py); default $EVAL_DIR/conditions
#   SEEDS            dialogue seeds, e.g. 1,2,3 (default 1)
#   DOCTOR_BASE_URL  the doctor's own server (the study's MedGemma doctors); DOCTOR_MODEL_ID, the model behind it, for
#                    run.json; DOCTOR_MODEL, its model name on that server (default: the first model it serves)
#   OUT              the folder of the run folders (default runs); each arm runs into $OUT/<arm name>
#   OPENINGS         the openings cache (default $OUT/_openings); share it between OUT folders of the same patient model
#   WORKERS          parallel dialogues per run (default 16)
#   DRY_RUN          1: print the commands instead of running them
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
: "${BASE_URL:?set BASE_URL}" "${EVAL_DIR:?set EVAL_DIR}"
VERSIONS=${VERSIONS:-medqa_cs=216669d727b9,agentclinic=0669657c4f05,medcasereasoning=3172e8076188,ddxplus=ce9a684fa350}
case "${TESTS:-}" in
    "") DEFAULT_DATASETS=medqa_cs,agentclinic,medcasereasoning,ddxplus ;;
    TT) DEFAULT_DATASETS=agentclinic,medcasereasoning ;;
    TE) DEFAULT_DATASETS=agentclinic,medcasereasoning,medqa_cs ;;
    *) echo "TESTS must be empty, TT or TE" >&2; exit 2 ;;
esac
OUT=${OUT:-runs}
OPENINGS=${OPENINGS:-$OUT/_openings}
COMMON=(--base-url "$BASE_URL" --model local --model-id "${MODEL_ID:-}" --eval-dir "$EVAL_DIR"
        --releases "${RELEASES:-$EVAL_DIR/data/releases}" --versions "$VERSIONS"
        --datasets "${DATASETS:-$DEFAULT_DATASETS}" --seeds "${SEEDS:-1}" --workers "${WORKERS:-16}"
        --openings "$OPENINGS")
EXTRA=()
if [ -n "${TESTS:-}" ]; then
    EXTRA+=(--tests "$TESTS" --tests-dir "${TESTS_DIR:-$EVAL_DIR/tests}")
fi
if [ -n "${DOCTOR_BASE_URL:-}" ]; then
    EXTRA+=(--doctor-base-url "$DOCTOR_BASE_URL" --doctor-model-id "${DOCTOR_MODEL_ID:-}"
            ${DOCTOR_MODEL:+--doctor-model "$DOCTOR_MODEL"})
fi

names=("$@")
if [ "${#names[@]}" -eq 0 ]; then echo "name arms from arms.tsv, or all" >&2; exit 2; fi
if [ "${names[0]}" = all ]; then names=($(grep -v '^#' "$HERE/arms.tsv" | cut -f1)); fi
for name in "${names[@]}"; do
    grep -q "^$name	" "$HERE/arms.tsv" || { echo "unknown arm $name (see arms.tsv)" >&2; exit 2; }
done

export PYTHONPATH="$HERE"
run() {
    if [ "${DRY_RUN:-0}" = 1 ]; then printf '%q ' "$@"; echo; else "$@"; fi
}
# the openings the arms share (the A13 openings are made by their own runs)
run python -B -m sim.run --openings-only --arms control,single_exposure,persistence --out "$OUT/_openings_step" \
    "${COMMON[@]}"
for name in "${names[@]}"; do
    IFS=$'\t' read -r _ arms condition < <(grep "^$name	" "$HERE/arms.tsv")
    cond=()
    if [ "$condition" != - ]; then
        cond=(--condition "$condition" --conditions-dir "${CONDITIONS_DIR:-$EVAL_DIR/conditions}")
    fi
    [ "${DRY_RUN:-0}" = 1 ] || echo "$(date -Is) $name: --arms $arms ${cond[*]:-}"
    run python -B -m sim.run --design S1VRFm2 --arms "$arms" --out "$OUT/$name" "${COMMON[@]}" \
        ${cond[@]+"${cond[@]}"} ${EXTRA[@]+"${EXTRA[@]}"} || echo "$(date -Is) $name: not complete (run it again)"
done
