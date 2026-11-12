"""Statistics used by paper_numbers.py.

- fit(): cumulative-logit model with a random intercept per case, fitted by maximum likelihood with Gauss-Hermite
  quadrature over the random intercept. With K = 2 it is the mixed logistic model of the paper (top-1 accuracy,
  reported as odds ratios with Wald CIs and p-values from a numerical Hessian).

      P(Y <= k | x, u) = logistic(theta_k - x'beta - u),  u ~ N(0, sigma^2)

  Y is coded 0..K-1 with higher = better, so beta > 0 (OR > 1) means the level improves the outcome.
- cluster_boot(): case bootstrap of a mean over case-seed pairs (5,000 resamples).
- mean_test(): per-case differences, Wilcoxon signed-rank test across cases and the case bootstrap.
- mcnemar(): level against control on case-seed pairs (exact McNemar test), with the case-bootstrap CI.
- holm(), bh(): Holm and Benjamini-Hochberg adjustment.
"""
import math

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit
from scipy.stats import binomtest, wilcoxon
from scipy.stats import norm as _normal
from statsmodels.stats.multitest import multipletests

BOOT = 5000
GH_X, GH_W = np.polynomial.hermite.hermgauss(30)
NODES = math.sqrt(2.0) * GH_X           # for u = sigma * node
LOGW = np.log(GH_W / math.sqrt(math.pi))


def _unpack(params, K, p):
    t = params[:K - 1]
    theta = np.concatenate([[t[0]], t[0] + np.cumsum(np.exp(t[1:]))]) if K > 2 else t
    return theta, params[K - 1:K - 1 + p], params[-1]


def _negloglik(params, y, X, gidx, ngroups, K):
    theta, beta, logsig = _unpack(params, K, X.shape[1])
    sig = math.exp(logsig)
    eta = X @ beta
    u = sig * NODES
    lin = eta[:, None] + u[None, :]
    th = np.concatenate([[-np.inf], theta, [np.inf]])
    up, lo = th[y + 1][:, None] - lin, th[y][:, None] - lin
    lp = np.log(np.clip(expit(up) - expit(lo), 1e-300, None))
    per_group = np.zeros((ngroups, len(NODES)))
    np.add.at(per_group, gidx, lp)
    m = per_group + LOGW[None, :]
    mx = m.max(axis=1, keepdims=True)
    return -float((mx[:, 0] + np.log(np.exp(m - mx).sum(axis=1))).sum())


def _hessian(f, x, h=1e-4):
    n = len(x)
    H = np.zeros((n, n))
    for i in range(n):
        for j in range(i, n):
            e_i, e_j = np.eye(n)[i] * h, np.eye(n)[j] * h
            v = (f(x + e_i + e_j) - f(x + e_i - e_j) - f(x - e_i + e_j) + f(x - e_i - e_j)) / (4 * h * h)
            H[i, j] = H[j, i] = v
    return H


def fit(y, X, groups):
    """y: ints 0..K-1 (higher = better); X: n x p covariates (no intercept); groups: case labels."""
    y = np.asarray(y, int)
    X = np.asarray(X, float).reshape(len(y), -1)
    _, y = np.unique(y, return_inverse=True)      # empty categories merged; beta unchanged
    K = int(y.max()) + 1
    if K < 2:
        raise ValueError("a single observed category")
    labels, gidx = np.unique(np.asarray(groups, object).astype(str), return_inverse=True)
    p = X.shape[1]
    cum = np.clip(np.cumsum(np.bincount(y, minlength=K))[:-1] / len(y), 0.02, 0.98)
    t0 = np.log(cum / (1 - cum))
    start = np.concatenate([[t0[0]], np.log(np.maximum(np.diff(t0), 0.05)), np.zeros(p), [0.0]])
    f = lambda v: _negloglik(v, y, X, gidx, len(labels), K)       # noqa: E731
    res = minimize(f, start, method="BFGS", options={"gtol": 1e-6, "maxiter": 500})
    H = _hessian(f, res.x)
    try:
        se_all = np.sqrt(np.clip(np.diag(np.linalg.inv(H)), 0, None))
    except np.linalg.LinAlgError:
        se_all = np.full(len(res.x), np.nan)
    beta, se = res.x[K - 1:K - 1 + p], se_all[K - 1:K - 1 + p]
    with np.errstate(divide="ignore", invalid="ignore"):
        z = np.where(se > 0, beta / se, np.nan)
    return {"beta": beta, "se": se, "ci": np.stack([beta - 1.96 * se, beta + 1.96 * se], axis=1),
            "p": 2 * _normal.sf(np.abs(z)), "sigma": math.exp(res.x[-1]), "converged": bool(res.success)}


