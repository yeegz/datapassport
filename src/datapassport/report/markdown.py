"""Markdown reports: for pull requests, GitHub step summaries and chat."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..fingerprint import short

if TYPE_CHECKING:
    from ..compare import Comparison
    from ..models import Passport
    from ..rules import CheckReport

_ICON = {"pass": "✅ pass", "warn": "⚠️ warn", "fail": "❌ fail", "error": "💥 error", "skipped": "➖ skipped"}


def _n(v: float | int | None, digits: int = 4) -> str:
    if v is None:
        return "–"
    if isinstance(v, int):
        return f"{v:,}"
    if abs(v) >= 1e6 or (abs(v) < 1e-3 and v != 0):
        return f"{v:.3g}"
    return f"{v:,.{digits}g}"


def _esc(s: str) -> str:
    return s.replace("|", "\\|")


def passport_markdown(p: Passport) -> str:
    lines = [
        f"### Passport: {_esc(p.name or 'dataset')}",
        "",
        f"**{p.rows:,} rows × {len(p.columns)} columns** · fingerprint `{short(p.fingerprint.dataset)}`"
        f" · {p.duplicates.rows:,} duplicate rows",
        "",
        "| Column | Type | Nulls | Distinct | Min | Max | Mean |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name in p.column_names:
        c = p.columns[name]
        num = c.numeric
        lines.append(
            f"| {_esc(name)} | {c.type} | {c.null_fraction:.1%} | {_n(c.distinct)}{'' if c.distinct_exact else '≈'} "
            f"| {_n(num.min) if num else '–'} | {_n(num.max) if num else '–'} | {_n(num.mean) if num else '–'} |"
        )
    if p.sample.method != "full":
        lines += [
            "",
            f"_Profile sampled: {p.sample.rows_profiled:,} of {p.rows:,} rows. "
            "Fingerprint and duplicates cover all rows._",
        ]
    return "\n".join(lines) + "\n"


def comparison_markdown(c: Comparison) -> str:
    title = "identical content" if c.identical else "changed"
    r = c.rows
    lines = [
        f"### Dataset comparison: {title}",
        "",
        f"`{short(c.base.fingerprint)}` ({c.base.rows:,} rows) → `{short(c.target.fingerprint)}` "
        f"({c.target.rows:,} rows)",
        "",
    ]
    if r.added is not None:
        row = f"**Rows** ({r.method}{' on ' + ', '.join(r.key) if r.key else ''}): +{r.added:,} added, −{r.removed:,} removed"
        if r.changed is not None:
            row += f", ~{r.changed:,} changed"
        lines.append(row + f", {r.unchanged:,} unchanged")
        if r.changed_by_column:
            lines.append("")
            lines.append(
                "Changed values by column: "
                + ", ".join(f"`{_esc(k)}` {v:,}" for k, v in sorted(r.changed_by_column.items(), key=lambda kv: -kv[1]))
            )
    if c.schema_changes:
        lines += ["", "**Schema changes**", ""]
        lines += [f"- {'⚠️ ' if s.breaking else ''}{_esc(s.describe())}" for s in c.schema_changes]
    elif not c.identical and r.added is None and c.changed_columns:
        lines += ["", "Columns with changed values: " + ", ".join(f"`{_esc(x)}`" for x in c.changed_columns)]
    judged = [d for d in c.drift.values() if d.status != "skipped"]
    if judged:
        lines += ["", "| Column | Drift | Metric | Value | Null Δ |", "| --- | --- | --- | ---: | ---: |"]
        for d in sorted(judged, key=lambda d: ("fail", "warn", "pass").index(d.status)):
            val = getattr(d, d.metric) if d.metric else None
            lines.append(
                f"| {_esc(d.column)} | {_ICON[d.status]} | {d.metric} | {_n(val, 3)} | {d.null_fraction_delta:+.1%} |"
            )
    if c.notes or r.note:
        lines += [""] + [f"> {n}" for n in ([r.note] if r.note else []) + c.notes]
    return "\n".join(lines) + "\n"


def check_markdown(rep: CheckReport) -> str:
    head = {"pass": "✅ Passed", "warn": "⚠️ Passed with warnings", "fail": "❌ Failed"}[rep.status]
    cnt = rep.counts
    lines = [
        f"### DataPassport check: {head}",
        "",
        f"**{_esc(rep.dataset or 'dataset')}** · {rep.rows:,} rows · fingerprint `{short(rep.fingerprint)}`"
        f" · {cnt['pass']} passed, {cnt['warn']} warnings, {cnt['fail'] + cnt['error']} failed",
        "",
    ]
    problems = [r for r in rep.results if r.status in {"fail", "error", "warn"}]
    if problems:
        lines += ["| Status | Check | Detail |", "| --- | --- | --- |"]
        for r in sorted(problems, key=lambda r: ("fail", "error", "warn").index(r.status)):
            lines.append(f"| {_ICON[r.status]} | {_esc(r.label)} | {_esc(r.message)} |")
    else:
        lines.append("All checks passed.")
    return "\n".join(lines) + "\n"
