"""Check the hand-written statistics against scipy / statsmodels reference implementations."""

import numpy as np
import pytest
from scipy import stats
from statsmodels.stats.power import NormalIndPower
from statsmodels.stats.proportion import proportion_effectsize, proportions_ztest

from analysis import stats_utils as su


def test_two_proportion_matches_statsmodels():
    r = su.two_proportion_test(400, 1000, 460, 1000)
    z, p = proportions_ztest([460, 400], [1000, 1000])
    assert r["z"] == pytest.approx(z, rel=1e-9)
    assert r["p_value"] == pytest.approx(p, rel=1e-9)


def test_chi_square_equals_z_squared_for_2x2():
    r = su.chi_square_independence(np.array([[400, 600], [460, 540]]))
    z = su.two_proportion_test(400, 1000, 460, 1000)["z"]
    assert r["chi2"] == pytest.approx(z ** 2, rel=1e-9)


def test_welch_matches_scipy():
    rng = np.random.default_rng(0)
    a, b = rng.normal(10, 2, 300), rng.normal(10.5, 3, 250)
    r = su.welch_t_test(a, b)
    ref = stats.ttest_ind(b, a, equal_var=False)
    assert r["t"] == pytest.approx(ref.statistic, rel=1e-9)
    assert r["p_value"] == pytest.approx(ref.pvalue, rel=1e-9)


def test_sample_size_close_to_statsmodels():
    n = su.sample_size_two_proportions(0.30, 0.02)
    es = proportion_effectsize(0.32, 0.30)
    ref = NormalIndPower().solve_power(es, alpha=0.05, power=0.8)
    assert abs(n - ref) / ref < 0.02


def test_holm_is_monotone_and_bounded():
    out = su.holm_bonferroni([0.01, 0.04, 0.03, 0.5])
    adj = [o["p_adjusted"] for o in out]
    assert adj[0] == pytest.approx(0.04) and max(adj) <= 1.0


def test_kaplan_meier_simple_case():
    km = su.kaplan_meier(np.array([1, 2, 2, 3, 4]), np.array([1, 1, 0, 1, 0]))
    assert km["survival"][0] == pytest.approx(0.8)
    assert km["survival"][1] == pytest.approx(0.8 * 3 / 4)


def test_srm_detects_imbalance():
    assert su.srm_check(5000, 5000)["srm_detected"] is False
    assert su.srm_check(5000, 5600)["srm_detected"] is True