def mixed_top1(level, control, keys):
    """Level (arm 1) against control (arm 0) on the same case-seed keys; random intercept per case.
    Returns the odds ratio, its 95% CI and p, or None (fewer than 5 cases, one outcome only, or separation)."""
    if len({k[0] for k in keys}) < 5:
        return None
    y = [control[k]["top1"] for k in keys] + [level[k]["top1"] for k in keys]
    if len(set(y)) < 2:
        return None
    x = np.array([0] * len(keys) + [1] * len(keys)).reshape(-1, 1)
    r = fit(np.array(y), x, [k[0] for k in keys] * 2)
    b, se = float(r["beta"][0]), float(r["se"][0])
    if not (abs(b) <= 10 and se <= 5):
        return None
    return {"or": math.exp(b), "ci": tuple(math.exp(v) for v in r["ci"][0]), "p": float(r["p"][0])}


def cluster_boot(diff_by_case, rng):
    """diff_by_case: case -> list of per-seed differences; 95% CI of the mean over case-seed pairs, resampling cases."""
    cases = list(diff_by_case)
    if not cases:
        return (math.nan, math.nan)
    sums = np.array([sum(diff_by_case[c]) for c in cases], float)
    ns = np.array([len(diff_by_case[c]) for c in cases], float)
    idx = rng.integers(0, len(cases), size=(BOOT, len(cases)))
    means = sums[idx].sum(axis=1) / ns[idx].sum(axis=1)
    return (float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)))


def mean_test(by, a_vals, b_vals, rng):
    """by: case -> list of differences. Wilcoxon signed-rank test on the per-case means; the case bootstrap CI."""
    if not by:
        return None
    m = np.array([np.mean(v) for v in by.values()])
    p = wilcoxon(m, zero_method="wilcox").pvalue if np.any(m != 0) else 1.0
    return {"level": float(np.mean(a_vals)), "control": float(np.mean(b_vals)),
            "diff": float(np.mean([d for v in by.values() for d in v])),
            "ci": cluster_boot(by, rng), "p": float(p), "cases": len(by)}


def compare_field(level, control, keys, field, rng):
    """Level against control on the same case-seed keys for one 0/1 or numeric field."""
    by, av, bv = {}, [], []
    for k in keys:
        x, y = level[k].get(field), control[k].get(field)
        if x is not None and y is not None:
            by.setdefault(k[0], []).append(x - y)
            av.append(x)
            bv.append(y)
    return mean_test(by, av, bv, rng)


def mcnemar(level, control, keys, field, rng):
    x = np.array([level[k][field] for k in keys])
    y = np.array([control[k][field] for k in keys])
    lost, gained = int(((y == 1) & (x == 0)).sum()), int(((y == 0) & (x == 1)).sum())
    p = binomtest(min(lost, gained), lost + gained, 0.5).pvalue if lost + gained else 1.0
    by = {}
    for k, d in zip(keys, x - y):
        by.setdefault(k[0], []).append(d)
    return {"level": float(x.mean()), "control": float(y.mean()), "diff": float(x.mean() - y.mean()),
            "ci": cluster_boot(by, rng), "lost": lost, "gained": gained, "p": float(p)}


def holm(ps):
    return [float(v) for v in multipletests(ps, method="holm")[1]] if ps else []


def bh(ps):
    return [float(v) for v in multipletests(ps, method="fdr_bh")[1]] if ps else []
