from __future__ import annotations

import json

import polars as pl
import pytest
from typer.testing import CliRunner

from datapassport.cli import app

runner = CliRunner()


@pytest.fixture
def files(tmp_path, orders: pl.DataFrame):
    v1 = tmp_path / "v1.csv"
    v2 = tmp_path / "v2.parquet"
    orders.write_csv(v1)
    orders.with_columns(pl.col("amount") * 2).write_parquet(v2)
    contract = tmp_path / "c.yml"
    contract.write_text("columns:\n  id: {type: integer, unique: true}\n  amount: {max: 25}\n")
    return tmp_path, v1, v2, contract


def test_version() -> None:
    r = runner.invoke(app, ["--version"])
    assert r.exit_code == 0 and r.stdout.startswith("datapassport ")


def test_inspect_writes_outputs(files) -> None:
    tmp, v1, _, _ = files
    r = runner.invoke(app, ["inspect", str(v1), "-k", "id", "-o", str(tmp / "p.json"), "--html", str(tmp / "p.html")])
    assert r.exit_code == 0, r.output
    assert "6 rows" in r.output
    assert json.loads((tmp / "p.json").read_text())["format"] == "datapassport/passport"
    assert (tmp / "p.html").read_text().startswith("<!doctype html>")


def test_inspect_json_stdout(files) -> None:
    _, v1, _, _ = files
    r = runner.invoke(app, ["inspect", str(v1), "--json"])
    assert json.loads(r.stdout)["rows"] == 6


def test_fingerprint_same_for_formats(files, orders) -> None:
    tmp, v1, _, _ = files
    orders.write_parquet(tmp / "same.parquet")
    a = runner.invoke(app, ["fingerprint", str(v1)]).stdout.split()[0]
    b = runner.invoke(app, ["fingerprint", str(tmp / "same.parquet")]).stdout.split()[0]
    assert a == b and len(a) == 64


def test_compare_and_fail_on(files) -> None:
    _, v1, v2, _ = files
    r = runner.invoke(app, ["compare", str(v1), str(v2), "-k", "id"])
    assert r.exit_code == 0, r.output
    assert "changed" in r.output.lower()
    assert runner.invoke(app, ["compare", str(v1), str(v2), "--fail-on", "change"]).exit_code == 1
    assert runner.invoke(app, ["compare", str(v1), str(v1), "--fail-on", "change"]).exit_code == 0
    md = runner.invoke(app, ["compare", str(v1), str(v2), "-k", "id", "--output", "markdown"])
    assert md.stdout.startswith("### Dataset comparison")


def test_check_exit_codes_and_github(files, tmp_path, monkeypatch) -> None:
    _, v1, v2, contract = files
    assert runner.invoke(app, ["check", str(v1), "-c", str(contract)]).exit_code == 0
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    r = runner.invoke(app, ["check", str(v2), "-c", str(contract), "--output", "github"])
    assert r.exit_code == 1
    assert "::error title=DataPassport amount: max::" in r.stdout
    assert "Failed" in summary.read_text()


def test_check_with_baseline_and_passport_out(files) -> None:
    tmp, v1, _, contract = files
    runner.invoke(app, ["inspect", str(v1), "-o", str(tmp / "base.json")])
    r = runner.invoke(
        app,
        [
            "check",
            str(v1),
            "-c",
            str(contract),
            "-b",
            str(tmp / "base.json"),
            "--passport-out",
            str(tmp / "new.json"),
            "-o",
            str(tmp / "rep.json"),
        ],
    )
    assert r.exit_code == 0, r.output
    assert json.loads((tmp / "rep.json").read_text())["baseline"]
    assert (tmp / "new.json").exists()


def test_errors_exit_2_with_hint(tmp_path) -> None:
    r = runner.invoke(app, ["inspect", str(tmp_path / "missing.csv")])
    assert r.exit_code == 2
    assert "File not found" in r.output
    bad = tmp_path / "bad.yml"
    bad.write_text("columns: {x: {typo: 1}}")
    (tmp_path / "d.csv").write_text("x\n1\n")
    r = runner.invoke(app, ["check", str(tmp_path / "d.csv"), "-c", str(bad)])
    assert r.exit_code == 2 and "columns.x.typo" in r.output


def test_verify(files) -> None:
    tmp, v1, v2, _ = files
    runner.invoke(app, ["inspect", str(v1), "-o", str(tmp / "p.json")])
    assert runner.invoke(app, ["verify", str(tmp / "p.json"), str(v1)]).exit_code == 0
    r = runner.invoke(app, ["verify", str(tmp / "p.json"), str(v2)])
    assert r.exit_code == 1 and "amount" in r.output


def test_contract_init_and_rules(files) -> None:
    tmp, v1, _, _ = files
    r = runner.invoke(app, ["contract", "init", str(v1), "-o", str(tmp / "draft.yml")])
    assert r.exit_code == 0
    assert runner.invoke(app, ["check", str(v1), "-c", str(tmp / "draft.yml")]).exit_code == 0
    assert "no_duplicate_rows" in runner.invoke(app, ["contract", "rules"]).stdout


def test_report_and_schema(files) -> None:
    tmp, v1, v2, _ = files
    runner.invoke(app, ["compare", str(v1), str(v2), "-o", str(tmp / "c.json")])
    assert runner.invoke(app, ["report", str(tmp / "c.json"), "-o", str(tmp / "c.html")]).exit_code == 0
    assert "<svg" in (tmp / "c.html").read_text() or "Dataset comparison" in (tmp / "c.html").read_text()
    s = runner.invoke(app, ["schema", "contract"])
    assert json.loads(s.stdout)["title"] == "Contract"


def test_read_option_parsing(tmp_path) -> None:
    (tmp_path / "s.csv").write_text("a;b\n1;2\n")
    r = runner.invoke(app, ["inspect", str(tmp_path / "s.csv"), "--read", "delim=;", "--json"])
    assert json.loads(r.stdout)["schema"][1]["name"] == "b"
