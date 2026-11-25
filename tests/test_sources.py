from __future__ import annotations

import gzip
import json

import duckdb
import polars as pl
import pytest

import datapassport as dp
from datapassport.sources import FileSource


def test_missing_file_suggests(tmp_path) -> None:
    (tmp_path / "orders.csv").write_text("a\n1\n")
    with pytest.raises(dp.SourceError) as e:
        dp.inspect(tmp_path / "ordres.csv")
    assert "orders.csv" in str(e.value.hint)


def test_unknown_format(tmp_path) -> None:
    (tmp_path / "x.dat").write_text("a\n1\n")
    with pytest.raises(dp.SourceError, match="format"):
        dp.inspect(tmp_path / "x.dat")
    assert dp.inspect(tmp_path / "x.dat", format="csv").rows == 1


def test_directory_and_glob_of_parquet(tmp_path, orders) -> None:
    d = tmp_path / "parts"
    d.mkdir()
    orders.head(3).write_parquet(d / "a.parquet")
    orders.tail(3).write_parquet(d / "b.parquet")
    assert dp.fingerprint(d).dataset == dp.fingerprint(orders).dataset
    assert dp.fingerprint(str(d / "*.parquet")).dataset == dp.fingerprint(orders).dataset
    assert dp.inspect(d).source.files == 2


def test_tsv_gzip_and_options(tmp_path) -> None:
    (tmp_path / "x.tsv").write_text("a\tb\n1\tx\n2\ty\n")
    assert dp.inspect(tmp_path / "x.tsv").column_names == ["a", "b"]
    with gzip.open(tmp_path / "y.csv.gz", "wt") as fh:
        fh.write("a;b\n1;x\n")
    p = dp.inspect(tmp_path / "y.csv.gz", read_options={"delim": ";"})
    assert p.column_names == ["a", "b"]
    assert p.source.read_options["delim"] == ";"


def test_json_array_and_jsonl(tmp_path) -> None:
    rows = [{"a": 1, "b": "x"}, {"a": 2, "b": None}]
    (tmp_path / "x.json").write_text(json.dumps(rows))
    (tmp_path / "x.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    assert dp.fingerprint(tmp_path / "x.json").dataset == dp.fingerprint(tmp_path / "x.jsonl").dataset


def test_malformed_csv_has_hint(tmp_path) -> None:
    lines = ["a,b"] + [f"{i},{i}" for i in range(30000)] + ["oops,1"]
    (tmp_path / "bad.csv").write_text("\n".join(lines))
    # DuckDB may fail with a hint or widen the type; either is fine. Silently dropping the row is not.
    hint = None
    try:
        rows = dp.inspect(tmp_path / "bad.csv").rows
    except dp.SourceError as e:
        rows, hint = None, e.hint
    assert rows == 30001 or (hint and "sample_size" in hint)
    p = dp.inspect(tmp_path / "bad.csv", read_options={"all_varchar": True})
    assert p.types["a"] == "string"


def test_ragged_csv_is_never_silently_truncated(tmp_path) -> None:
    (tmp_path / "r.csv").write_text("a,b\n1,2\n3\n4,5,6\n")
    with pytest.raises(dp.SourceError, match="different numbers of fields") as e:
        dp.inspect(tmp_path / "r.csv")
    assert "delim" in e.value.hint


def test_csv_preamble_needs_explicit_skip(tmp_path) -> None:
    (tmp_path / "p.csv").write_text("exported 2026-11-25\na,b\n1,2\n")
    assert dp.inspect(tmp_path / "p.csv", read_options={"skip": 1}).column_names == ["a", "b"]


def test_sql_source_on_own_connection() -> None:
    con = duckdb.connect()
    con.execute("CREATE TABLE t AS SELECT range AS x FROM range(10)")
    assert dp.inspect(dp.sql("t", con=con)).rows == 10
    assert dp.inspect(dp.sql("SELECT * FROM t WHERE x < 3", con=con)).rows == 3


def test_register_custom_source() -> None:
    class Rows:
        def __init__(self, rows):
            self.rows = rows

    class RowsSource:
        kind = "rows"

        def __init__(self, obj, **_):
            self.obj = obj

        def register(self, con, name):
            tbl = pl.DataFrame(self.obj.rows).to_arrow()
            con.register(name + "_src", tbl)
            con.execute(f'CREATE TEMP VIEW "{name}" AS SELECT * FROM "{name}_src"')
            return dp.SourceInfo(kind="rows")

    dp.register_source("rows", lambda o: isinstance(o, Rows), RowsSource)
    p = dp.inspect(Rows([{"a": 1}, {"a": 2}]))
    assert p.rows == 2 and p.source.kind == "rows"


def test_unknown_object() -> None:
    with pytest.raises(dp.SourceError, match="Don't know how to read"):
        dp.inspect(object())


def test_byte_hash_recorded(tmp_path, orders) -> None:
    orders.write_parquet(tmp_path / "o.parquet")
    p = dp.inspect(tmp_path / "o.parquet")
    import hashlib

    assert p.source.sha256 == hashlib.sha256((tmp_path / "o.parquet").read_bytes()).hexdigest()


def test_duplicate_column_names(tmp_path) -> None:
    (tmp_path / "d.csv").write_text("a,a\n1,2\n")
    # DuckDB renames the second column, so this reads fine.
    assert len(dp.inspect(tmp_path / "d.csv").columns) == 2


def test_verify(tmp_path, orders) -> None:
    orders.write_csv(tmp_path / "o.csv")
    p = dp.inspect(tmp_path / "o.csv")
    assert dp.verify(p, orders)
    assert not dp.verify(p, orders.head(5))


def test_file_source_effective_options(tmp_path) -> None:
    (tmp_path / "x.tsv").write_text("a\n1\n")
    assert FileSource(tmp_path / "x.tsv").effective_options()["delim"] == "\t"
