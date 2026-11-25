from __future__ import annotations

import datetime as dt
import decimal
import math

import duckdb
import pandas as pd
import polars as pl
import pyarrow as pa
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

import datapassport as dp
from datapassport.fingerprint import reference_fingerprint

from .conftest import write_all


def fp(obj, **kw) -> str:
    return dp.fingerprint(obj, **kw).dataset


# ------------------------------------------------------------------ golden


GOLDEN_TABLE = pl.DataFrame(
    {
        "i": [1, -2, None, 2**40],
        "f": [0.1, -0.0, float("nan"), 1e300],
        "s": ["a", "", None, "ü~:1"],
        "b": [True, False, None, True],
        "d": [dt.date(2026, 1, 1), None, dt.date(1969, 12, 31), dt.date(2000, 2, 29)],
        "t": [dt.datetime(2026, 1, 1, 12, 0, 0, 123456), None, dt.datetime(1960, 1, 1), dt.datetime(2026, 11, 25)],
    }
)

# Pinned values. If these change, the fingerprint spec changed: bump SPEC
# ("dp-fp/2"), document it in docs/fingerprint-spec.md and the changelog.
GOLDEN = {
    17: "8f08565fa552d7d3b06d182704ebdd4c6c9fc84f001d22b350cd4fddf260bde0",
    6: "87dd66f0789360436f9aef1378b9ee7d82ebd79ec5be59196163c910e4e4de11",
}


@pytest.mark.parametrize("digits", [17, 6])
def test_golden_vectors(digits: int) -> None:
    got = fp(GOLDEN_TABLE, float_digits=digits)
    assert got == GOLDEN[digits], f"fingerprint for float_digits={digits} changed: {got}"


def test_matches_reference_on_golden() -> None:
    schema = [("i", "integer"), ("f", "float"), ("s", "string"), ("b", "boolean"), ("d", "date"), ("t", "timestamp")]
    ref = reference_fingerprint(schema, GOLDEN_TABLE.rows())
    assert ref.dataset == fp(GOLDEN_TABLE)


# -------------------------------------------------------------- invariances


def test_same_content_any_format(orders: pl.DataFrame, tmp_path) -> None:
    paths = write_all(orders, tmp_path)
    expected = fp(orders)
    assert fp(paths["parquet"]) == expected
    assert fp(paths["csv"]) == expected
    assert fp(orders.to_pandas(use_pyarrow_extension_array=True)) == expected
    assert fp(orders.to_arrow()) == expected
    assert fp(orders.lazy()) == expected


def test_numpy_pandas_turns_dates_into_timestamps(orders: pl.DataFrame) -> None:
    # Documented limitation: NumPy-backed pandas has no date type, so the
    # logical type (and fingerprint) differs. Arrow-backed pandas keeps dates.
    p = dp.inspect(orders.to_pandas())
    assert p.types["day"] == "timestamp"
    assert p.columns["amount"].nulls == 1  # NaN from pandas is read as missing


def test_jsonl_matches_when_types_match(orders: pl.DataFrame, tmp_path) -> None:
    # JSON has no date type: DuckDB reads ISO dates as DATE when it can.
    paths = write_all(orders, tmp_path)
    assert fp(paths["jsonl"]) == fp(orders)


def test_row_order_is_ignored(orders: pl.DataFrame) -> None:
    assert fp(orders) == fp(orders.reverse()) == fp(orders.sample(fraction=1, shuffle=True, seed=1))


def test_column_order_is_ignored(orders: pl.DataFrame) -> None:
    assert fp(orders) == fp(orders.select(reversed(orders.columns)))


def test_integer_width_is_ignored() -> None:
    a = pl.DataFrame({"x": pl.Series([1, 2, 3], dtype=pl.Int8)})
    b = pl.DataFrame({"x": pl.Series([1, 2, 3], dtype=pl.UInt64)})
    assert fp(a) == fp(b)


def test_duplicates_count() -> None:
    a = pl.DataFrame({"x": [1, 2]})
    assert fp(a) != fp(pl.DataFrame({"x": [1, 2, 2]}))
    assert fp(pl.DataFrame({"x": [1, 1, 2]})) != fp(pl.DataFrame({"x": [1, 2, 2]}))


