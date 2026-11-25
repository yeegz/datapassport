from __future__ import annotations

import json

import numpy as np
import polars as pl
import pytest

import datapassport as dp


def test_basic_profile(orders: pl.DataFrame) -> None:
    p = dp.inspect(orders, key="id")
    assert p.rows == 6
    assert p.column_names == ["id", "status", "amount", "city", "day"]
    s = p.columns["status"]
    assert (s.nulls, s.count, s.distinct) == (1, 5, 3)
    a = p.columns["amount"].numeric
    assert a is not None
    assert (a.min, a.max, a.zeros, a.negatives) == (-3.5, 20.0, 1, 1)
    assert a.mean == pytest.approx(np.mean([10.5, 20.0, 7.25, 0.0, -3.5]))
    assert len(a.quantiles) == 101
    assert p.columns["city"].text.empty == 1
    assert p.columns["day"].temporal.min == "2026-01-01"
    assert p.duplicates.key.duplicates == 0


def test_quantiles_match_numpy(big_orders: pl.DataFrame) -> None:
    p = dp.inspect(big_orders)
    q = p.columns["amount"].numeric.quantiles
    exp = np.quantile(big_orders["amount"].to_numpy(), [i / 100 for i in range(101)])
    assert np.allclose(q, exp)


def test_safe_mode_has_no_raw_values(orders: pl.DataFrame) -> None:
    text = dp.inspect(orders).to_json()
    for raw in ["Zürich", "東京", "Kuala Lumpur", "shipped"]:
        assert raw not in text
    html = dp.inspect(orders).to_html()
    assert "Zürich" not in html and "shipped" not in html


def test_values_mode_includes_top_values(orders: pl.DataFrame) -> None:
    p = dp.inspect(orders, privacy="values")
    assert p.columns["status"].categories.values[0] == "paid"


def test_sensitive_columns_are_withheld(orders: pl.DataFrame) -> None:
    p = dp.inspect(orders, sensitive=["amount", "status"], privacy="values")
    assert p.columns["amount"].numeric is None
    assert p.columns["status"].categories is None
    assert p.columns["amount"].sensitive
    assert "20.0" not in json.dumps(p.to_dict()["columns"]["amount"])


def test_duplicates_and_key_stats() -> None:
    df = pl.DataFrame({"k": [1, 1, 2, None], "v": ["a", "a", "b", "c"]})
    p = dp.inspect(df, key="k")
    assert p.duplicates.rows == 1
    assert p.duplicates.key.duplicates == 1
    assert p.duplicates.key.nulls == 1


def test_sampling_is_deterministic_and_close(big_orders: pl.DataFrame) -> None:
    a = dp.inspect(big_orders, sample=2000, seed=1)
    b = dp.inspect(big_orders, sample=2000, seed=1)
    full = dp.inspect(big_orders)
    assert a.sample.method == "hash"
    assert 1500 < a.sample.rows_profiled < 2500
    assert a.columns["amount"].numeric.mean == b.columns["amount"].numeric.mean
    assert a.fingerprint.dataset == full.fingerprint.dataset  # fingerprint covers all rows
    assert a.columns["amount"].numeric.mean == pytest.approx(full.columns["amount"].numeric.mean, rel=0.02)


def test_sampling_is_content_addressed(big_orders: pl.DataFrame) -> None:
    # The same row is sampled whatever order the data comes in.
    a = dp.inspect(big_orders, sample=0.1)
    b = dp.inspect(big_orders.reverse(), sample=0.1)
    assert a.sample.rows_profiled == b.sample.rows_profiled
    assert a.columns["amount"].numeric.quantiles == b.columns["amount"].numeric.quantiles


def test_identifier_columns_have_no_categories() -> None:
    df = pl.DataFrame({"email": [f"u{i}@x.org" for i in range(5000)]})
    assert dp.inspect(df).columns["email"].categories is None


def test_extreme_values() -> None:
    df = pl.DataFrame({"x": [1e308, -1e308, float("inf"), float("-inf"), float("nan"), 0.0, None]})
    n = dp.inspect(df).columns["x"].numeric
    assert n.nan == 1 and n.infinite == 2
    assert n.max == 1e308 and n.min == -1e308


def test_all_null_and_empty() -> None:
    df = pl.DataFrame({"x": pl.Series([None, None], dtype=pl.Int64), "y": pl.Series([None, None], dtype=pl.String)})
    p = dp.inspect(df)
    assert p.columns["x"].null_fraction == 1.0
    assert p.columns["x"].numeric.quantiles == []
    e = dp.inspect(pl.DataFrame({"x": pl.Series([], dtype=pl.Float64)}))
    assert e.rows == 0 and e.columns["x"].null_fraction == 0.0


def test_nested_columns(tmp_path) -> None:
    path = tmp_path / "n.json"
    path.write_text(json.dumps([{"a": 1, "tags": ["x", "y"], "meta": {"k": 1}}, {"a": 2, "tags": [], "meta": None}]))
    p = dp.inspect(path)
    assert p.types["tags"] == "list<string>"
    assert p.types["meta"].startswith("struct<")
    assert p.columns["meta"].nulls == 1


def test_custom_metric(orders: pl.DataFrame) -> None:
    @dp.metric("share_negative", types=["float", "integer"])
    def share_negative(ctx: dp.MetricContext) -> float:
        return float(ctx.scalar(f"avg(CASE WHEN {ctx.col} < 0 THEN 1.0 ELSE 0.0 END)"))

    try:
        p = dp.inspect(orders)
        assert p.columns["amount"].extras["share_negative"] == pytest.approx(1 / 6)  # nulls count as not negative
        assert "share_negative" not in p.columns["status"].extras
    finally:
        from datapassport.plugins import unregister

        unregister("share_negative")


def test_passport_roundtrip(orders: pl.DataFrame, tmp_path) -> None:
    p = dp.inspect(orders, key="id")
    path = tmp_path / "p.json"
    p.to_json(path)
    q = dp.load(str(path))
    assert q.fingerprint.dataset == p.fingerprint.dataset
    assert q.to_dict() == p.to_dict()


def test_json_schema_available() -> None:
    schema = dp.Passport.model_json_schema(by_alias=True)
    assert "fingerprint" in schema["properties"]


def test_column_table(orders: pl.DataFrame) -> None:
    t = dp.inspect(orders).column_table()
    assert t.height == 5 and "null_fraction" in t.columns
