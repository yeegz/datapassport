from __future__ import annotations

import numpy as np
import polars as pl
import pytest

import datapassport as dp


def _versions() -> tuple[pl.DataFrame, pl.DataFrame]:
    rng = np.random.default_rng(0)
    n = 1000
    a = pl.DataFrame({"id": np.arange(n), "x": rng.normal(0, 1, n), "c": rng.choice(["p", "q"], n)})
    b = a.filter(pl.col("id") >= 10)  # 10 removed
    b = b.with_columns(pl.when(pl.col("id") < 30).then(pl.col("x") + 1).otherwise(pl.col("x")).alias("x"))  # 20 changed
    b = pl.concat([b, pl.DataFrame({"id": np.arange(n, n + 5), "x": np.zeros(5), "c": ["p"] * 5})])  # 5 added
    return a, b


def test_keyed_diff_counts() -> None:
    a, b = _versions()
    c = dp.compare(a, b, key="id", examples=3)
    r = c.rows
    assert (r.added, r.removed, r.changed) == (5, 10, 20)
    assert r.unchanged == 1000 - 10 - 20
    assert r.changed_by_column == {"x": 20}
    assert r.examples["removed"] == [[0], [1], [2]]
    assert c.changed_columns == ["x"]
    assert not c.identical


def test_multiset_diff_without_key() -> None:
    a, b = _versions()
    r = dp.compare(a, b).rows
    assert r.method == "multiset"
    assert r.added == 25 and r.removed == 30  # an edit is one removal and one addition


def test_identical_ignores_order() -> None:
    a, _ = _versions()
    c = dp.compare(a, a.reverse())
    assert c.identical
    assert c.rows.added == 0 and c.rows.removed == 0


def test_schema_evolution() -> None:
    a = pl.DataFrame({"id": [1, 2, 3], "old": ["x", "y", "z"], "n": [1, 2, 3], "gone": [1, 1, 1]})
    b = pl.DataFrame({"id": [1, 2, 3], "new": ["x", "y", "z"], "n": [1.0, 2.0, 3.5], "extra": [0, 0, 0]})
    c = dp.compare(a, b, key="id")
    kinds = {(s.kind, s.column) for s in c.schema_changes}
    assert ("renamed", "old") in kinds
    assert ("removed", "gone") in kinds
    assert ("added", "extra") in kinds
    tc = next(s for s in c.schema_changes if s.kind == "type_changed")
    assert (tc.column, tc.from_type, tc.to_type, tc.breaking) == ("n", "integer", "float", False)
    assert next(s for s in c.schema_changes if s.kind == "renamed").confidence == "exact"


def test_likely_rename_when_values_also_change() -> None:
    rng = np.random.default_rng(1)
    a = pl.DataFrame({"id": np.arange(500), "country": rng.choice(["MY", "SG", "AE"], 500)})
    b = a.with_columns(
        pl.when(pl.col("id") < 5).then(pl.lit("SG")).otherwise(pl.col("country")).alias("country")
    ).rename({"country": "country_code"})
    ch = next(s for s in dp.compare(a, b).schema_changes if s.kind == "renamed")
    assert (ch.column, ch.to_column, ch.confidence) == ("country", "country_code", "likely")


def test_int_to_float_widening_does_not_mark_rows_changed() -> None:
    a = pl.DataFrame({"id": [1, 2], "v": [1, 2]})
    b = pl.DataFrame({"id": [1, 2], "v": [1.0, 2.0]})
    assert dp.compare(a, b, key="id").rows.changed == 0


def test_compare_passports_without_data(tmp_path) -> None:
    a, b = _versions()
    pa = dp.inspect(a)
    pa.to_json(tmp_path / "a.json")
    c = dp.compare(tmp_path / "a.json", b)
    assert c.rows.method == "summary"
    assert c.rows.before == 1000 and c.rows.after == 995
    assert c.changed_columns == ["id", "x", "c"] or set(c.changed_columns) >= {"x"}


def test_drift_detected_from_passports() -> None:
    rng = np.random.default_rng(2)
    a = pl.DataFrame({"x": rng.normal(0, 1, 5000), "c": rng.choice(["a", "b"], 5000, p=[0.9, 0.1])})
    b = pl.DataFrame({"x": rng.normal(1.0, 1, 5000), "c": rng.choice(["a", "b"], 5000, p=[0.5, 0.5])})
    c = dp.compare(dp.inspect(a), dp.inspect(b))
    assert c.drift["x"].status == "fail"
    assert c.drift["c"].status == "fail"
    same = dp.compare(dp.inspect(a), dp.inspect(a.sample(fraction=1, shuffle=True, seed=3)))
    assert all(d.status == "pass" for d in same.drift.values())


def test_drift_thresholds_configurable() -> None:
    rng = np.random.default_rng(3)
    a = pl.DataFrame({"x": rng.normal(0, 1, 5000)})
    b = pl.DataFrame({"x": rng.normal(0.15, 1, 5000)})
    loose = dp.compare(a, b, drift={"x": {"metric": "ks", "fail": 0.5, "warn": 0.4}})
    tight = dp.compare(a, b, drift={"default": {"metric": "ks", "fail": 0.02}})
    assert loose.drift["x"].status == "pass"
    assert tight.drift["x"].status == "fail"


def test_incompatible_float_digits() -> None:
    a = dp.inspect(pl.DataFrame({"x": [1.0]}), float_digits=17)
    b = dp.inspect(pl.DataFrame({"x": [1.0]}), float_digits=6)
    with pytest.raises(dp.IncompatibleError):
        dp.compare(a, b)


def test_duplicate_key_falls_back_to_multiset() -> None:
    a = pl.DataFrame({"k": [1, 1, 2], "v": [1, 2, 3]})
    c = dp.compare(a, a, key="k")
    assert c.rows.method == "multiset"
    assert any("not unique" in n for n in c.notes)


def test_outputs() -> None:
    a, b = _versions()
    c = dp.compare(a, b, key="id")
    assert "+5" in c.summary()
    assert "Dataset comparison" in c.to_markdown()
    assert "<svg" in c.to_html()
    assert c.to_dict()["format"] == "datapassport/comparison"
