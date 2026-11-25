"""Evaluate a contract against a dataset and produce a :class:`CheckReport`."""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from ._types import compatible, quote_ident, quote_literal
from .contract import CheckSpec, ColumnSpec, Contract
from .engine import Engine, inspect, open_source
from .errors import CheckFailed, ContractError
from .models import Passport
from .plugins import Outcome, RuleContext, get_rule, registered_rules
from .sources import Loaded

Status = Literal["pass", "warn", "fail", "error", "skipped"]


class CheckResult(BaseModel):
    rule: str
    column: str | None = None
    status: Status
    severity: Literal["error", "warn"] = "error"
    observed: Any = None
    expected: Any = None
    failing_rows: int | None = None
    message: str

    @property
    def label(self) -> str:
        return f"{self.column}: {self.rule}" if self.column else self.rule


class CheckReport(BaseModel):
    format: Literal["datapassport/check"] = "datapassport/check"
    format_version: int = 1
    dataset: str | None
    fingerprint: str
    rows: int
    contract: str | None
    baseline: str | None = Field(None, description="Fingerprint of the baseline passport, if any.")
    checked_at: _dt.datetime
    status: Literal["pass", "warn", "fail"]
    counts: dict[str, int]
    results: list[CheckResult]

    _passport: Passport | None = None

    @property
    def passport(self) -> Passport | None:
        return self._passport

    @property
    def ok(self) -> bool:
        """True unless a check failed at error severity (warnings are OK)."""
        return self.status != "fail"

    @property
    def failures(self) -> list[CheckResult]:
        return [r for r in self.results if r.status in {"fail", "error"}]

    @property
    def warnings(self) -> list[CheckResult]:
        return [r for r in self.results if r.status == "warn"]

    def exit_code(self, strict: bool = False) -> int:
        if self.status == "fail" or (strict and self.status == "warn"):
            return 1
        return 0

    def raise_for_status(self, strict: bool = False) -> CheckReport:
        if self.exit_code(strict):
            items = self.failures + (self.warnings if strict else [])
            lines = "\n".join(f"  - {r.label}: {r.message}" for r in items[:20])
            raise CheckFailed(f"{len(items)} check(s) did not pass for {self.dataset or 'dataset'}:\n{lines}")
        return self

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)

    def to_json(self, path: str | Path | None = None, *, indent: int = 2) -> str:
        text = json.dumps(self.to_dict(), indent=indent, ensure_ascii=False, default=str) + "\n"
        if path is not None:
            Path(path).write_text(text, encoding="utf-8")
        return text

    def to_markdown(self) -> str:
        from .report.markdown import check_markdown

        return check_markdown(self)

    def github_annotations(self) -> str:
        """Workflow commands that show failures inline in GitHub Actions."""
        out = []
        for r in self.results:
            if r.status in {"fail", "error", "warn"}:
                level = "warning" if r.status == "warn" else "error"
                msg = r.message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
                out.append(f"::{level} title=DataPassport {r.label}::{msg}")
        return "\n".join(out)


# ------------------------------------------------------------------ helpers


def _status(passed: bool, severity: str) -> Status:
    if passed:
        return "pass"
    return "warn" if severity == "warn" else "fail"


class _Batch:
    """Collects violation-count expressions and runs them in a single scan."""

    def __init__(self) -> None:
        self.exprs: list[str] = []
        self.meta: list[tuple[str, str, str, Any, str]] = []

    def add(self, expr: str, column: str, rule: str, expected: Any, severity: str) -> None:
        self.exprs.append(expr)
        self.meta.append((column, rule, rule, expected, severity))

    def run(self, data: Loaded) -> list[CheckResult]:
        if not self.exprs:
            return []
        row = data.con.execute(f"SELECT {', '.join(self.exprs)} FROM {data.ref}").fetchone() or ()
        out = []
        for value, (column, rule, _, expected, severity) in zip(row, self.meta, strict=True):
            n = int(value or 0)
            out.append(
                CheckResult(
                    rule=rule,
                    column=column,
                    status=_status(n == 0, severity),
                    severity=severity,  # type: ignore[arg-type]
                    observed=n,
                    expected=expected,
                    failing_rows=n,
                    message="ok" if n == 0 else f"{n} row(s) violate {rule} ({_fmt(expected)})",
                )
            )
        return out


