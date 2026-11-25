"""Large-file tests. Run with: uv run pytest -m slow"""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

import datapassport as dp

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def big(tmp_path_factory) -> tuple:
    d = tmp_path_factory.mktemp("big")
    rng = np.random.default_rng(1)
    n = 3_000_000
    df = pl.DataFrame({"id": np.arange(n), "x": rng.normal(size=n), "s": rng.choice(["a", "b", "c"], n)})
    df.write_parquet(d / "a.parquet")
    df.sample(fraction=1, shuffle=True, seed=2).write_csv(d / "shuffled.csv")
    return d, n


def test_large_formats_and_order_agree(big) -> None:
    d, n = big
    a = dp.fingerprint(d / "a.parquet")
    b = dp.fingerprint(d / "shuffled.csv")
    assert a.rows == n
    assert a.dataset == b.dataset


def test_large_csv_under_memory_limit(big) -> None:
    d, n = big
    p = dp.inspect(d / "shuffled.csv", key="id", engine=dp.Engine(memory_limit="300MB"))
    assert p.rows == n and p.duplicates.key.duplicates == 0
    assert p.options.quantiles == "approx"


def test_large_sampled_profile_is_exact_and_reproducible(big) -> None:
    d, _ = big
    a = dp.inspect(d / "a.parquet", sample=200_000)
    b = dp.inspect(d / "a.parquet", sample=200_000)
    assert a.options.quantiles == "exact"
    assert a.columns["x"].numeric.quantiles == b.columns["x"].numeric.quantiles
