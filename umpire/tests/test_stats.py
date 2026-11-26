import math

import pytest

from third_umpire import stats


def test_chi_squared_survival_matches_critical_values():
    assert stats.chi_squared_survival(3.841458820694124, 1) == pytest.approx(0.05, abs=1e-9)
    assert stats.chi_squared_survival(5.991464547107979, 2) == pytest.approx(0.05, abs=1e-9)
    assert stats.chi_squared_survival(10.827566170662733, 1) == pytest.approx(0.001, abs=1e-9)
    assert stats.chi_squared_survival(0, 3) == 1.0


def test_srm_balanced_and_skewed():
    assert stats.srm({"control": 500, "near_miss": 500}, {"control": 0.5, "near_miss": 0.5}).p_value == 1.0
    skewed = stats.srm({"control": 400, "near_miss": 600}, {"control": 0.5, "near_miss": 0.5})
    assert skewed.statistic == pytest.approx(40.0)
    assert skewed.p_value < 1e-9


def test_srm_is_undefined_without_a_split():
    assert stats.srm({"control": 10}, {"control": 1.0}) is None
    assert stats.srm({"control": 10, "b": 5}, {"control": 1.0, "b": 0.0}) is None
    assert stats.srm({}, {"control": 0.5, "b": 0.5}) is None


def test_compare_uses_flagsmith_delta_method():
    control = stats.VariantStats(n=400, sum=140, sum_squares=140)
    treatment = stats.VariantStats(n=400, sum=180, sum_squares=180)
    inf = stats.compare(control, treatment)
    assert inf.lift == pytest.approx((0.45 - 0.35) / 0.35)
    var = treatment.variance / (400 * 0.35**2) + 0.45**2 * control.variance / (400 * 0.35**4)
    se = math.sqrt(var)
    assert inf.ci_low == pytest.approx(inf.lift - stats.Z_95 * se)
    assert inf.ci_high == pytest.approx(inf.lift + stats.Z_95 * se)
    assert 0.99 < inf.chance_to_win < 1.0


def test_compare_lower_is_better_flips_chance():
    control = stats.VariantStats(n=400, sum=80, sum_squares=80)
    worse = stats.VariantStats(n=400, sum=120, sum_squares=120)
    up = stats.compare(control, worse)
    down = stats.compare(control, worse, lower_is_better=True)
    assert down.chance_to_win == pytest.approx(1 - up.chance_to_win)
    assert down.lift == up.lift


def test_compare_needs_two_observations_and_positive_control():
    assert stats.compare(stats.VariantStats(1, 1, 1), stats.VariantStats(10, 5, 5)) is None
    assert stats.compare(stats.VariantStats(10, 0, 0), stats.VariantStats(10, 5, 5)) is None
