from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import polars as pl
import pytest


@pytest.fixture
def orders() -> pl.DataFrame:
    """Small orders table with nulls, Unicode and a date."""
    return pl.DataFrame(
        {
            "id": [1, 2, 3, 4, 5, 6],
            "status": ["new", "paid", "paid", None, "shipped", "paid"],
            "amount": [10.5, 20.0, None, 7.25, 0.0, -3.5],
            "city": ["Kuala Lumpur", "Zürich", "東京", "São Paulo", "", "Dubai"],
            "day": [dt.date(2026, 1, d) for d in range(1, 7)],
        }
    )


@pytest.fixture
def big_orders() -> pl.DataFrame:
    rng = np.random.default_rng(7)
    n = 20_000
    return pl.DataFrame(
        {
            "id": np.arange(n),
            "amount": rng.normal(100, 15, n).round(2),
            "segment": rng.choice(["a", "b", "c", "d"], n, p=[0.4, 0.3, 0.2, 0.1]),
            "qty": rng.integers(1, 10, n),
        }
    )


def write_all(df: pl.DataFrame, tmp: Path, stem: str = "t") -> dict[str, Path]:
    paths = {
        "csv": tmp / f"{stem}.csv",
        "parquet": tmp / f"{stem}.parquet",
        "jsonl": tmp / f"{stem}.jsonl",
    }
    df.write_csv(paths["csv"])
    df.write_parquet(paths["parquet"])
    df.write_ndjson(paths["jsonl"])
    return paths
