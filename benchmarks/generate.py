"""Generate deterministic benchmark datasets (not committed; see .gitignore).

    uv run python benchmarks/generate.py 1000000 10000000
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import polars as pl

OUT = Path(__file__).parent / "data"


def make(n: int, seed: int = 42) -> pl.DataFrame:
    """Ten columns: ints, floats (2% null), float32, categoricals, a high-cardinality string, timestamps, bools."""
    rng = np.random.default_rng(seed)
    amount = rng.lognormal(3, 1, n)
    amount[rng.random(n) < 0.02] = np.nan
    return pl.DataFrame({
        "id": np.arange(n, dtype=np.int64),
        "user_id": rng.integers(0, n // 10 + 1, n),
        "amount": amount,
        "score": rng.normal(0, 1, n).astype(np.float32),
        "qty": rng.integers(1, 20, n).astype(np.int32),
        "status": rng.choice(["new", "paid", "shipped", "cancelled", "refunded"], n, p=[.2, .3, .35, .1, .05]),
        "country": rng.choice(["MY", "SG", "AE", "SA", "DE", "GB", "US", "IN", "ID", "EG"], n),
        "email": pl.Series("e", rng.integers(0, n, n)).cast(pl.String),
        "ts": (np.datetime64("2026-01-01") + rng.integers(0, 300 * 86400, n).astype("timedelta64[s]")).astype("datetime64[us]"),
        "flag": rng.random(n) < 0.3,
    }).with_columns(pl.col("amount").fill_nan(None), ("u" + pl.col("email") + "@example.com").alias("email"))


def edit(df: pl.DataFrame, seed: int = 7) -> pl.DataFrame:
    """Version 2: 1% of amounts changed, 0.5% rows removed, 0.5% rows added."""
    rng = np.random.default_rng(seed)
    n = df.height
    changed = pl.Series(rng.random(n) < 0.01)
    removed = pl.Series(rng.random(n) < 0.005)
    v2 = df.with_columns(pl.when(changed).then(pl.col("amount") * 1.5).otherwise(pl.col("amount")).alias("amount"))
    v2 = v2.filter(~removed)
    extra = df.sample(n=n // 200, seed=seed).with_columns((pl.col("id") + n).alias("id"))
    return pl.concat([v2, extra])


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for arg in sys.argv[1:] or ["1000000"]:
        n = int(arg)
        tag = f"{n // 1_000_000}m" if n >= 1_000_000 else f"{n // 1000}k"
        df = make(n)
        df.write_parquet(OUT / f"v1_{tag}.parquet")
        df.write_csv(OUT / f"v1_{tag}.csv")
        edit(df).write_parquet(OUT / f"v2_{tag}.parquet")
        print(f"{tag}: {df.height} rows, {df.width} columns")


if __name__ == "__main__":
    main()
