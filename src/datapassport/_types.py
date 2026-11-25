"""Logical types: the engine-independent type vocabulary used in passports.

Physical types differ between formats (a CSV integer becomes BIGINT, the same
column in Parquet may be INT32). Fingerprints and contracts use *logical* types
so that the same data in a different container has the same identity.
"""

from __future__ import annotations

from typing import Any

#: Logical type names that may appear in passports and contracts.
SCALAR_TYPES = (
    "boolean",
    "integer",
    "float",
    "decimal",
    "string",
    "binary",
    "date",
    "time",
    "timestamp",
    "timestamp_tz",
    "interval",
    "uuid",
    "null",
)

_INTEGER_IDS = {
    "tinyint",
    "smallint",
    "integer",
    "bigint",
    "hugeint",
    "utinyint",
    "usmallint",
    "uinteger",
    "ubigint",
    "uhugeint",
}
_FLOAT_IDS = {"float", "double"}
_TIMESTAMP_IDS = {"timestamp", "timestamp_s", "timestamp_ms", "timestamp_ns"}


def logical_type(dtype: Any) -> str:
    """Map a DuckDB type object to a logical type string.

    Nested types render recursively, e.g. ``list<integer>`` or
    ``struct<a:integer,b:string>``.
    """
    tid = str(dtype.id).lower()
    if tid in _INTEGER_IDS:
        return "integer"
    if tid in _FLOAT_IDS:
        return "float"
    if tid == "decimal":
        return "decimal"
    if tid in {"varchar", "enum", "string"}:
        return "string"
    if tid in {"blob", "bit"}:
        return "binary"
    if tid == "boolean":
        return "boolean"
    if tid == "date":
        return "date"
    if tid in {"time", "time with time zone", "time_ns"}:
        return "time"
    if tid in _TIMESTAMP_IDS:
        return "timestamp"
    if tid == "timestamp with time zone":
        return "timestamp_tz"
    if tid == "interval":
        return "interval"
    if tid == "uuid":
        return "uuid"
    if tid == "null":
        return "null"
    children = dict(dtype.children) if hasattr(dtype, "children") else {}
    if tid in {"list", "array"}:
        return f"list<{logical_type(children['child'])}>"
    if tid == "struct":
        inner = ",".join(f"{name}:{logical_type(t)}" for name, t in dtype.children)
        return f"struct<{inner}>"
    if tid == "map":
        return f"map<{logical_type(children['key'])},{logical_type(children['value'])}>"
    if tid == "union":
        return "union"
    return f"other:{tid}"


def is_numeric(ltype: str) -> bool:
    return ltype in {"integer", "float", "decimal"}


def is_temporal(ltype: str) -> bool:
    return ltype in {"date", "timestamp", "timestamp_tz", "time"}


def is_nested(ltype: str) -> bool:
    return ltype.startswith(("list<", "struct<", "map<")) or ltype == "union"


def is_textual(ltype: str) -> bool:
    return ltype in {"string", "uuid"}


def compatible(expected: str, actual: str) -> bool:
    """Whether data of logical type ``actual`` satisfies a contract type ``expected``.

    ``number`` accepts integer, float or decimal. ``any`` accepts everything.
    An all-null column (``null``) satisfies any type.
    """
    if expected in {"any", actual} or actual == "null":
        return True
    if expected == "number":
        return is_numeric(actual)
    if expected == "list":
        return actual.startswith("list<")
    if expected == "struct":
        return actual.startswith("struct<")
    if expected == "map":
        return actual.startswith("map<")
    return False


def quote_ident(name: str) -> str:
    """Quote an identifier for DuckDB SQL."""
    return '"' + name.replace('"', '""') + '"'


def quote_literal(value: str) -> str:
    """Quote a string literal for DuckDB SQL."""
    return "'" + value.replace("'", "''") + "'"
