"""The same statistics Flagsmith's experimentation engine uses, recomputed from the
raw per-variant sums so the umpire never has to take a dashboard number on trust.

Mirrors ``api/experimentation/stats.py`` in Flagsmith/flagsmith: a delta-method
normal approximation on the relative lift, and a chi-squared test for sample
ratio mismatch.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from statistics import NormalDist

_NORMAL = NormalDist()
Z_95 = 1.959963984540054


@dataclass(frozen=True)
class VariantStats:
    n: int
    sum: float
    sum_squares: float

    @property
    def mean(self) -> float:
        return self.sum / self.n if self.n else 0.0

    @property
    def variance(self) -> float:
        if self.n < 2:
            return 0.0
        return max(0.0, (self.sum_squares - self.sum**2 / self.n) / (self.n - 1))

    @classmethod
    def from_api(cls, raw: Mapping[str, float]) -> VariantStats:
        return cls(n=int(raw["n"]), sum=float(raw["sum"]), sum_squares=float(raw["sum_squares"]))


@dataclass(frozen=True)
class Inference:
    lift: float
    ci_low: float
    ci_high: float
    chance_to_win: float

    @classmethod
    def from_api(cls, raw: Mapping[str, float] | None) -> Inference | None:
        if not raw:
            return None
        return cls(
            lift=float(raw["lift"]),
            ci_low=float(raw["ci_low"]),
            ci_high=float(raw["ci_high"]),
            chance_to_win=float(raw["chance_to_win"]),
        )


def compare(control: VariantStats, treatment: VariantStats, *, lower_is_better: bool = False) -> Inference | None:
    """Relative lift of treatment over control with a 95% interval and the
    probability that treatment is better (for a lower-is-better metric, that
    its true lift is below zero)."""
    if control.n < 2 or treatment.n < 2 or control.mean <= 0:
        return None
    lift = (treatment.mean - control.mean) / control.mean
    variance = treatment.variance / (treatment.n * control.mean**2) + (
        treatment.mean**2 * control.variance / (control.n * control.mean**4)
    )
    se = math.sqrt(variance)
    if se == 0:
        up = 0.5 if lift == 0 else float(lift > 0)
        return Inference(lift, lift, lift, 1 - up if lower_is_better else up)
    up = _NORMAL.cdf(lift / se)
    return Inference(
        lift=lift,
        ci_low=lift - Z_95 * se,
        ci_high=lift + Z_95 * se,
        chance_to_win=1 - up if lower_is_better else up,
    )


def chi_squared_survival(statistic: float, dof: int) -> float:
    """P(X >= statistic) for X ~ chi-squared(dof), exact for integer dof."""
    if statistic <= 0:
        return 1.0
    y = statistic / 2.0
    if dof % 2:
        a, survival = 0.5, math.erfc(math.sqrt(y))
    else:
        a, survival = 1.0, math.exp(-y)
    while a + 1.0 <= dof / 2.0:
        survival += math.exp(a * math.log(y) - y - math.lgamma(a + 1.0))
        a += 1.0
    return min(1.0, survival)


@dataclass(frozen=True)
class SrmTest:
    statistic: float
    p_value: float
    expected: dict[str, float]


def srm(observed: Mapping[str, int], shares: Mapping[str, float]) -> SrmTest | None:
    """Chi-squared goodness of fit of observed exposures against the configured split."""
    keys = list(shares)
    total = sum(observed.get(k, 0) for k in keys)
    if len(keys) < 2 or total == 0 or any(shares[k] <= 0 for k in keys):
        return None
    expected = {k: total * shares[k] for k in keys}
    statistic = sum((observed.get(k, 0) - expected[k]) ** 2 / expected[k] for k in keys)
    return SrmTest(statistic, chi_squared_survival(statistic, len(keys) - 1), expected)


def proportion(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def relative_lift(control_rate: float, treatment_rate: float) -> float | None:
    if control_rate <= 0:
        return None
    return (treatment_rate - control_rate) / control_rate


def max_abs_diff(a: Sequence[float], b: Sequence[float]) -> float:
    return max(abs(x - y) for x, y in zip(a, b, strict=True))
