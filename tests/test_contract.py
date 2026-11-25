from __future__ import annotations

import json

import numpy as np
import polars as pl
import pytest

import datapassport as dp

CONTRACT = """
version: 1
dataset: orders
key: [id]
rows: {min: 1, max: 100}
schema: {extra_columns: warn}
columns:
  id: {type: integer, nullable: false, unique: true}
  status: {type: string, allowed: [new, paid, shipped], max_null_fraction: 0.5}
  amount: {type: number, min: -10, max: 100}
  city: {type: string, not_blank: true, severity: warn}
  day: {type: date, min: '2026-01-01'}
checks:
  - {rule: no_duplicate_rows}
"""


def test_passing_contract(orders: pl.DataFrame, tmp_path) -> None:
    path = tmp_path / "c.yml"
    path.write_text(CONTRACT)
    rep = dp.check(orders, path)
    assert rep.status == "warn"  # city has an empty string, at warn severity
    assert rep.ok
    assert [r.label for r in rep.warnings] == ["city: not_blank"]
    assert rep.exit_code() == 0 and rep.exit_code(strict=True) == 1


def test_failing_rules(orders: pl.DataFrame) -> None:
    bad = orders.with_columns(
        pl.when(pl.col("id") == 2).then(pl.lit("lost")).otherwise(pl.col("status")).alias("status"),
        pl.when(pl.col("id") == 3).then(500.0).otherwise(pl.col("amount")).alias("amount"),
        pl.when(pl.col("id") == 4).then(1).otherwise(pl.col("id")).alias("id"),
    )
    rep = dp.check(
        bad,
        {
            "key": ["id"],
            "columns": {
                "id": {"unique": True},
                "status": {"allowed": ["new", "paid", "shipped"]},
                "amount": {"max": 100},
                "city": {"pattern": "[A-Za-z ]+"},
                "missing": {"type": "string"},
            },
        },
    )
    failed = {r.label for r in rep.failures}
    assert {"key", "id: unique", "status: allowed", "amount: max", "city: pattern", "missing: required"} <= failed
    assert next(r for r in rep.failures if r.label == "status: allowed").failing_rows == 1
    with pytest.raises(dp.CheckFailed):
        rep.raise_for_status()


def test_type_rule(orders: pl.DataFrame) -> None:
    rep = dp.check(orders, {"columns": {"amount": {"type": "integer"}, "id": {"type": "number"}}})
    assert [r.label for r in rep.failures] == ["amount: type"]


def test_invalid_contract_message() -> None:
    with pytest.raises(dp.ContractError) as e:
        dp.Contract.from_dict({"columns": {"x": {"type": "bigint", "nulable": False}}})
    msg = str(e.value)
    assert "columns.x.type" in msg and "columns.x.nulable" in msg


def test_formats(tmp_path) -> None:
    (tmp_path / "c.json").write_text(json.dumps({"columns": {"x": {"type": "integer"}}}))
    (tmp_path / "c.toml").write_text('[columns.x]\ntype = "integer"\n')
    assert dp.Contract.load(tmp_path / "c.json").columns["x"].type == "integer"
    assert dp.Contract.load(tmp_path / "c.toml").columns["x"].type == "integer"
    with pytest.raises(dp.ContractError, match="not found"):
        dp.Contract.load(tmp_path / "nope.yml")


def test_custom_rule(orders: pl.DataFrame) -> None:
    @dp.rule("amount_below_id_times_10")
    def r(ctx: dp.RuleContext) -> dp.Outcome:
        bad = ctx.count_where("amount > id * 10")
        return dp.Outcome(passed=bad == 0, observed=bad, message=f"{bad} rows")

    @dp.rule("column_has_no_x")
    def r2(ctx: dp.RuleContext) -> dp.Outcome:
        n = ctx.count_where(f"contains(CAST({ctx.col} AS VARCHAR), 'x')")
        return dp.Outcome(passed=n == 0)

    rep = dp.check(
        orders,
        {
            "checks": [{"rule": "amount_below_id_times_10"}],
            "columns": {"city": {"checks": [{"rule": "column_has_no_x", "severity": "warn"}]}},
        },
    )
    assert {r.label: r.status for r in rep.results} == {
        "amount_below_id_times_10": "fail",
        "city: column_has_no_x": "pass",
    }
    with pytest.raises(dp.ContractError, match="Unknown rule"):
        dp.check(orders, {"checks": [{"rule": "does_not_exist"}]})


def test_rule_that_raises_is_reported(orders: pl.DataFrame) -> None:
    @dp.rule("boom")
    def boom(ctx: dp.RuleContext) -> dp.Outcome:
        raise RuntimeError("kaput")

    rep = dp.check(orders, {"checks": [{"rule": "boom"}]})
    assert rep.results[0].status == "error" and "kaput" in rep.results[0].message


def test_baseline_schema_and_drift(tmp_path) -> None:
    rng = np.random.default_rng(5)
    v1 = pl.DataFrame({"id": np.arange(3000), "x": rng.normal(0, 1, 3000), "gone": np.zeros(3000)})
    v2 = pl.DataFrame({"id": np.arange(3000), "x": rng.normal(2, 1, 3000)})
    dp.inspect(v1, key="id").to_json(tmp_path / "v1.json")
    rep = dp.check(
        v2,
        {"key": ["id"], "checks": [{"rule": "row_count_change", "max_fraction": 0.1}]},
        baseline=tmp_path / "v1.json",
    )
    labels = {r.label: r.status for r in rep.results}
    assert labels["gone: schema_removed"] == "fail"
    assert labels["x: drift_psi"] == "fail"
    assert labels["row_count_change"] == "pass"
    assert "id: drift_psi" not in labels  # keys are not drift-checked


def test_fingerprint_matches_rule(orders: pl.DataFrame) -> None:
    fp = dp.fingerprint(orders).dataset
    ok = dp.check(orders, {"checks": [{"rule": "fingerprint_matches", "fingerprint": fp[:16]}]})
    bad = dp.check(orders.head(3), {"checks": [{"rule": "fingerprint_matches", "fingerprint": fp}]})
    assert ok.status == "pass" and bad.status == "fail"


def test_infer_contract_passes_on_its_own_data(orders: pl.DataFrame, big_orders: pl.DataFrame) -> None:
    for df in (orders, big_orders):
        c = dp.Contract.infer(df)
        assert dp.check(df, c).status in {"pass", "warn"}
    c = dp.Contract.infer(big_orders)
    assert c.columns["segment"].allowed == ["a", "b", "c", "d"]
    assert c.columns["id"].unique
    assert dp.Contract.from_dict(__import__("yaml").safe_load(c.to_yaml())) == c


def test_sampled_check_still_checks_every_row(big_orders: pl.DataFrame) -> None:
    bad = big_orders.with_columns(pl.when(pl.col("id") == 12345).then(-1).otherwise(pl.col("qty")).alias("qty"))
    rep = dp.check(bad, {"columns": {"qty": {"min": 1}}}, sample=500)
    assert rep.failures[0].failing_rows == 1


def test_report_outputs(orders: pl.DataFrame) -> None:
    rep = dp.check(orders, {"columns": {"amount": {"max": 5}}})
    assert "::error title=DataPassport amount: max::" in rep.github_annotations()
    assert "Failed" in rep.to_markdown()
    assert json.loads(rep.to_json())["status"] == "fail"
