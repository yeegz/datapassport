"""Content fingerprints (spec ``dp-fp/1``).

A fingerprint identifies the *content* of a table, not the bytes of a file:

* Row order does not matter. Rows are combined with a commutative sum.
* Column order does not matter. Columns are sorted by NFC-normalised name.
* Physical width does not matter: INT32 and INT64 holding the same numbers match,
  and so do CSV and Parquet files holding the same values.
* Types do matter: the integer ``1`` and the string ``"1"`` differ, because the
  logical schema is bound into the fingerprint.
* Duplicates matter: two copies of a row differ from one copy.

The full specification, including the canonical value encodings, lives in
``docs/fingerprint-spec.md``. This module holds two implementations of it:

* :func:`sql_row_encoding` builds DuckDB SQL that the engine runs out of core.
* :func:`reference_fingerprint` is a slow, dependency-free Python reference
  used in property tests to prove that the SQL matches the spec.

The fingerprint is integrity evidence, not a signature. It uses MD5 per row and
additive combination, which is fine for detecting accidental change but is not
resistant to someone deliberately constructing a collision. Use the file
``sha256`` recorded in the passport, or sign the passport, when you need that.
"""

from __future__ import annotations

import datetime as _dt
import decimal as _decimal
import hashlib
import json
import math
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from ._types import is_nested, quote_ident

SPEC = "dp-fp/1"
DEFAULT_FLOAT_DIGITS = 17
_MASK64 = (1 << 64) - 1
_NULL = "~"


def nfc(name: str) -> str:
    return unicodedata.normalize("NFC", name)


def column_order(names: Iterable[str]) -> list[str]:
    """Canonical column order: by NFC name, ties broken by the raw name."""
    return sorted(names, key=lambda n: (nfc(n), n))