def test_types_are_bound() -> None:
    assert fp(pl.DataFrame({"x": [1]})) != fp(pl.DataFrame({"x": ["1"]}))
    assert fp(pl.DataFrame({"x": [1]})) != fp(pl.DataFrame({"x": [1.0]}))


def test_null_empty_and_sentinel_strings_differ() -> None:
    vals = [None, "", "~", "0:", "1:~"]
    fps = {fp(pl.DataFrame({"x": [v]}, schema={"x": pl.String})) for v in vals}
    assert len(fps) == len(vals)


def test_field_boundaries_are_unambiguous() -> None:
    a = pl.DataFrame({"a": ["ab"], "b": ["c"]})
    b = pl.DataFrame({"a": ["a"], "b": ["bc"]})
    assert fp(a) != fp(b)


def test_negative_zero_and_nan() -> None:
    assert fp(pl.DataFrame({"x": [0.0]})) == fp(pl.DataFrame({"x": [-0.0]}))
    assert fp(pl.DataFrame({"x": [float("nan")]})) == fp(pl.DataFrame({"x": [float("nan")]}))
    assert fp(pl.DataFrame({"x": [float("nan")]})) != fp(pl.DataFrame({"x": [None]}, schema={"x": pl.Float64}))


def test_float_digits_tolerates_noise() -> None:
    a = pl.DataFrame({"x": [0.1 + 0.2]})
    b = pl.DataFrame({"x": [0.3]})
    assert fp(a) != fp(b)
    assert fp(a, float_digits=15) == fp(b, float_digits=15)


def test_float32_vs_float64() -> None:
    a = pl.DataFrame({"x": pl.Series([0.1, 2.5], dtype=pl.Float32)})
    b = pl.DataFrame({"x": pl.Series([0.1, 2.5], dtype=pl.Float64)})
    # Stored values differ (0.1 is not representable the same way)...
    assert fp(a) != fp(b)
    # ...but agree at float32 precision.
    assert fp(a, float_digits=7) == fp(b, float_digits=7)


def test_decimal_scale_is_normalised() -> None:
    con = duckdb.connect()
    a = dp.fingerprint(dp.sql("SELECT 1.50::DECIMAL(10,2) AS x UNION ALL SELECT 2::DECIMAL(10,2)", con))
    b = dp.fingerprint(dp.sql("SELECT 1.5::DECIMAL(18,4) AS x UNION ALL SELECT 2.0::DECIMAL(18,4)", con))
    assert a.dataset == b.dataset


def test_timestamp_units_and_timezones() -> None:
    us = pl.DataFrame({"t": [dt.datetime(2026, 1, 1, 1, 2, 3)]})
    ns = us.with_columns(pl.col("t").cast(pl.Datetime("ns")))
    ms = us.with_columns(pl.col("t").cast(pl.Datetime("ms")))
    assert fp(us) == fp(ns) == fp(ms)
    utc = us.with_columns(pl.col("t").dt.replace_time_zone("UTC"))
    kl = utc.with_columns(pl.col("t").dt.convert_time_zone("Asia/Kuala_Lumpur"))
    assert fp(utc) == fp(kl)  # same instant
    assert fp(utc) != fp(us)  # aware vs naive are different types


def test_nanoseconds_are_kept() -> None:
    a = pl.DataFrame({"t": pl.Series([1_000_000_000_000_000_001], dtype=pl.Datetime("ns"))})
    b = pl.DataFrame({"t": pl.Series([1_000_000_000_000_000_002], dtype=pl.Datetime("ns"))})
    assert fp(a) != fp(b)


def test_unicode_column_names_normalised() -> None:
    nfc = pl.DataFrame({"café": [1]})
    nfd = pl.DataFrame({"café": [1]})
    assert fp(nfc) == fp(nfd)


def test_nested_values() -> None:
    a = pl.DataFrame({"x": [[1, 2], [3]], "s": [{"a": 1, "b": "x"}, {"a": 2, "b": None}]})
    assert fp(a) == fp(a.reverse())
    b = pl.DataFrame({"x": [[2, 1], [3]], "s": [{"a": 1, "b": "x"}, {"a": 2, "b": None}]})
    assert fp(a) != fp(b)  # list order is content


