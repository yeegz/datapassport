"""Airflow: validate each daily partition and keep its passport.

No provider package is needed; DataPassport is a plain Python call.
"""

from __future__ import annotations

import pendulum
from airflow.decorators import dag, task


@dag(schedule="@daily", start_date=pendulum.datetime(2026, 11, 1), catchup=False)
def orders_quality():
    @task
    def check_partition(ds: str | None = None) -> dict:
        import datapassport as dp

        path = f"s3://lake/orders/day={ds}/*.parquet"  # DuckDB reads s3:// via httpfs; configure credentials as usual
        report = dp.check(path, "contracts/orders.yml", baseline="passports/orders.latest.json")
        report.passport.to_json(f"/tmp/orders_{ds}.passport.json")
        report.raise_for_status()  # fails the task on contract failures
        return {"fingerprint": report.fingerprint, "rows": report.rows, "status": report.status}

    check_partition()


orders_quality()
