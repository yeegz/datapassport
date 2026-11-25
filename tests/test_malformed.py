"""Malformed, hostile and extreme inputs."""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

import datapassport as dp


def test_corrupted_parquet(tmp_path) -> None:
    (tmp_path / "bad.parquet").write_bytes(b"PAR1 this is not parquet")
    with pytest.raises(dp.SourceError, match="parquet"):
        dp.inspect(tmp_path / "bad.parquet")


def test_invalid_json(tmp_path) -> None:
    (tmp_path / "bad.jsonl").write_text('{"a": 1}\n{"a": \n')
    with pytest.raises(dp.SourceError):
        dp.inspect(tmp_path / "bad.jsonl")


def test_empty_file(tmp_path) -> None:
    (tmp_path / "empty.csv").write_text("a,b\n")
    p = dp.inspect(tmp_path / "empty.csv")
    assert p.rows == 0


def test_hostile_column_names(tmp_path) -> None:
    # An empty column name is renamed by DuckDB (to "v<n>"), so it is not covered here.
    df = pl.DataFrame({'we"ird': [1], "drop table x;--": [2], "naïve 名字": [3]})
    p = dp.inspect(df)
    assert set(p.column_names) == set(df.columns)
    rep = dp.check(df, {"columns": {'we"ird': {"min": 0}, "drop table x;--": {"max": 5}}})
    assert rep.status == "pass"


def test_quotes_and_newlines_in_csv(tmp_path) -> None:
    df = pl.DataFrame({"t": ["a,b", "line1\nline2", 'quote " inside', "", None]})
    df.write_csv(tmp_path / "q.csv")
    assert dp.fingerprint(tmp_path / "q.csv").dataset == dp.fingerprint(df).dataset


def test_heavy_tails_and_constant_columns() -> None:
    rng = np.random.default_rng(0)
    df = pl.DataFrame({"cauchy": rng.standard_cauchy(10_000), "const": np.ones(10_000)})
    p = dp.inspect(df)
    assert p.columns["const"].numeric.std == 0
    c = dp.compare(p, dp.inspect(df.with_columns(pl.col("cauchy") * 1.0)))
    assert c.identical and c.drift["cauchy"].status == "pass"
    assert c.drift["const"].status == "pass"


def test_wide_table() -> None:
    df = pl.DataFrame({f"c{i}": np.arange(100) * i for i in range(300)})
    p = dp.inspect(df)
    assert len(p.columns) == 300
    assert dp.compare(df, df.select(reversed(df.columns))).identical


def test_mixed_types_in_json(tmp_path) -> None:
    (tmp_path / "m.jsonl").write_text('{"v": 1}\n{"v": "two"}\n{"v": null}\n{"v": [3]}\n')
    p = dp.inspect(tmp_path / "m.jsonl")
    assert p.rows == 4  # DuckDB unifies to a JSON/text type rather than dropping rows