def _fmt(v: Any) -> str:
    if isinstance(v, list) and len(v) > 6:
        return "[" + ", ".join(map(str, v[:6])) + ", …]"
    return str(v)


def _literal_for(value: Any, physical: str) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return repr(value)
    return f"CAST({quote_literal(str(value))} AS {physical})"


def _column_checks(name: str, spec: ColumnSpec, data: Loaded, passport: Passport, batch: _Batch) -> list[CheckResult]:
    results: list[CheckResult] = []
    sev = spec.severity
    actual = passport.types.get(name)
    if actual is None:
        if spec.required:
            results.append(
                CheckResult(
                    rule="required",
                    column=name,
                    status=_status(False, sev),
                    severity=sev,
                    message=f"column {name!r} is missing",
                )
            )
        return results
    if spec.type:
        ok = compatible(spec.type, actual)
        results.append(
            CheckResult(
                rule="type",
                column=name,
                status=_status(ok, sev),
                severity=sev,
                observed=actual,
                expected=spec.type,
                message="ok" if ok else f"expected {spec.type}, found {actual}",
            )
        )
    c = quote_ident(name)
    physical = next(s.physical for s in passport.schema_ if s.name == name)
    text = f"CAST({c} AS VARCHAR)"
    if not spec.nullable:
        batch.add(f"count(*) - count({c})", name, "not_null", "no nulls", sev)
    if spec.max_null_fraction is not None:
        frac = passport.columns[name].nulls / passport.rows if passport.rows else 0.0
        if passport.sample.method != "full":
            # The profile may be sampled; count nulls on all rows.
            n = data.con.execute(f"SELECT count(*) - count({c}) FROM {data.ref}").fetchone()[0]  # type: ignore[index]
            frac = n / passport.rows if passport.rows else 0.0
        ok = frac <= spec.max_null_fraction
        results.append(
            CheckResult(
                rule="max_null_fraction",
                column=name,
                status=_status(ok, sev),
                severity=sev,
                observed=round(frac, 6),
                expected=spec.max_null_fraction,
                message="ok" if ok else f"{frac:.2%} null, limit {spec.max_null_fraction:.2%}",
            )
        )
    if spec.unique:
        batch.add(f"count({c}) - count(DISTINCT {c})", name, "unique", "unique values", sev)
    if spec.min is not None:
        batch.add(f"count(*) FILTER (WHERE {c} < {_literal_for(spec.min, physical)})", name, "min", spec.min, sev)
    if spec.max is not None:
        batch.add(f"count(*) FILTER (WHERE {c} > {_literal_for(spec.max, physical)})", name, "max", spec.max, sev)
    if spec.allowed is not None:
        values = ", ".join(quote_literal(str(v)) for v in spec.allowed) or "NULL"
        batch.add(
            f"count(*) FILTER (WHERE {c} IS NOT NULL AND {text} NOT IN ({values}))", name, "allowed", spec.allowed, sev
        )
    if spec.pattern is not None:
        try:
            data.con.execute("SELECT regexp_full_match('', ?)", [spec.pattern])
        except Exception as e:
            raise ContractError(f"columns.{name}.pattern is not a valid regular expression: {e}") from e
        batch.add(
            f"count(*) FILTER (WHERE {c} IS NOT NULL AND NOT regexp_full_match({text}, {quote_literal(spec.pattern)}))",
            name,
            "pattern",
            spec.pattern,
            sev,
        )
    if spec.min_length is not None:
        batch.add(
            f"count(*) FILTER (WHERE length({text}) < {int(spec.min_length)})", name, "min_length", spec.min_length, sev
        )
    if spec.max_length is not None:
        batch.add(
            f"count(*) FILTER (WHERE length({text}) > {int(spec.max_length)})", name, "max_length", spec.max_length, sev
        )
    if spec.not_blank:
        batch.add(f"count(*) FILTER (WHERE trim({text}) = '')", name, "not_blank", "no empty or blank values", sev)
    return results


