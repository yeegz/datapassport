"""Generate the example datasets used in the README, notebooks and docs.

Deterministic: the same seed always produces the same files.

    uv run python examples/make_data.py
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import polars as pl

OUT = Path(__file__).parent / "data"


def orders(n: int, seed: int, *, price_shift: float = 0.0, new_status: bool = False) -> pl.DataFrame:
    rng = np.random.default_rng(seed)
    statuses = ["new", "paid", "shipped", "cancelled"] + (["refunded"] if new_status else [])
    weights = np.array([0.2, 0.35, 0.4, 0.05] + ([0.08] if new_status else []))
    start = dt.datetime(2026, 10, 1)
    return pl.DataFrame({
        "order_id": np.arange(1, n + 1),
        "customer_email": [f"user{int(i)}@example.com" for i in rng.integers(1, n // 3 + 2, n)],
        "status": rng.choice(statuses, n, p=weights / weights.sum()),
        "amount": np.round(rng.lognormal(3.2 + price_shift, 0.6, n), 2),
        "quantity": rng.integers(1, 6, n),
        "created_at": [start + dt.timedelta(minutes=int(m)) for m in rng.integers(0, 60 * 24 * 31, n)],
        "country": rng.choice(["MY", "SG", "AE", "SA", "DE", "GB"], n),
    })


def main() -> None:
    OUT.mkdir(exist_ok=True)
    v1 = orders(5_000, seed=1)
    v1.write_csv(OUT / "orders_v1.csv")
    v1.write_parquet(OUT / "orders_v1.parquet")
    # v2: 2% of amounts edited, 100 rows removed, 300 rows added, a new status value,
    # a renamed column, prices drifted upwards for new rows.
    rng = np.random.default_rng(2)
    edit = rng.choice(v1.height, 100, replace=False)
    v2 = v1.with_columns(
        pl.when(pl.int_range(pl.len()).is_in(edit.tolist())).then(pl.col("amount") * 1.1)
        .otherwise(pl.col("amount")).round(2).alias("amount")
    ).filter(~pl.col("order_id").is_in(list(range(1, 101))))
    extra = orders(300, seed=3, price_shift=0.8, new_status=True).with_columns(pl.col("order_id") + 5_000)
    v2 = pl.concat([v2, extra]).rename({"country": "country_code"})
    v2.write_parquet(OUT / "orders_v2.parquet")
    print(f"wrote {OUT}: orders_v1.csv, orders_v1.parquet ({v1.height} rows), orders_v2.parquet ({v2.height} rows)")


if __name__ == "__main__":
    main()
