from __future__ import annotations

import polars as pl
import pytest

import datapassport as dp


def test_openlineage_facets(orders: pl.DataFrame) -> None:
    f = dp.inspect(orders).to_openlineage()
    assert f["facets"]["version"]["datasetVersion"] == dp.fingerprint(orders).dataset
    assert [x["name"] for x in f["facets"]["schema"]["fields"]] == orders.columns
    dq = f["inputFacets"]["dataQualityMetrics"]
    assert dq["rowCount"] == 6
    assert dq["columnMetrics"]["amount"]["nullCount"] == 1
    assert dq["_schemaURL"].endswith("DataQualityMetricsInputDatasetFacet.json")


def test_markdown_and_repr(orders: pl.DataFrame) -> None:
    p = dp.inspect(orders)
    assert "| amount | float |" in p.to_markdown()
    assert "<svg" in p._repr_html_()
    assert repr(p).startswith("Passport(")


def test_html_is_self_contained(orders: pl.DataFrame) -> None:
    html = dp.inspect(orders).to_html()
    assert "http://" not in html and "https://" not in html  # no network requests
    assert 'lang="en"' in html and "prefers-color-scheme" in html


def test_pandera_conversion(orders: pl.DataFrame) -> None:
    pa = pytest.importorskip("pandera.polars")
    schema = pa.DataFrameSchema(
        {
            "id": pa.Column(pl.Int64, unique=True, nullable=False),
            "status": pa.Column(pl.Utf8, pa.Check.isin(["new", "paid", "shipped"]), nullable=True),
            "amount": pa.Column(pl.Float64, pa.Check.in_range(-10, 100), nullable=True),
        }
    )
    from datapassport.integrations.pandera import contract_from_pandera

    c = contract_from_pandera(schema)
    assert c.columns["id"].unique and not c.columns["id"].nullable
    assert c.columns["status"].allowed == ["new", "paid", "shipped"]
    assert (c.columns["amount"].min, c.columns["amount"].max) == (-10, 100)
    assert dp.check(orders, c).status == "pass"
