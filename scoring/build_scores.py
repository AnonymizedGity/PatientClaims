"""Per-dialogue scores of the paper's runs, from the dialogues.

    python scoring/build_scores.py DIALOGUES_DIR [--out results/scores] [--check]

DIALOGUES_DIR holds the run folders (<run>/dialogues/*.json), as unpacked from the dialogue archive (results/README.md).
Writes one results/scores/<set>.jsonl.gz per doctor and setting, sorted, the files analysis/paper_numbers.py reads.
With --check, compares with the files already in --out instead of writing them, and reports any difference.
"""
import argparse
import glob
import gzip
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from score import dispute_marks, score, tests_fields      # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Run-folder prefix of each doctor and setting (the longest matching prefix wins).
PREFIXES = {"S4Fm2_main_": "hist_qwen", "S4Fm2_dMG27_": "hist_medgemma27b", "S4Fm2_dMG4_": "hist_medgemma4b",
            "S4Fm2_TT_": "tests_qwen", "S4Fm2_TE_": "tests_exam_qwen", "S4Fm2_dMG27_TT_": "tests_medgemma27b",
            "S4Fm2_dMG27_TE_": "tests_exam_medgemma27b"}


def set_and_arm(run):
    pre = max((p for p in PREFIXES if run.startswith(p)), key=len, default=None)
    if pre is None:
        return None, None
    return PREFIXES[pre], run[len(pre):].split("__")[0]


def rows_of(run_dir):
    run = os.path.basename(os.path.normpath(run_dir))
    name, arm = set_and_arm(run)
    out = []
    for p in sorted(glob.glob(os.path.join(run_dir, "dialogues", "*.json"))):
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        r = {"run": run, "arm": arm, **score(d), **dispute_marks(d), **tests_fields(d)}
        out.append(r)
    return name, out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dialogues")
    ap.add_argument("--out", default=os.path.join(ROOT, "results", "scores"))
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    by_set = {}
    for run_dir in sorted(glob.glob(os.path.join(args.dialogues, "*"))):
        name, rows = rows_of(run_dir)
        if name:
            by_set.setdefault(name, []).extend(rows)
    bad = 0
    for name, rows in sorted(by_set.items()):
        rows.sort(key=lambda x: (x["arm"], x["seed"], x["dataset"], x["case_id"]))
        lines = [json.dumps(x, ensure_ascii=False, sort_keys=True) for x in rows]
        path = os.path.join(args.out, name + ".jsonl.gz")
        if args.check:
            with gzip.open(path, "rt", encoding="utf-8") as f:
                have = [json.loads(line) for line in f]
            new = [json.loads(line) for line in lines]
            diff = [(a, b) for a, b in zip(have, new) if a != b]
            n = len(diff) + abs(len(have) - len(new))
            bad += n
            print(f"{name}: {len(new)} dialogues, {len(have)} in {path}, {n} differ")
            for a, b in diff[:5]:
                print("  have", {k: a[k] for k in a if a[k] != b.get(k)}, "\n  new ", {k: b.get(k) for k in a if a[k] != b.get(k)})
        else:
            with gzip.GzipFile(path, "wb", mtime=0) as g:
                for line in lines:
                    g.write((line + "\n").encode("utf-8"))
            print(f"{name}: {len(rows)} dialogues -> {path}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