def _builtin_named(spec: CheckSpec, passport: Passport, baseline: Passport | None) -> CheckResult | None:
    p = spec.params
    sev = spec.severity
    if spec.rule == "no_duplicate_rows":
        n = passport.duplicates.rows
        return CheckResult(
            rule=spec.rule,
            status=_status(n == 0, sev),
            severity=sev,
            observed=n,
            expected=0,
            failing_rows=n,
            message="ok" if n == 0 else f"{n} duplicate row(s)",
        )
    if spec.rule == "row_count_change":
        if baseline is None:
            return CheckResult(rule=spec.rule, status="skipped", severity=sev, message="needs a baseline passport")
        before, after = baseline.rows, passport.rows
        change = (after - before) / before if before else (0.0 if after == 0 else float("inf"))
        limit = p.get("max_fraction")
        lo = p.get("max_decrease", limit)
        hi = p.get("max_increase", limit)
        ok = (lo is None or change >= -float(lo)) and (hi is None or change <= float(hi))
        return CheckResult(
            rule=spec.rule,
            status=_status(ok, sev),
            severity=sev,
            observed=round(change, 6),
            expected={"max_decrease": lo, "max_increase": hi},
            message="ok" if ok else f"row count changed {change:+.1%} ({before} → {after})",
        )
    if spec.rule == "fingerprint_matches":
        want = p.get("fingerprint") or (baseline.fingerprint.dataset if baseline else None)
        if not want:
            return CheckResult(
                rule=spec.rule, status="skipped", severity=sev, message="give fingerprint: <sha256> or a baseline"
            )
        ok = passport.fingerprint.dataset.startswith(str(want))
        return CheckResult(
            rule=spec.rule,
            status=_status(ok, sev),
            severity=sev,
            observed=passport.fingerprint.dataset,
            expected=want,
            message="ok" if ok else "content differs from the expected fingerprint",
        )
    return None


def _run_custom(
    spec: CheckSpec, data: Loaded, passport: Passport, baseline: Passport | None, column: str | None
) -> CheckResult:
    fn = get_rule(spec.rule)
    if fn is None:
        known = ", ".join(registered_rules()) or "none registered"
        raise ContractError(
            f"Unknown rule {spec.rule!r}",
            hint=f"Built-in: no_duplicate_rows, row_count_change, fingerprint_matches. Custom: {known}. "
            "Custom rules must be imported (or installed as a plugin) before checking.",
        )
    try:
        out = fn(RuleContext(data=data, passport=passport, baseline=baseline, params=spec.params, column=column))
    except Exception as e:
        return CheckResult(
            rule=spec.rule,
            column=column,
            status="error",
            severity=spec.severity,
            message=f"rule raised {type(e).__name__}: {e}",
        )
    if not isinstance(out, Outcome):
        out = Outcome(passed=bool(out))
    return CheckResult(
        rule=spec.rule,
        column=column,
        status=_status(out.passed, spec.severity),
        severity=spec.severity,
        observed=out.observed,
        failing_rows=out.failing_rows,
        message=out.message or ("ok" if out.passed else "failed"),
    )


# -------------------------------------------------------------------- check


