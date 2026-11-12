"""Every number in the paper, from the per-dialogue scores in results/scores/.

    python analysis/paper_numbers.py [--out analysis/output]

Writes paper_numbers.md (Tables 1-3 and the numbers in the text, each next to the value printed in the paper) and
paper_numbers.json. Runs in a few minutes on a laptop (the mixed models take most of it).

Definitions (as in the paper):
- top-1: the correct diagnosis ranked first; incomplete dialogues count as misses.
- X listed / X first: the wrong diagnosis X in the top five / ranked first.
- Cases where X is ranked first in at least two of three control seeds are left out of every comparison that
  involves X (own worry, sources, fact fitting X), per doctor and setting.
- Top-1 changes are differences on case-seed pairs (level minus control). Their significance is the mixed logistic
  model's p, Holm-adjusted across the levels of the intervention's family.
- Other outcomes: Wilcoxon signed-rank tests on per-case means, case-bootstrap CIs (5,000 resamples), BH-adjusted
  within the family (q).
- Diagnosis change: the top diagnosis of a level dialogue against the control dialogues of the other seeds, minus the
  same rate between two control seeds.
Bootstrap CIs depend on the random draws; with the seed below they can differ from the published intervals in the
last digit. Point estimates and p-values do not depend on them.
"""
import argparse
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np
from scipy.stats import wilcoxon

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data import (ANCHORED, HIST, LEVELS, PAPER_ARMS, SETS, dataset_of, load, source_arms,  # noqa: E402
                  x_first_cases)
from stats import bh, cluster_boot, compare_field, holm, mcnemar, mean_test, mixed_top1  # noqa: E402

SEED = 20261112
SRC = {"own": source_arms("own"), "doctor": source_arms("DOCTOR"), "AI": source_arms("AI"), "web": source_arms("WEB")}
SRC["AI + web"] = SRC["AI"] + SRC["web"]
SRC["all attributed"] = SRC["AI"] + SRC["web"] + SRC["doctor"]
SINGLE = {"own": "A1_single", "web": "A15_WEB_single", "AI": "A15_AI_single", "doctor": "A15_DOCTOR_single"}
TABLE_ROWS = [("Own worry", "A1_single"), ("Web", "A15_WEB_single"), ("AI chatbot", "A15_AI_single"),
              ("Another doctor", "A15_DOCTOR_single"), ("Fact fitting X", "A12a_anchor_R1"),
              ("Diagnostic fact", "A12a_EARLY"), ("Full opening", "A13_5")]


# ---------------------------------------------------------------- per-level comparisons

def change_test(lvl, ctrl, cases, rng):
    """Diagnosis change beyond seed variation, per case: the share of (level, control) pairs from different seeds whose
    top diagnoses differ, minus the same share between two control seeds."""
    by_l, by_c = defaultdict(list), defaultdict(list)
    for k, v in lvl.items():
        by_l[k[0]].append(v)
    for k, v in ctrl.items():
        by_c[k[0]].append(v)
    a, b = {}, {}
    for c in cases:
        lv = [r for r in by_l.get(c, []) if r["done"] and r["key"]]
        ct = [r for r in by_c.get(c, []) if r["done"] and r["key"]]
        if not lv or len(ct) < 2:
            continue
        crossed = [(x, y) for x in lv for y in ct if x["seed"] != y["seed"]]
        base = [(x, y) for x in ct for y in ct if x["seed"] != y["seed"]]
        if crossed and base:
            a[c] = float(np.mean([x["key"] != y["key"] for x, y in crossed]))
            b[c] = float(np.mean([x["key"] != y["key"] for x, y in base]))
    return mean_test({c: [a[c] - b[c]] for c in a}, list(a.values()), list(b.values()), rng)


def control_disagreement(ctrl):
    """Share of pairs of control seeds whose top diagnoses differ, averaged over cases."""
    by = defaultdict(list)
    for k, v in ctrl.items():
        by[k[0]].append(v)
    out = []
    for g in by.values():
        ct = [r for r in g if r["done"] and r["key"]]
        base = [(x, y) for x in ct for y in ct if x["seed"] != y["seed"]]
        if len(ct) >= 2 and base:
            out.append(np.mean([x["key"] != y["key"] for x, y in base]))
    return float(np.mean(out))


