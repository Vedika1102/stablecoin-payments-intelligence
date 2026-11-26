"""
Small, tested statistics toolkit used by the A/B test and churn analyses.

Each function returns a plain dict so results drop straight into a report table.
The formulas are written out (rather than only calling a library) so they can be
explained line by line in an interview; tests/test_stats_utils.py checks them
against scipy / statsmodels.
"""

from __future__ import annotations

import math

import numpy as np
from scipy import stats

# ---------------------------------------------------------------------------
# Experiment design
# ---------------------------------------------------------------------------

def sample_size_two_proportions(p_baseline: float, mde_abs: float, alpha: float = 0.05,
                                power: float = 0.80, two_sided: bool = True) -> int:
    """Units needed *per arm* to detect an absolute lift `mde_abs` on a conversion rate.

    n = (z_{1-a/2} * sqrt(2 p_bar (1-p_bar)) + z_{1-b} * sqrt(p1(1-p1) + p2(1-p2)))^2 / mde^2
    """
    p1, p2 = p_baseline, p_baseline + mde_abs
    p_bar = (p1 + p2) / 2
    z_a = stats.norm.ppf(1 - alpha / 2) if two_sided else stats.norm.ppf(1 - alpha)
    z_b = stats.norm.ppf(power)
    num = (z_a * math.sqrt(2 * p_bar * (1 - p_bar)) + z_b * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))) ** 2
    return math.ceil(num / mde_abs ** 2)


def mde_two_proportions(p_baseline: float, n_per_arm: int, alpha: float = 0.05, power: float = 0.80) -> float:
    """Minimum detectable absolute effect for a given per-arm sample (normal approximation)."""
    z_a, z_b = stats.norm.ppf(1 - alpha / 2), stats.norm.ppf(power)
    return (z_a + z_b) * math.sqrt(2 * p_baseline * (1 - p_baseline) / n_per_arm)


def srm_check(n_control: int, n_treatment: int, expected_ratio: float = 0.5) -> dict:
    """Sample ratio mismatch: chi-squared goodness of fit against the planned split."""
    total = n_control + n_treatment
    expected = [total * expected_ratio, total * (1 - expected_ratio)]
    chi2, p = stats.chisquare([n_control, n_treatment], f_exp=expected)
    return {"n_control": n_control, "n_treatment": n_treatment, "chi2": chi2, "p_value": p,
            "srm_detected": bool(p < 0.001)}


# ---------------------------------------------------------------------------
# Proportions
# ---------------------------------------------------------------------------

def two_proportion_test(x_c: int, n_c: int, x_t: int, n_t: int, alpha: float = 0.05) -> dict:
    """Two-proportion z-test (pooled SE for the test, unpooled SE for the CI)."""
    p_c, p_t = x_c / n_c, x_t / n_t
    diff = p_t - p_c
    p_pool = (x_c + x_t) / (n_c + n_t)
    se_pool = math.sqrt(p_pool * (1 - p_pool) * (1 / n_c + 1 / n_t))
    z = diff / se_pool
    p_value = 2 * (1 - stats.norm.cdf(abs(z)))
    se = math.sqrt(p_c * (1 - p_c) / n_c + p_t * (1 - p_t) / n_t)
    z_crit = stats.norm.ppf(1 - alpha / 2)
    # Relative lift CI via the delta method on log(p_t / p_c)
    se_log_rr = math.sqrt((1 - p_t) / (p_t * n_t) + (1 - p_c) / (p_c * n_c))
    rr = p_t / p_c
    return {
        "control_rate": p_c, "treatment_rate": p_t,
        "abs_diff": diff, "ci_low": diff - z_crit * se, "ci_high": diff + z_crit * se,
        "rel_lift": rr - 1,
        "rel_ci_low": math.exp(math.log(rr) - z_crit * se_log_rr) - 1,
        "rel_ci_high": math.exp(math.log(rr) + z_crit * se_log_rr) - 1,
        "z": z, "p_value": p_value,
        "cohens_h": 2 * math.asin(math.sqrt(p_t)) - 2 * math.asin(math.sqrt(p_c)),
    }


def chi_square_independence(table: np.ndarray) -> dict:
    """Pearson chi-squared test of independence plus Cramer's V effect size."""
    table = np.asarray(table)
    chi2, p, dof, expected = stats.chi2_contingency(table, correction=False)
    n = table.sum()
    k = min(table.shape) - 1
    cramers_v = math.sqrt(chi2 / (n * k)) if k > 0 else float("nan")
    return {"chi2": chi2, "dof": dof, "p_value": p, "cramers_v": cramers_v,
            "min_expected": float(expected.min())}


# ---------------------------------------------------------------------------
# Means
# ---------------------------------------------------------------------------

