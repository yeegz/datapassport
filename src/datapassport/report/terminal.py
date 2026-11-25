"""Rich terminal output. Status is always spelled out, never colour alone."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ..fingerprint import short

if TYPE_CHECKING:
    from ..compare import Comparison
    from ..models import Passport
    from ..rules import CheckReport

STYLE = {"pass": "green", "warn": "yellow", "fail": "red", "error": "red", "skipped": "dim"}
WORD = {"pass": "PASS", "warn": "WARN", "fail": "FAIL", "error": "ERROR", "skipped": "SKIP"}

_BARS = " ▁▂▃▄▅▆▇█"


def _fmt(v: float | int | None) -> str:
    if v is None:
        return "–"
    if isinstance(v, int):
        return f"{v:,}"
    if v != 0 and (abs(v) >= 1e7 or abs(v) < 1e-3):
        return f"{v:.3g}"
    return f"{v:,.4g}"


def spark(quantiles: list[float], bins: int = 12) -> str:
    """A tiny histogram from quantiles: bar height = share of mass per equal-width bin."""
    if len(quantiles) < 2 or quantiles[-1] == quantiles[0]:
        return ""
    lo, hi = quantiles[0], quantiles[-1]
    width = (hi - lo) / bins
    from ..drift import cdf

    mass = [cdf(quantiles, lo + width * (i + 1)) - cdf(quantiles, lo + width * i) for i in range(bins)]
    mass[0] += cdf(quantiles, lo)
    top = max(mass) or 1
    return "".join(_BARS[min(8, round(m / top * 8))] for m in mass)


def passport_view(p: Passport) -> Group:
    head = Text()
    head.append(f"{p.name or 'dataset'}  ", style="bold")
    head.append(f"{p.rows:,} rows × {len(p.columns)} columns  ")
    head.append(f"fingerprint {short(p.fingerprint.dataset)}", style="cyan")
    if p.duplicates.rows:
        head.append(f"  {p.duplicates.rows:,} duplicate rows", style="yellow")
    if p.duplicates.key:
        k = p.duplicates.key
        style = "yellow" if (k.duplicates or k.nulls) else "green"
        head.append(f"  key {', '.join(k.columns)}: {k.duplicates:,} dup / {k.nulls:,} null", style=style)
    t = Table(box=None, pad_edge=False, header_style="bold")
    for col, j in [
        ("column", "left"),
        ("type", "left"),
        ("nulls", "right"),
        ("distinct", "right"),
        ("min", "right"),
        ("max", "right"),
        ("mean", "right"),
        ("shape", "left"),
    ]:
        t.add_column(col, justify=j)  # type: ignore[arg-type]
    for name in p.column_names:
        c = p.columns[name]
        num = c.numeric
        shape = spark(num.quantiles) if num else spark(c.temporal.quantiles) if c.temporal else ""
        if c.sensitive:
            shape = "(withheld)"
        elif c.text and not shape:
            shape = f"len {c.text.min_length}–{c.text.max_length}"
        nulls = Text(f"{c.null_fraction:.1%}", style="yellow" if c.nulls else "")
        mn = _fmt(num.min) if num else (c.temporal.min if c.temporal else "–")
        mx = _fmt(num.max) if num else (c.temporal.max if c.temporal else "–")
        t.add_row(
            name,
            c.type,
            nulls,
            _fmt(c.distinct) + ("" if c.distinct_exact else "≈"),
            mn or "–",
            mx or "–",
            _fmt(num.mean) if num else "–",
            shape,
        )
    parts: list[object] = [head, Text(""), t]
    if p.sample.method != "full":
        parts.append(
            Text(
                f"\nProfile sampled: {p.sample.rows_profiled:,} of {p.rows:,} rows "
                "(fingerprint and duplicates use all rows).",
                style="dim",
            )
        )
    return Group(*parts)  # type: ignore[arg-type]


def comparison_view(c: Comparison) -> Group:
    parts: list[object] = []
    head = Text()
    if c.identical:
        head.append("IDENTICAL CONTENT", style="bold green")
        head.append("  (row order is ignored)", style="dim")
    else:
        head.append("CHANGED", style="bold yellow")
    head.append(f"   {short(c.base.fingerprint)} → {short(c.target.fingerprint)}", style="cyan")
    parts.append(head)
    r = c.rows
    rows = Text(f"rows {r.before:,} → {r.after:,}")
    if r.added is not None:
        rows.append(f"   +{r.added:,} added", style="green")
        rows.append(f"  −{r.removed:,} removed", style="red")
        if r.changed is not None:
            rows.append(f"  ~{r.changed:,} changed", style="yellow")
        rows.append(f"  ({r.method}{': ' + ', '.join(r.key) if r.key else ''})", style="dim")
    parts.append(rows)
    if r.changed_by_column:
        parts.append(
            Text(
                "changed values: "
                + ", ".join(f"{k} {v:,}" for k, v in sorted(r.changed_by_column.items(), key=lambda kv: -kv[1]))
            )
        )
    elif c.changed_columns and not c.identical:
        parts.append(Text("columns with changed values: " + ", ".join(c.changed_columns)))
    if c.schema_changes:
        parts.append(Text("\nSchema", style="bold"))
        for s in c.schema_changes:
            parts.append(
                Text(("  BREAKING  " if s.breaking else "  ") + s.describe(), style="red" if s.breaking else "")
            )
    judged = [d for d in c.drift.values() if d.status != "skipped"]
    if judged:
        t = Table(box=None, header_style="bold", title=None)
        for col, j in [
            ("column", "left"),
            ("drift", "left"),
            ("psi", "right"),
            ("ks", "right"),
            ("w1/iqr", "right"),
            ("null Δ", "right"),
        ]:
            t.add_column(col, justify=j)  # type: ignore[arg-type]
        for d in sorted(judged, key=lambda d: (("fail", "warn", "pass").index(d.status), d.column)):
            t.add_row(
                d.column,
                Text(WORD[d.status], style=STYLE[d.status]),
                _fmt(d.psi),
                _fmt(d.ks),
                _fmt(d.wasserstein_norm),
                f"{d.null_fraction_delta:+.1%}",
            )
        parts += [Text("\nDistribution drift", style="bold"), t]
    for n in ([r.note] if r.note else []) + c.notes:
        parts.append(Text(n, style="dim"))
    return Group(*parts)  # type: ignore[arg-type]


def check_view(rep: CheckReport, *, verbose: bool = False) -> Panel:
    t = Table(box=None, header_style="bold", show_header=True)
    t.add_column("status")
    t.add_column("check")
    t.add_column("detail")
    order = ("fail", "error", "warn", "pass", "skipped")
    for r in sorted(rep.results, key=lambda r: order.index(r.status)):
        if r.status in {"pass", "skipped"} and not verbose:
            continue
        t.add_row(Text(WORD[r.status], style=STYLE[r.status]), r.label, r.message)
    cnt = rep.counts
    summary = Text()
    summary.append(f"{WORD[rep.status]}", style=f"bold {STYLE[rep.status]}")
    summary.append(
        f"  {rep.dataset or 'dataset'} · {rep.rows:,} rows · {short(rep.fingerprint)} · "
        f"{cnt['pass']} passed, {cnt['warn']} warnings, {cnt['fail'] + cnt['error']} failed"
    )
    body: list[object] = [summary]
    if t.row_count:
        body += [Text(""), t]
    elif not verbose:
        body.append(Text("All checks passed. Use --verbose to list them.", style="dim"))
    return Panel(Group(*body), title="DataPassport check", border_style=STYLE[rep.status])  # type: ignore[arg-type]


def console(stderr: bool = False) -> Console:
    return Console(stderr=stderr, highlight=False)