def level_rows(data, xf, rng):
    ctrl = data["control"]
    rows = {}
    for arm, (fam, label) in LEVELS.items():
        if arm not in data:
            continue
        lvl = {k: v for k, v in data[arm].items() if not (fam in ANCHORED and k[0] in xf)}
        keys = sorted(set(lvl) & set(ctrl))
        cases = sorted({k[0] for k in keys})
        row = {"family": fam, "label": label, "cases": len(cases), "pairs": len(keys),
               "mixed": mixed_top1(lvl, ctrl, keys), "top1": mcnemar(lvl, ctrl, keys, "top1", rng)}
        for f in ("anchor_in", "anchor_first", "x_top"):
            row[f] = compare_field(lvl, ctrl, keys, f, rng)
        row["change"] = change_test(lvl, ctrl, cases, rng)
        rows[arm] = row
    for fam in {r["family"] for r in rows.values()}:
        members = [a for a, r in rows.items() if r["family"] == fam]
        mm = [a for a in members if rows[a]["mixed"]]
        for a, p in zip(mm, holm([rows[a]["mixed"]["p"] for a in mm])):
            rows[a]["mixed"]["p_holm"] = p
        for f in ("anchor_in", "anchor_first", "x_top", "change"):
            mm = [a for a in members if rows[a][f]]
            for a, q in zip(mm, bh([rows[a][f]["p"] for a in mm])):
                rows[a][f]["q"] = q
    return rows


# ---------------------------------------------------------------- pooled comparisons

def pooled_effect(d, levels, field, exclude=(), cases=None):
    """Case -> (mean of the field over the levels' dialogues, mean over the control dialogues of the same seeds)."""
    ctrl, vals = d["control"], defaultdict(lambda: ([], []))
    for s in levels:
        for (c, sd), v in d.get(s, {}).items():
            if c in exclude or (cases is not None and c not in cases):
                continue
            x, y = v.get(field), ctrl.get((c, sd), {}).get(field)
            if x is not None and y is not None:
                vals[c][0].append(x)
                vals[c][1].append(y)
    return {c: (float(np.mean(a)), float(np.mean(b))) for c, (a, b) in vals.items()}


def pooled_test(d, levels, field, rng, exclude=()):
    e = pooled_effect(d, levels, field, exclude)
    return mean_test({c: [a - b] for c, (a, b) in e.items()}, [a for a, _ in e.values()],
                     [b for _, b in e.values()], rng) if e else None


def source_pairs(d, xf, rng):
    """One doctor, source against source on the same cases (pooled over the four doses), for X first; BH over the five
    comparisons."""
    pairs = [("doctor", "AI"), ("doctor", "web"), ("AI", "web"), ("own", "doctor"), ("own", "AI + web")]
    rows = []
    for s1, s2 in pairs:
        e1, e2 = pooled_effect(d, SRC[s1], "anchor_first", xf), pooled_effect(d, SRC[s2], "anchor_first", xf)
        cases = sorted(set(e1) & set(e2))
        r = mean_test({c: [e1[c][0] - e2[c][0]] for c in cases}, [e1[c][0] for c in cases],
                      [e2[c][0] for c in cases], rng)
        r.update(first=s1, second=s2)
        rows.append(r)
    for r, q in zip(rows, bh([r["p"] for r in rows])):
        r["q"] = q
    return {(r["first"], r["second"]): r for r in rows}


def dispute_pairs(d, xf, rng):
    """Dispute rate, source against source on the same case, seed and dose; BH over the six comparisons."""
    pairs = [("doctor", "web"), ("doctor", "AI"), ("AI", "web"), ("own", "doctor"), ("own", "AI"), ("own", "web")]
    rows = []
    for a, b in pairs:
        by, va, vb = defaultdict(list), [], []
        for x, y in zip(SRC[a], SRC[b]):
            for k in set(d[x]) & set(d[y]):
                if k[0] in xf:
                    continue
                p, q = d[x][k].get("disputed"), d[y][k].get("disputed")
                if p is not None and q is not None:
                    by[k[0]].append(p - q)
                    va.append(p)
                    vb.append(q)
        r = mean_test(by, va, vb, rng)
        r.update(first=a, second=b)
        rows.append(r)
    for r, q in zip(rows, bh([r["p"] for r in rows])):
        r["q"] = q
    return {(r["first"], r["second"]): r for r in rows}