def check(
    source: Any,
    contract: Contract | str | Path | dict[str, Any],
    *,
    baseline: Passport | str | Path | None = None,
    sample: int | float | None = None,
    privacy: str = "safe",
    engine: Engine | None = None,
    format: str | None = None,
    read_options: dict[str, Any] | None = None,
) -> CheckReport:
    """Validate ``source`` against ``contract``; optionally compare with a ``baseline``.

    With a baseline (a passport or passport file), breaking schema changes and
    drift beyond the contract's thresholds are reported too.
    """
    contract_name: str | None
    if isinstance(contract, (str, Path)):
        contract_name = str(contract)
        contract = Contract.load(contract)
    elif isinstance(contract, dict):
        contract = Contract.from_dict(contract)
        contract_name = contract.dataset
    else:
        contract_name = contract.dataset
    if isinstance(baseline, (str, Path)):
        baseline = Passport.load(baseline)

    data = open_source(source, engine=engine, format=format, read_options=read_options)
    present = {c.name for c in data.columns}
    key = [k for k in contract.key if k in present]
    passport = inspect(
        source,
        key=key or None,
        sample=sample,
        privacy=privacy,
        sensitive=[c for c in contract.sensitive_columns if c in present],
        _loaded=data,
        name=contract.dataset,
    )
    results: list[CheckResult] = []
    batch = _Batch()

    # Dataset-level
    rs = contract.rows
    if rs.min is not None or rs.max is not None:
        ok = (rs.min is None or passport.rows >= rs.min) and (rs.max is None or passport.rows <= rs.max)
        results.append(
            CheckResult(
                rule="row_count",
                status=_status(ok, "error"),
                observed=passport.rows,
                expected={"min": rs.min, "max": rs.max},
                message="ok"
                if ok
                else f"{passport.rows} rows, expected "
                f"{rs.min if rs.min is not None else 0}..{rs.max if rs.max is not None else '∞'}",
            )
        )
    missing_key = [k for k in contract.key if k not in present]
    if contract.key:
        if missing_key:
            results.append(CheckResult(rule="key", status="fail", message=f"key column(s) missing: {missing_key}"))
        elif passport.duplicates.key:
            ks = passport.duplicates.key
            ok = ks.duplicates == 0 and ks.nulls == 0
            results.append(
                CheckResult(
                    rule="key",
                    status=_status(ok, "error"),
                    observed={"duplicates": ks.duplicates, "nulls": ks.nulls},
                    failing_rows=ks.duplicates + ks.nulls,
                    expected=contract.key,
                    message="ok" if ok else f"key {contract.key}: {ks.duplicates} duplicate(s), {ks.nulls} null(s)",
                )
            )
    extra = [c for c in passport.column_names if c not in contract.columns]
    if contract.columns and contract.schema_.extra_columns != "allow":
        sev = "warn" if contract.schema_.extra_columns == "warn" else "error"
        results.append(
            CheckResult(
                rule="extra_columns",
                status=_status(not extra, sev),
                severity=sev,  # type: ignore[arg-type]
                observed=extra,
                message="ok" if not extra else f"columns not in the contract: {', '.join(extra)}",
            )
        )
    if contract.schema_.column_order == "enforce":
        expected_order = [c for c in contract.columns if c in present]
        actual_order = [c for c in passport.column_names if c in contract.columns]
        ok = expected_order == actual_order
        results.append(
            CheckResult(
                rule="column_order",
                status=_status(ok, "error"),
                observed=actual_order,
                expected=expected_order,
                message="ok" if ok else "columns are in a different order",
            )
        )

    # Columns
    for name, spec in contract.columns.items():
        results += _column_checks(name, spec, data, passport, batch)
    results += batch.run(data)
    for name, spec in contract.columns.items():
        for cs in spec.checks:
            if name in present:
                results.append(_run_custom(cs, data, passport, baseline, name))

    # Named checks
    for cs in contract.checks:
        builtin = _builtin_named(cs, passport, baseline)
        results.append(builtin if builtin is not None else _run_custom(cs, data, passport, baseline, None))

    # Baseline: schema compatibility and drift
    if baseline is not None:
        from .compare import compare

        comp = compare(baseline, passport, key=contract.key or None, drift=contract.drift_config())
        for ch in comp.schema_changes:
            if ch.kind == "moved":
                continue
            results.append(
                CheckResult(
                    rule=f"schema_{ch.kind}",
                    column=ch.column,
                    status="fail" if ch.breaking else "pass",
                    observed=ch.to_type,
                    expected=ch.from_type,
                    message=ch.describe() + (" (breaking)" if ch.breaking else ""),
                )
            )
        for col, d in comp.drift.items():
            if d.status == "skipped":
                continue
            value = getattr(d, d.metric) if d.metric else None
            results.append(
                CheckResult(
                    rule=f"drift_{d.metric}",
                    column=col,
                    status="fail" if d.status == "fail" else "warn" if d.status == "warn" else "pass",
                    severity="warn" if d.status == "warn" else "error",
                    observed=round(value, 6) if isinstance(value, float) else value,
                    message="ok" if d.status == "pass" else f"{d.metric} = {value:.3f} vs baseline",
                )
            )

    counts = {s: sum(1 for r in results if r.status == s) for s in ("pass", "warn", "fail", "error", "skipped")}
    overall: Literal["pass", "warn", "fail"] = (
        "fail" if counts["fail"] or counts["error"] else "warn" if counts["warn"] else "pass"
    )
    report = CheckReport(
        dataset=passport.name,
        fingerprint=passport.fingerprint.dataset,
        rows=passport.rows,
        contract=contract_name,
        baseline=baseline.fingerprint.dataset if baseline else None,
        checked_at=_dt.datetime.now(_dt.UTC).replace(microsecond=0),
        status=overall,
        counts=counts,
        results=results,
    )
    report._passport = passport
    return report
