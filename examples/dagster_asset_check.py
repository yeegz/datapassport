"""Dagster: an asset check backed by a DataPassport contract."""

from __future__ import annotations

import polars as pl
from dagster import AssetCheckResult, Definitions, asset, asset_check

import datapassport as dp


@asset
def orders() -> pl.DataFrame:
    return pl.read_parquet("examples/data/orders_v2.parquet")


@asset_check(asset=orders)
def orders_contract(orders: pl.DataFrame) -> AssetCheckResult:
    report = dp.check(orders, "examples/contract.yml")
    return AssetCheckResult(
        passed=report.ok,
        metadata={
            "fingerprint": report.fingerprint,
            "rows": report.rows,
            "failed": [r.label for r in report.failures],
            "warnings": [r.label for r in report.warnings],
        },
    )


defs = Definitions(assets=[orders], asset_checks=[orders_contract])