def interaction(da, db, s1, s2, field, rng, exclude):
    """Per case: (B's s1 - s2 gap) minus (A's s1 - s2 gap), on the cases both doctors share."""
    ea, eb = pooled_effect(da, SRC[s1], field, exclude), pooled_effect(db, SRC[s1], field, exclude)
    ea2, eb2 = pooled_effect(da, SRC[s2], field, exclude), pooled_effect(db, SRC[s2], field, exclude)
    cases = sorted(set(ea) & set(eb) & set(ea2) & set(eb2))
    diff = {c: [(eb[c][0] - eb2[c][0]) - (ea[c][0] - ea2[c][0])] for c in cases}
    m = np.array([v[0] for v in diff.values()])
    p = wilcoxon(m, zero_method="wilcox").pvalue if np.any(m != 0) else 1.0
    return {"diff": float(m.mean()), "ci": cluster_boot(diff, rng), "p": float(p), "cases": len(cases)}


def named_vs_fact(d, xf, field):
    """Own worry (one mention) against the fact fitting X (reply 1), same case and seed: per-case mean difference."""
    by = defaultdict(list)
    for k, v in d["A1_single"].items():
        if k[0] in xf or k not in d["A12a_anchor_R1"]:
            continue
        by[k[0]].append(v[field] - d["A12a_anchor_R1"][k][field])
    m = np.array([np.mean(x) for x in by.values()])
    return {"diff": float(m.mean()), "p": float(wilcoxon(m).pvalue), "cases": len(m), "by": dict(by)}


def slot_model(d, levels, exclude):
    """If X only took a slot: a gold at rank 5 falls off when X enters above it, and nothing else moves. Predicted
    top-5 change against the observed change."""
    ctrl = d["control"]
    pred, obs, n = 0.0, 0.0, 0
    for s in levels:
        for (c, sd), v in d[s].items():
            u = ctrl.get((c, sd))
            if c in exclude or not u:
                continue
            obs += v["top5"] - u["top5"]
            n += 1
            if not u["anchor_in"] and v["anchor_in"] and u["g"] == 5:
                pred -= 1
    return {"predicted": pred / n, "observed": obs / n}


# ---------------------------------------------------------------- formatting

def pct(v, d=1):
    return f"{100 * v:.{d}f}"


def pts(v, d=1):
    s = f"{100 * v:+.{d}f}"
    return s.replace("-", "−")


def span(values, fmt, sep="–"):
    return f"{fmt(min(values))}{sep}{fmt(max(values))}"