def schema_digest(columns: Sequence[tuple[str, str]]) -> str:
    """sha256 over the sorted (NFC name, logical type) pairs."""
    pairs = sorted((nfc(n), t) for n, t in columns)
    payload = json.dumps(pairs, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _options_tag(float_digits: int) -> str:
    return f"float_digits={float_digits}"


def combine(schema: str, rows: int, sum_hi: int, sum_lo: int, *, float_digits: int) -> str:
    """Final dataset fingerprint from its parts."""
    text = "\n".join(
        [SPEC, schema, str(rows), f"{sum_hi & _MASK64:016x}{sum_lo & _MASK64:016x}", _options_tag(float_digits)]
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def combine_column(name: str, ltype: str, rows: int, sum_hi: int, sum_lo: int, *, float_digits: int) -> str:
    """Fingerprint of a single column's multiset of values.

    The column name is deliberately left out, so a renamed column keeps its
    fingerprint. That is how comparisons detect renames.
    """
    del name
    text = "\n".join(
        [
            SPEC,
            "column",
            ltype,
            str(rows),
            f"{sum_hi & _MASK64:016x}{sum_lo & _MASK64:016x}",
            _options_tag(float_digits),
        ]
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- SQL


def sql_value(col: str, ltype: str, type_id: str, *, float_digits: int) -> str:
    """SQL expression giving the canonical text of a non-null value."""
    c = quote_ident(col)
    if ltype == "boolean":
        return f"CASE WHEN {c} THEN 'true' ELSE 'false' END"
    if ltype == "integer":
        return f"CAST({c} AS VARCHAR)"
    if ltype == "float":
        return (
            f"CASE WHEN isnan({c}) THEN 'nan' WHEN {c} = 0 THEN '0' "
            f"ELSE format('{{:.{float_digits}g}}', CAST({c} AS DOUBLE)) END"
        )
    if ltype == "decimal":
        # Drop trailing fractional zeros, then a trailing dot: 1.500 -> 1.5, 2.00 -> 2.
        return (
            f"CASE WHEN {c} = 0 THEN '0' ELSE regexp_replace(regexp_replace("
            f"CAST({c} AS VARCHAR), '(\\.[0-9]*?)0+$', '\\1'), '\\.$', '') END"
        )
    if ltype == "string":
        return f"CAST({c} AS VARCHAR)"
    if ltype == "uuid":
        return f"lower(CAST({c} AS VARCHAR))"
    if ltype == "binary":
        return f"lower(hex({c}))"
    if ltype == "date":
        return f"CAST({c} AS VARCHAR)"
    if ltype == "time":
        return f"CAST((hour({c}) * 3600 + minute({c}) * 60) * 1000000 + microsecond({c}) AS VARCHAR)"
    if ltype in {"timestamp", "timestamp_tz"}:
        base = f"CAST(epoch_us({c}) AS VARCHAR)"
        if type_id == "timestamp_ns":
            sub = f"nanosecond({c}) % 1000"
            return f"{base} || CASE WHEN {sub} <> 0 THEN '.' || lpad(CAST({sub} AS VARCHAR), 3, '0') ELSE '' END"
        return base
    if is_nested(ltype):
        return f"CAST(to_json({c}) AS VARCHAR)"
    if ltype == "null":
        return "''"
    return f"CAST({c} AS VARCHAR)"


def sql_field(col: str, ltype: str, type_id: str, *, float_digits: int) -> str:
    """SQL expression for one field: ``~`` for null, else ``<bytes>:<text>``."""
    value = sql_value(col, ltype, type_id, float_digits=float_digits)
    c = quote_ident(col)
    return f"(CASE WHEN {c} IS NULL THEN '{_NULL}' ELSE CAST(strlen({value}) AS VARCHAR) || ':' || {value} END)"


def sql_row_encoding(columns: Sequence[tuple[str, str, str]], *, float_digits: int = DEFAULT_FLOAT_DIGITS) -> str:
    """SQL expression for a whole row. ``columns`` is (name, logical type, type id)."""
    by_name = {name: (lt, tid) for name, lt, tid in columns}
    parts = [sql_field(name, *by_name[name], float_digits=float_digits) for name in column_order(by_name)]
    if not parts:
        return "''"
    return "concat(" + ", ".join(parts) + ")"


# --------------------------------------------------------------------- reference


def _digest_parts(text: str) -> tuple[int, int]:
    d = hashlib.md5(text.encode("utf-8"), usedforsecurity=False).digest()
    return int.from_bytes(d[:8], "little"), int.from_bytes(d[8:], "little")


def reference_value(value: Any, ltype: str, *, float_digits: int = DEFAULT_FLOAT_DIGITS) -> str:
    """Python reference for :func:`sql_value`, for scalar logical types."""
    if ltype == "boolean":
        return "true" if value else "false"
    if ltype == "integer":
        return str(int(value))
    if ltype == "float":
        f = float(value)
        if math.isnan(f):
            return "nan"
        if f == 0:
            return "0"
        return format(f, f".{float_digits}g")
    if ltype == "decimal":
        d = _decimal.Decimal(value)
        if d == 0:
            return "0"
        text = format(d, "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return text
    if ltype in {"string"}:
        return str(value)
    if ltype == "uuid":
        return str(value).lower()
    if ltype == "binary":
        return bytes(value).hex()
    if ltype == "date":
        return str(value.isoformat())
    if ltype == "time":
        t: _dt.time = value
        return str((t.hour * 3600 + t.minute * 60 + t.second) * 1_000_000 + t.microsecond)
    if ltype in {"timestamp", "timestamp_tz"}:
        ts: _dt.datetime = value
        if ts.tzinfo is not None:
            ts = ts.astimezone(_dt.UTC).replace(tzinfo=None)
        delta = ts - _dt.datetime(1970, 1, 1)
        return str((delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds)
    raise ValueError(f"reference encoding not defined for logical type {ltype!r}")


def reference_field(value: Any, ltype: str, *, float_digits: int = DEFAULT_FLOAT_DIGITS) -> str:
    if value is None:
        return _NULL
    text = reference_value(value, ltype, float_digits=float_digits)
    return f"{len(text.encode('utf-8'))}:{text}"


@dataclass(frozen=True)
class FingerprintParts:
    """The pieces that make up a dataset fingerprint."""

    schema: str
    rows: int
    sum_hi: int
    sum_lo: int
    float_digits: int

    @property
    def dataset(self) -> str:
        return combine(self.schema, self.rows, self.sum_hi, self.sum_lo, float_digits=self.float_digits)


def reference_fingerprint(
    schema: Sequence[tuple[str, str]],
    rows: Iterable[Sequence[Any]],
    *,
    float_digits: int = DEFAULT_FLOAT_DIGITS,
) -> FingerprintParts:
    """Compute a dataset fingerprint in pure Python.

    ``schema`` is a list of (name, logical type) in the order values appear in
    each row. Only scalar logical types are supported.
    """
    names = [n for n, _ in schema]
    order = [names.index(n) for n in column_order(names)]
    types = [t for _, t in schema]
    n = hi = lo = 0
    for row in rows:
        text = "".join(reference_field(row[i], types[i], float_digits=float_digits) for i in order)
        h, l_ = _digest_parts(text)
        hi = (hi + h) & _MASK64
        lo = (lo + l_) & _MASK64
        n += 1
    return FingerprintParts(schema_digest(schema), n, hi, lo, float_digits)


def short(fingerprint: str, length: int = 12) -> str:
    """Short display form of a fingerprint."""
    return fingerprint[:length]
