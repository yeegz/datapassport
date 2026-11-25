from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from datapassport.drift import cdf, numeric_drift

P = [i / 100 for i in range(101)]


def qs(x: np.ndarray) -> list[float]:
    return list(np.quantile(x, P))


def exact_ks(a: np.ndarray, b: np.ndarray) -> float:
    pts = np.sort(np.concatenate([a, b]))
    fa = np.searchsorted(np.sort(a), pts, side="right") / len(a)
    fb = np.searchsorted(np.sort(b), pts, side="right") / len(b)
    return float(np.max(np.abs(fa - fb)))


@pytest.mark.parametrize("shift", [0.0, 0.1, 0.3, 1.0])
def test_ks_close_to_exact(shift: float) -> None:
    rng = np.random.default_rng(int(shift * 10))
    a, b = rng.normal(0, 1, 10_000), rng.normal(shift, 1, 10_000)
    approx = numeric_drift(qs(a), qs(b))["ks"]
    assert abs(approx - exact_ks(a, b)) < 0.02


def test_wasserstein_matches_location_shift() -> None:
    rng = np.random.default_rng(1)
    a = rng.normal(0, 1, 50_000)
    d = numeric_drift(qs(a), qs(a + 2.0))
    assert d["wasserstein"] == pytest.approx(2.0, rel=0.01)


def test_identical_is_zero() -> None:
    a = list(np.quantile(np.arange(100.0), P))
    d = numeric_drift(a, a)
    assert d["psi"] == pytest.approx(0, abs=1e-9) and d["ks"] == 0 and d["wasserstein"] == 0


def test_discrete_and_constant() -> None:
    a = qs(np.array([1, 1, 1, 2, 2, 3] * 100, dtype=float))
    b = qs(np.array([1, 2, 2, 2, 3, 3] * 100, dtype=float))
    d = numeric_drift(a, b)
    assert d["ks"] > 0.2
    c = qs(np.full(10, 5.0))
    assert numeric_drift(c, c)["ks"] == 0


@settings(max_examples=100, deadline=None)
@given(st.lists(st.floats(-1e6, 1e6), min_size=2, max_size=200), st.floats(-2e6, 2e6), st.floats(-2e6, 2e6))
def test_cdf_monotone_and_bounded(values, x, y) -> None:
    q = qs(np.array(values))
    lo, hi = sorted([x, y])
    assert 0.0 <= cdf(q, lo) <= cdf(q, hi) <= 1.0
