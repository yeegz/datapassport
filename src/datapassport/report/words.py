"""Plain-language sentences shared by the HTML and terminal reports."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..compare import Comparison
    from ..models import Passport

TYPE_WORDS = {
    "integer": "Whole number",
    "float": "Decimal number",
    "decimal": "Exact decimal",
    "string": "Text",
    "boolean": "Yes or no",
    "date": "Date",
    "time": "Time of day",
    "timestamp": "Date and time",
    "timestamp_tz": "Date and time, with time zone",
    "uuid": "UUID",
    "binary": "Binary",
    "interval": "Duration",
    "null": "Always empty",
}


def type_words(t: str) -> str:
    if t in TYPE_WORDS:
        return TYPE_WORDS[t]
    if t.startswith("list<"):
        return "List"
    if t.startswith("struct<"):
        return "Record"
    if t.startswith("map<"):
        return "Map"
    return t


DRIFT_WORDS = {
    "pass": ("ok", "Steady"),
    "warn": ("warn", "Shifted"),
    "fail": ("bad", "Shifted beyond the limit"),
    "skipped": ("skip", "Not judged"),
}
RESULT_WORDS = {
    "pass": ("ok", "Passed"),
    "warn": ("warn", "Warning"),
    "fail": ("bad", "Failed"),
    "error": ("bad", "Rule error"),
    "skipped": ("skip", "Skipped"),
}


def passport_lede(p: Passport) -> str:
    bits = [f"{p.rows:,} rows across {len(p.columns)} column{'s' if len(p.columns) != 1 else ''}."]
    k = p.duplicates.key
    if k:
        key = ", ".join(k.columns)
        if k.duplicates == 0 and k.nulls == 0:
            bits.append(f"Every {key} is unique and present.")
        else:
            bits.append(f"{k.duplicates:,} {key} values repeat and {k.nulls:,} are missing.")
    gaps = sorted(((c.null_fraction, n) for n, c in p.columns.items() if c.nulls), reverse=True)
    if not gaps:
        bits.append("Nothing is missing.")
    elif len(gaps) == 1:
        bits.append(f"Only {gaps[0][1]} has gaps ({gaps[0][0]:.1%}).")
    else:
        bits.append(f"{len(gaps)} columns have gaps, most in {gaps[0][1]} ({gaps[0][0]:.1%}).")
    bits.append("No row appears twice." if p.duplicates.rows == 0 else f"{p.duplicates.rows:,} rows are exact repeats.")
    return " ".join(bits)


def comparison_lede(c: Comparison) -> str:
    r = c.rows
    if c.identical:
        return "Same content. Rows may be in a different order or format, but every value matches."
    bits = []
    if r.added is not None:
        parts = [f"{r.added:,} rows added", f"{r.removed:,} removed"]
        if r.changed is not None:
            edited = f"{r.changed:,} edited"
            if r.changed_by_column:
                cols = sorted(r.changed_by_column, key=lambda k: -r.changed_by_column[k])
                edited += f", in {', '.join(cols[:2])}" + (" and others" if len(cols) > 2 else "")
            parts.append(edited)
        bits.append(", ".join(parts[:-1]) + " and " + parts[-1] + ".")
    else:
        bits.append(f"Rows went from {r.before:,} to {r.after:,}.")
    if c.breaking_changes:
        bits.append(
            f"{len(c.breaking_changes)} schema change{'s' if len(c.breaking_changes) > 1 else ''} can break readers."
        )
    elif c.schema_changes:
        bits.append("The schema changed in compatible ways.")
    if c.drifted:
        bits.append(f"{', '.join(list(c.drifted)[:3])} shifted in distribution.")
    return " ".join(bits)