def mark(s, significant):
    """Gray italics in the paper = not significant; shown here as (s)."""
    return s if significant else f"({s})"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "output"))
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    rng = np.random.default_rng(SEED)
    D, XF, R = {}, {}, {}
    for name in SETS:
        D[name] = load(name)
        XF[name] = x_first_cases(D[name]["control"])
        R[name] = level_rows(D[name], XF[name], rng)
        print("loaded", name, flush=True)

    checks = []   # (where, what, computed, paper)

    def check(where, what, computed, paper):
        checks.append((where, what, computed, paper))

    out = ["# The paper's numbers, recomputed\n",
           "Generated by analysis/paper_numbers.py from results/scores. Values in parentheses are not significant "
           "(the paper shows them in gray italics). Differences are in percentage points (pp).\n"]

    # ---------------- sizes
    out.append("## Data\n")
    total = 0
    for name in SETS:
        d, xf = D[name], XF[name]
        n = sum(len(v) if arm == "control" or LEVELS[arm][0] not in ANCHORED
                else sum(1 for k in v if k[0] not in xf) for arm, v in d.items() if arm in PAPER_ARMS)
        total += n
        anchored = len({k[0] for k in d["A1_single"]})
        out.append(f"- {SETS[name][0]} {SETS[name][1]}: {len({k[0] for k in d['control']})} cases, {anchored} anchored, "
                   f"{len(xf)} excluded (X first in >= 2 control seeds), {n:,} consultations in the analysis.")
    out.append(f"- Total: {total:,} consultations.\n")
    check("Setup", "consultations in the analysis", f"{total:,}", "120,930")
    check("Setup", "anchored cases", str(len({k[0] for k in D['hist_qwen']['A1_single']})), "362")
    check("Setup", "excluded cases per doctor, history only",
          f"{min(len(XF[n]) for n in HIST)}–{max(len(XF[n]) for n in HIST)}", "22–31")
    for name in ("tests_qwen", "tests_exam_qwen", "tests_medgemma27b", "tests_exam_medgemma27b"):
        c = D[name]["control"]
        share = np.mean([v["requested"] for v in c.values()])
        out.append(f"- {SETS[name][0]} {SETS[name][1]}: findings requested in {pct(share)}% of control dialogues.")
    check("Setup", "Qwen requests findings (control)",
          f"{pct(np.mean([v['requested'] for v in D['tests_qwen']['control'].values()]))}% / "
          f"{pct(np.mean([v['requested'] for v in D['tests_exam_qwen']['control'].values()]))}%", "about 80%")
    check("Setup", "MedGemma 27B requests findings (control)",
          f"{pct(np.mean([v['requested'] for v in D['tests_medgemma27b']['control'].values()]))}% / "
          f"{pct(np.mean([v['requested'] for v in D['tests_exam_medgemma27b']['control'].values()]))}%", "nearly all")
    out.append("")

    # ---------------- Table 1
    out.append("## Table 1 (history only, one mention)\n")
    out.append("| | " + " | ".join(f"{SETS[n][1]}: Listed | First | Top-1 | Change" for n in HIST) + " |")
    out.append("|---|" + "---|" * 12)
    ctl = []
    for n in HIST:
        r = R[n]["A1_single"]
        ctl += [pct(r["anchor_in"]["control"]), pct(r["x_top"]["control"]), pct(r["top1"]["control"]), "–"]
    out.append("| Control | " + " | ".join(ctl) + " |")
    paper_t1 = {
        "Control": ["39.5", "2.9", "32.7", "–", "32.8", "1.6", "28.5", "–", "25.9", "2.2", "13.8", "–"],
        "Own worry": ["+39.7", "5.5", "(+1.6)", "+5.8", "+36.1", "10.4", "(−0.9)", "+8.6", "+33.3", "16.2", "(−2.3)", "+9.0"],
        "Web": ["+39.6", "7.7", "(−1.7)", "+7.6", "+35.9", "12.6", "(−1.9)", "+12.4", "+40.3", "28.8", "−3.0", "+13.0"],
        "AI chatbot": ["+37.7", "7.3", "(−0.9)", "+5.5", "+35.9", "13.9", "(−2.0)", "+11.9", "+36.6", "22.1", "(−1.6)", "+11.1"],
        "Another doctor": ["+41.4", "16.4", "(−1.3)", "+9.1", "+43.7", "22.7", "−4.0", "+15.0", "+40.2", "25.9", "−3.0", "+13.2"],
        "Fact fitting X": ["+5.3", "(4.9)", "(+0.9)", "(+2.5)", "+8.2", "4.6", "(+1.3)", "+5.1", "+4.6", "5.5", "(+0.9)", "(+3.2)"],
        "Diagnostic fact": ["–", "5.0", "+9.8", "(+1.3)", "–", "(6.1)", "+5.9", "+4.8", "–", "(7.7)", "+4.3", "(+1.7)"],
        "Full opening": ["–", "(5.4)", "+8.8", "+5.1", "–", "(6.5)", "+9.5", "+8.5", "–", "(7.8)", "+6.1", "+6.8"],
    }
    for i, v in enumerate(ctl):
        check("Table 1", f"Control, column {i + 1}", v, paper_t1["Control"][i])
    for label, arm in TABLE_ROWS:
        cells = []
        for n in HIST:
            r = R[n][arm]
            listed = mark(pts(r["anchor_in"]["diff"]), r["anchor_in"]["q"] < 0.05) if arm.startswith(("A1_", "A15_", "A12a_anchor")) else "–"
            first = mark(pct(r["x_top"]["level"]), r["x_top"]["q"] < 0.05)
            top1 = mark(pts(r["top1"]["diff"]), r["mixed"]["p_holm"] < 0.05)
            change = mark(pts(r["change"]["diff"]), r["change"]["q"] < 0.05)
            cells += [listed, first, top1, change]
        out.append(f"| {label} | " + " | ".join(cells) + " |")
        for i, v in enumerate(cells):
            check("Table 1", f"{label}, column {i + 1}", v, paper_t1[label][i])
    out.append("\nThe control row is on the anchored cases. The last two rows use all 384 cases; their own control "
               "values of X first are " + ", ".join(f"{SETS[n][1]} {pct(R[n]['A12a_EARLY']['x_top']['control'])}%" for n in HIST) + ".\n")

    # ---------------- Table 2
    out.append("## Table 2 (history only, pooled over the four doses)\n")
    out.append("| Source | Listed | First | Disp. | Top-1 [95% CI] |")
    out.append("|---|---|---|---|---|")
    paper_t2 = {"hist_qwen": [("83.0", "5.4", "28.8", "(+0.6)"), ("81.4", "7.2", "29.4", "(−0.9)"), ("79.7", "5.9", "32.9", "(−0.8)"), ("83.7", "14.8", "18.7", "(−1.8)")],
                "hist_medgemma27b": [("70.3", "10.0", "7.0", "(−0.2)"), ("70.3", "13.3", "7.6", "(−2.0)"), ("69.6", "13.6", "9.3", "(−1.8)"), ("78.7", "23.5", "2.3", "−3.8")],
                "hist_medgemma4b": [("64.2", "13.7", "3.7", "(−1.1)"), ("70.5", "26.8", "3.5", "−3.0"), ("66.8", "21.6", "4.6", "(−2.0)"), ("69.6", "25.1", "2.0", "(−1.9)")]}
    for n in HIST:
        d, xf = D[n], XF[n]
        out.append(f"| **{SETS[n][1]}** (control {pct(R[n]['A1_single']['anchor_in']['control'])} / "
                   f"{pct(R[n]['A1_single']['anchor_first']['control'])}) | | | | |")
        for i, (label, s) in enumerate((("Own worry", "own"), ("Web", "web"), ("AI chatbot", "AI"), ("Another doctor", "doctor"))):
            recs = [v for a in SRC[s] for k, v in d[a].items() if k[0] not in xf and v.get("disputed") is not None]
            t = pooled_test(d, SRC[s], "top1", rng, xf)
            sig = not (t["ci"][0] <= 0 <= t["ci"][1])
            cells = (pct(np.mean([v["anchor_in"] for v in recs])), pct(np.mean([v["anchor_first"] for v in recs])),
                     pct(np.mean([v["disputed"] for v in recs])), mark(pts(t["diff"]), sig))
            out.append(f"| {label} | {cells[0]} | {cells[1]} | {cells[2]} | {cells[3]} [{pts(t['ci'][0])}, {pts(t['ci'][1])}] |")
            for j, (cv, pv) in enumerate(zip(cells, paper_t2[n][i])):
                check("Table 2", f"{SETS[n][1]}, {label}, column {j + 1}", cv, pv)
    out.append("")

    # ---------------- Table 3
    out.append("## Table 3 (change in top-1 accuracy, one mention)\n")
    t3 = [("hist_qwen", "tests_qwen", "tests_exam_qwen"), ("hist_medgemma27b", "tests_medgemma27b", "tests_exam_medgemma27b")]
    paper_t3 = {
        "Control top-1 (%)": ["31.9", "41.0", "47.3", "28.0", "33.3", "39.3"],
        "same cases, Hist.": ["–", "24.2", "27.9", "–", "19.4", "23.7"],
        "Own worry": ["(+1.6)", "−4.4", "(−1.3)", "(−0.9)", "(−0.9)", "(−1.2)"],
        "Web": ["(−1.7)", "(−2.8)", "(−1.5)", "(−1.9)", "−3.9", "(−1.6)"],
        "AI chatbot": ["(−0.9)", "(−2.0)", "(−1.7)", "(−2.0)", "−4.6", "(−1.8)"],
        "Another doctor": ["(−1.3)", "(−3.0)", "(−2.3)", "−4.0", "−5.7", "(−2.7)"],
        "Fact fitting X": ["(+0.9)", "(+0.2)", "(+3.2)", "(+1.3)", "(−2.3)", "(−0.3)"],
        "Diagnostic fact": ["+9.8", "+5.1", "+6.6", "+5.9", "+4.3", "+3.5"],
        "Full opening": ["+8.8", "+5.2", "+6.6", "+9.5", "(+0.9)", "+4.0"]}
    out.append("| Patient adds | " + " | ".join(f"{SETS[s][1]} {SETS[s][0]}" for trio in t3 for s in trio) + " |")
    out.append("|---|" + "---|" * 6)
    row_c, row_s = [], []
    for trio in t3:
        hist = D[trio[0]]["control"]
        for s in trio:
            row_c.append(pct(np.mean([v["top1"] for v in D[s]["control"].values()])))
            if s == trio[0]:
                row_s.append("–")
            else:
                cases = {k[0] for k in D[s]["control"]}
                row_s.append(pct(np.mean([v["top1"] for k, v in hist.items() if k[0] in cases])))
    out.append("| Control top-1 (%) | " + " | ".join(row_c) + " |")
    out.append("| same cases, Hist. | " + " | ".join(row_s) + " |")
    for i in range(6):
        check("Table 3", f"Control top-1, column {i + 1}", row_c[i], paper_t3["Control top-1 (%)"][i])
        check("Table 3", f"same cases, column {i + 1}", row_s[i], paper_t3["same cases, Hist."][i])
    for label, arm in TABLE_ROWS:
        cells = []
        for trio in t3:
            for s in trio:
                r = R[s][arm]
                cells.append(mark(pts(r["top1"]["diff"]), r["mixed"]["p_holm"] < 0.05))
        out.append(f"| {label} | " + " | ".join(cells) + " |")
        for i, v in enumerate(cells):
            check("Table 3", f"{label}, column {i + 1}", v, paper_t3[label][i])
    out.append("")

    # ---------------- text
    out.append("## Numbers in the text\n")
    h = {n: R[n] for n in HIST}
    lst = [h[n][a]["anchor_in"] for n in HIST for a in SINGLE.values()]
    check("3.1", "X listed in control, history only", span([h[n]['A1_single']['anchor_in']['control'] for n in HIST], lambda v: pct(v, 0)) + "%", "26–40%")
    check("Abstract, 3.1", "rise of X listed, one mention (12 comparisons)", f"{min(round(100 * r['diff']) for r in lst)}–{max(round(100 * r['diff']) for r in lst)} pp, max q {max(r['q'] for r in lst):.2g}", "33–44 pp, all q < 0.001")
    sp = {n: source_pairs(D[n], XF[n], rng) for n in SETS}
    for n, paper in (("hist_qwen", "7.6"), ("hist_medgemma27b", "10.1")):
        r = sp[n][("doctor", "web")]
        check("3.1", f"{SETS[n][1]}: X first, doctor minus web", f"{100 * r['diff']:.1f} pp, q {r['q']:.2g}", f"{paper} pp, q < 0.001")
    qs = [sp[n][pair]["q"] for n in ("tests_qwen", "tests_exam_qwen", "tests_medgemma27b", "tests_exam_medgemma27b") for pair in (("doctor", "web"), ("doctor", "AI"))]
    check("3.1", "with findings, X first: doctor vs web and vs AI (8 comparisons)", f"max q {max(qs):.3f}", "q ≤ 0.022")
    dp = {n: dispute_pairs(D[n], XF[n], rng) for n in SETS}
    for n in ("tests_qwen", "tests_exam_qwen"):
        r1, r2 = dp[n][("doctor", "web")], dp[n][("doctor", "AI")]
        check("3.1", f"{SETS[n][0]} Qwen: disputes, doctor vs web / AI", f"q {r1['q']:.3g} / {r2['q']:.3g}", "q < 0.01")
    qq = [dp[n][("doctor", "web")]["q"] for n in ("tests_medgemma27b", "tests_exam_medgemma27b")]
    check("3.1", "with findings, MedGemma 27B: disputes, doctor vs web", f"q {min(qq):.3f}, {max(qq):.3f}", "q ≥ 0.43")
    r = sp["hist_medgemma4b"][("doctor", "web")]
    check("3.1", "MedGemma 4B: X first, doctor vs web", f"{pct(r['level'])}% vs {pct(r['control'])}%, q {r['q']:.2f}", "25.1% vs 26.8%, q = 0.12")
    excl = XF["hist_qwen"] | XF["hist_medgemma4b"]
    it = interaction(D["hist_qwen"], D["hist_medgemma4b"], "doctor", "AI + web", "anchor_first", rng, excl)
    it_rows = [it] + [interaction(D["hist_qwen"], D["hist_medgemma4b"], a, b, "anchor_first", rng, excl)
                      for a, b in (("doctor", "web"), ("doctor", "AI"), ("own", "doctor"))]
    q_it = bh([x["p"] for x in it_rows])[0]
    check("3.1", "doctor minus AI+web gap, MedGemma 4B minus Qwen", f"{100 * it['diff']:.1f} pp [{100 * it['ci'][0]:.1f}, {100 * it['ci'][1]:.1f}], q {q_it:.2g}", "−7.6 pp [−10.1, −5.2], q < 0.001")
    r = h["hist_medgemma4b"]["A15_WEB_single"]
    check("3.1", "MedGemma 4B, web, one mention: top-1", f"{pts(r['top1']['diff'])} pp, p_Holm {r['mixed']['p_holm']:.2f}", "−3.0 pp, p_Holm = 0.03")
    qs = [dp[n][("own", "web")]["q"] for n in HIST]
    check("3.1", "disputes: web vs own worry, history only", f"min q {min(qs):.2f}", "q ≥ 0.39")
    for n, paper in (("hist_qwen", "not reported"), ("hist_medgemma27b", "3.5 pp, q < 0.001"), ("hist_medgemma4b", "10.5 pp, q < 0.001")):
        r = sp[n][("own", "AI + web")]
        check("3.1", f"{SETS[n][1]}: X first, AI+web minus own worry", f"{-100 * r['diff']:.1f} pp, q {r['q']:.2g}", paper)

    rows = [h[n]["A12a_anchor_R1"]["anchor_in"] for n in HIST]
    check("Abstract, 3.2", "fact fitting X: rise of X listed", span([r['diff'] for r in rows], pct) + f" pp, max q {max(r['q'] for r in rows):.2g}", "4.6–8.2 pp, q < 0.01")
    for field, paper in (("anchor_in", "33.6, 27.6, 28.5 pp, all p_Holm < 0.001"), ("anchor_first", "+0.8 (p = 0.58), 6.7, 12.2 pp, p_Holm < 0.001")):
        res = [named_vs_fact(D[n], XF[n], field) for n in HIST]
        ph = holm([x["p"] for x in res])
        check("3.2", f"own worry minus fact fitting X: {'X listed' if field == 'anchor_in' else 'X first'}",
              ", ".join(f"{100 * x['diff']:.1f} (p_Holm {p:.2g})" for x, p in zip(res, ph)), paper)
    fx = [R[n]["A12a_anchor_R1"] for n in SETS]
    check("3.2", "fact fitting X: top-1 change, all seven settings", span([r['top1']['diff'] for r in fx], pts, " to ") + f"; significant: {sum(r['mixed']['p_holm'] < 0.05 for r in fx)}", "−2.3 to +3.2, none significant")

    dis = [control_disagreement(D[n]["control"]) for n in HIST]
    check("3.3", "top diagnosis differs between two control seeds", span(dis, lambda v: pct(v, 0)) + "%", "49–60%")
    ch = [h[n][a]["change"] for n in HIST for a in SINGLE.values()]
    check("3.3", "diagnosis change, one mention", span([r['diff'] for r in ch], pts, " to ") + " pp", "5.5–15.0 pp")
    allq = [h[n][a]["change"]["q"] for n in HIST for a in LEVELS if LEVELS[a][0] in ("own", "source")]
    check("3.3", "diagnosis change, all 16 opinion levels x 3 doctors", f"max q {max(allq):.3f}", "q < 0.05 for every level")
    t1 = [h[n][a]["top1"]["diff"] for n in HIST for a in SINGLE.values()]
    check("3.3", "top-1 change, one mention, history only", f"{pts(min(t1))} to {pts(max(t1))} pp", "−4.0 to +1.6 pp")
    wo = [pooled_test(D[n], SRC["all attributed"], "top1_wo_x", rng, XF[n]) for n in HIST]
    check("3.3", "top-1 with X taken out, attributed opinions, history only", ", ".join(pts(r["diff"]) for r in wo), "−0.2, +0.4, −0.1")

    a1 = [R["tests_qwen"][a] for a in source_arms("own")]
    check("3.4", "Qwen +T, own worry, four doses", f"{pts(max(r['top1']['diff'] for r in a1))} to {pts(min(r['top1']['diff'] for r in a1))} pp, max p_Holm {max(r['mixed']['p_holm'] for r in a1):.3f}", "−3.2 to −4.4 pp, p_Holm ≤ 0.044")
    a15 = [R["tests_medgemma27b"][a] for a in LEVELS if LEVELS[a][0] == "source"]
    check("3.4", "MedGemma 27B +T, 12 attributed levels", f"{pts(max(r['top1']['diff'] for r in a15))} to {pts(min(r['top1']['diff'] for r in a15))} pp, OR {min(r['mixed']['or'] for r in a15):.2f}–{max(r['mixed']['or'] for r in a15):.2f}, max p_Holm {max(r['mixed']['p_holm'] for r in a15):.3f}", "−3.4 to −5.7 pp, OR 0.42–0.57, p_Holm ≤ 0.015")
    te = [R[n][a]["mixed"]["p_holm"] for n in ("tests_exam_qwen", "tests_exam_medgemma27b") for a in LEVELS if LEVELS[a][0] in ("own", "source")]
    check("3.4", "+T+E: opinion levels significant", f"{sum(p < 0.05 for p in te)} of {len(te)}", "none")
    for n, paper in (("tests_qwen", "−2.9"), ("tests_medgemma27b", "−3.5")):
        r = pooled_test(D[n], SRC["all attributed"], "top1_wo_x", rng, XF[n])
        check("3.4", f"{SETS[n][1]} +T: top-1 with X taken out, 12 levels", f"{pts(r['diff'])} [{pts(r['ci'][0])}, {pts(r['ci'][1])}]", f"{paper}, CI excludes 0")
    for n, paper in (("tests_qwen", "2.4"), ("tests_medgemma27b", "5.2")):
        r = pooled_test(D[n], SRC["all attributed"], "off", rng, XF[n])
        sm = slot_model(D[n], SRC["all attributed"], XF[n])
        check("3.4", f"{SETS[n][1]} +T: gold off the list; share explained by X taking a slot", f"{pts(r['diff'])} pp; {sm['predicted'] / sm['observed']:.2f}", f"{paper} pp; about one-tenth")
    ors = [h[n]["A12a_EARLY"]["mixed"]["or"] for n in HIST]
    check("3.4", "diagnostic fact, history only: OR", f"{min(ors):.1f}–{max(ors):.1f}", "2.4–3.7")
    ors = [h[n]["A13_5"]["mixed"]["or"] for n in HIST]
    check("3.4", "full opening, history only: OR", f"{min(ors):.1f}–{max(ors):.1f}", "2.8–4.4")

    out.append("| Where | What | Recomputed | Paper |")
    out.append("|---|---|---|---|")
    for where, what, c, p in checks:
        if not where.startswith("Table"):
            out.append(f"| {where} | {what} | {c} | {p} |")
    bad = [(w, x, c, p) for w, x, c, p in checks if w.startswith("Table") and c != p]
    out.append(f"\n## Table cells against the paper\n\n{sum(1 for w, *_ in checks if w.startswith('Table'))} cells compared, "
               f"{len(bad)} differ" + (":" if bad else "."))
    for w, x, c, p in bad:
        out.append(f"- {w}, {x}: recomputed {c}, paper {p}")
    text = "\n".join(out) + "\n"
    with open(os.path.join(args.out, "paper_numbers.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    with open(os.path.join(args.out, "paper_numbers.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump([{"where": w, "what": x, "recomputed": c, "paper": p} for w, x, c, p in checks], f, indent=1, ensure_ascii=False)
    print(f"{len(checks)} numbers; table cells differing: {len(bad)}")
    for w, x, c, p in bad:
        print(" ", w, x, "recomputed", c, "paper", p)


if __name__ == "__main__":
    main()