def test_empty_table() -> None:
    e = pl.DataFrame({"x": pl.Series([], dtype=pl.Int64)})
    f = dp.fingerprint(e)
    assert f.rows == 0
    assert f.dataset != fp(pl.DataFrame({"y": pl.Series([], dtype=pl.Int64)}))


def test_column_fingerprints_ignore_names() -> None:
    a = dp.fingerprint(pl.DataFrame({"x": [1, 2, 3]}))
    b = dp.fingerprint(pl.DataFrame({"renamed": [3, 2, 1]}))
    assert a.columns["x"] == b.columns["renamed"]


# ------------------------------------------------------------ properties

scalars = {
    "integer": st.integers(min_value=-(2**63), max_value=2**63 - 1),
    "float": st.floats(allow_nan=True, allow_infinity=True, width=64),
    "string": st.text(max_size=12),
    "boolean": st.booleans(),
    "date": st.dates(min_value=dt.date(1, 1, 1), max_value=dt.date(9999, 12, 31)),
    "timestamp": st.datetimes(min_value=dt.datetime(1700, 1, 1), max_value=dt.datetime(2200, 1, 1)),
    "decimal": st.decimals(min_value=-(10**6), max_value=10**6, places=3, allow_nan=False, allow_infinity=False),
}
_pa_types = {
    "integer": pa.int64(),
    "float": pa.float64(),
    "string": pa.string(),
    "boolean": pa.bool_(),
    "date": pa.date32(),
    "timestamp": pa.timestamp("us"),
    "decimal": pa.decimal128(12, 3),
}


@st.composite
def tables(draw):
    kinds = draw(st.lists(st.sampled_from(sorted(scalars)), min_size=1, max_size=4))
    names = draw(
        st.lists(
            st.text(st.characters(exclude_characters="\x00", exclude_categories=["Cs"]), min_size=1, max_size=5),
            min_size=len(kinds),
            max_size=len(kinds),
            unique_by=lambda s: __import__("unicodedata").normalize("NFC", s),
        )
    )
    nrows = draw(st.integers(0, 12))
    rows = [tuple(draw(st.one_of(st.none(), scalars[k])) for k in kinds) for _ in range(nrows)]
    return list(zip(names, kinds, strict=True)), rows


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(tables())
def test_sql_matches_reference(table) -> None:
    schema, rows = table
    arrays = [pa.array([r[i] for r in rows], type=_pa_types[k]) for i, (_, k) in enumerate(schema)]
    tbl = pa.Table.from_arrays(arrays, names=[n for n, _ in schema])
    got = dp.fingerprint(tbl)
    ref = reference_fingerprint(schema, rows)
    assert got.rows == ref.rows
    assert got.dataset == ref.dataset


@settings(max_examples=60, deadline=None)
@given(st.lists(st.tuples(st.integers(-5, 5), st.sampled_from(["a", "b", None])), max_size=30), st.randoms())
def test_permutation_invariance(rows, rnd) -> None:
    shuffled = rows[:]
    rnd.shuffle(shuffled)
    mk = lambda rs: pl.DataFrame(rs, schema={"n": pl.Int64, "s": pl.String}, orient="row")
    assert fp(mk(rows)) == fp(mk(shuffled))


def test_reference_float_format_agrees_with_python() -> None:
    # The SQL uses fmt's '{:.17g}'; the reference uses Python's format(). Spot-check edge values.
    for v in [5e-324, 1.7976931348623157e308, 1e16, 1e-7, 123456789012345678.0, 2.5, -1.5e-10]:
        sql = duckdb.sql(f"SELECT format('{{:.17g}}', {v!r}::DOUBLE)").fetchall()[0][0]
        assert sql == format(v, ".17g"), v
    assert not math.isnan(1.0)


def test_pandas_and_decimal_reference() -> None:
    df = pd.DataFrame({"d": [decimal.Decimal("1.100"), decimal.Decimal("-0.5")]})
    got = dp.fingerprint(pa.Table.from_pandas(df, schema=pa.schema([("d", pa.decimal128(10, 3))])))
    ref = reference_fingerprint([("d", "decimal")], [(decimal.Decimal("1.1"),), (decimal.Decimal("-0.50"),)])
    assert got.dataset == ref.dataset