def welch_t_test(a: np.ndarray, b: np.ndarray, alpha: float = 0.05) -> dict:
    """Welch's t-test (unequal variances) for mean(b) - mean(a), with CI and Cohen's d."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    ma, mb = a.mean(), b.mean()
    va, vb = a.var(ddof=1), b.var(ddof=1)
    na, nb = len(a), len(b)
    se = math.sqrt(va / na + vb / nb)
    t = (mb - ma) / se
    df = (va / na + vb / nb) ** 2 / ((va / na) ** 2 / (na - 1) + (vb / nb) ** 2 / (nb - 1))
    p = 2 * (1 - stats.t.cdf(abs(t), df))
    t_crit = stats.t.ppf(1 - alpha / 2, df)
    pooled_sd = math.sqrt(((na - 1) * va + (nb - 1) * vb) / (na + nb - 2))
    return {"mean_a": ma, "mean_b": mb, "diff": mb - ma,
            "ci_low": mb - ma - t_crit * se, "ci_high": mb - ma + t_crit * se,
            "t": t, "df": df, "p_value": p, "cohens_d": (mb - ma) / pooled_sd}


def bootstrap_diff_ci(a: np.ndarray, b: np.ndarray, stat=np.mean, n_boot: int = 2000,
                      alpha: float = 0.05, seed: int = 7) -> dict:
    """Percentile bootstrap CI for stat(b) - stat(a). Robust to skewed metrics like minutes."""
    rng = np.random.default_rng(seed)
    a, b = np.asarray(a, float), np.asarray(b, float)
    diffs = np.empty(n_boot)
    for i in range(n_boot):
        diffs[i] = stat(rng.choice(b, len(b))) - stat(rng.choice(a, len(a)))
    return {"diff": stat(b) - stat(a),
            "ci_low": float(np.quantile(diffs, alpha / 2)),
            "ci_high": float(np.quantile(diffs, 1 - alpha / 2))}


# ---------------------------------------------------------------------------
# Multiple testing & correlation
# ---------------------------------------------------------------------------

def holm_bonferroni(p_values: list[float], alpha: float = 0.05) -> list[dict]:
    """Holm step-down correction. Returns adjusted p-values in the original order."""
    m = len(p_values)
    order = np.argsort(p_values)
    adjusted = np.empty(m)
    running_max = 0.0
    for rank, idx in enumerate(order):
        adj = min(1.0, (m - rank) * p_values[idx])
        running_max = max(running_max, adj)
        adjusted[idx] = running_max
    return [{"p_value": p, "p_adjusted": a, "reject": a < alpha} for p, a in zip(p_values, adjusted)]


def correlation_with_ci(x: np.ndarray, y: np.ndarray, method: str = "pearson", alpha: float = 0.05) -> dict:
    """Pearson or Spearman correlation with a Fisher-z confidence interval."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    r, p = (stats.pearsonr(x, y) if method == "pearson" else stats.spearmanr(x, y))
    r = float(r)
    n = len(x)
    z = np.arctanh(np.clip(r, -0.999999, 0.999999))
    se = 1 / math.sqrt(n - 3)
    zc = stats.norm.ppf(1 - alpha / 2)
    return {"r": r, "p_value": float(p), "ci_low": float(np.tanh(z - zc * se)),
            "ci_high": float(np.tanh(z + zc * se)), "n": n}


# ---------------------------------------------------------------------------
# Survival
# ---------------------------------------------------------------------------

def kaplan_meier(durations: np.ndarray, events: np.ndarray) -> dict:
    """Kaplan-Meier survival estimate. durations in periods, events 1 = churned, 0 = censored."""
    durations = np.asarray(durations)
    events = np.asarray(events)
    times = np.unique(durations[events == 1])
    surv, s = [], 1.0
    for t in times:
        at_risk = (durations >= t).sum()
        d = ((durations == t) & (events == 1)).sum()
        s *= 1 - d / at_risk
        surv.append(s)
    return {"time": times, "survival": np.array(surv)}


def logrank_test(d1, e1, d2, e2) -> dict:
    """Two-group log-rank test (Mantel-Haenszel form)."""
    d1, e1, d2, e2 = map(np.asarray, (d1, e1, d2, e2))
    times = np.unique(np.concatenate([d1[e1 == 1], d2[e2 == 1]]))
    o_minus_e, var = 0.0, 0.0
    for t in times:
        n1, n2 = (d1 >= t).sum(), (d2 >= t).sum()
        o1 = ((d1 == t) & (e1 == 1)).sum()
        o2 = ((d2 == t) & (e2 == 1)).sum()
        n, o = n1 + n2, o1 + o2
        if n < 2:
            continue
        o_minus_e += o1 - o * n1 / n
        var += o * (n1 / n) * (n2 / n) * (n - o) / (n - 1)
    chi2 = o_minus_e ** 2 / var
    return {"chi2": chi2, "p_value": float(1 - stats.chi2.cdf(chi2, 1))}


def fmt_p(p: float) -> str:
    """p-values for reports: '< 0.001' instead of a misleading 0."""
    return "< 0.001" if p < 0.001 else f"{p:.3f}"
