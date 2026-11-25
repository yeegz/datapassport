"""Build a DataPassport contract from an existing Pandera schema.

Teams that already describe frames with Pandera can reuse those schemas as
contracts for file-level CI checks and passports, without rewriting them::

    from datapassport.integrations.pandera import contract_from_pandera
    contract = contract_from_pandera(MySchema)          # DataFrameModel or DataFrameSchema
    dp.check("orders.parquet", contract).raise_for_status()

Supported: column presence, ``nullable``, ``unique``, dtype family, and the
built-in checks ``ge``/``gt``/``le``/``lt``/``in_range``/``isin``/``str_matches``/
``str_length``. Other checks are listed in the returned contract's description
so nothing is dropped silently.
"""

from __future__ import annotations

from typing import Any

from ..contract import ColumnSpec, Contract, SchemaSpec


def _family(dtype: Any) -> str | None:
    text = str(dtype).lower()
    if any(t in text for t in ("int",)):
        return "integer"
    if "float" in text or "double" in text:
        return "float"
    if "decimal" in text:
        return "decimal"
    if "bool" in text:
        return "boolean"
    if "datetime" in text or "timestamp" in text:
        return "timestamp_tz" if ("utc" in text or ("tz" in text and "none" not in text)) else "timestamp"
    if text == "date" or "date" in text:
        return "date"
    if "str" in text or "utf8" in text or "object" in text or "string" in text:
        return "string"
    return None


def contract_from_pandera(schema: Any) -> Contract:
    """Convert a Pandera ``DataFrameSchema`` or ``DataFrameModel`` class to a :class:`Contract`."""
    if hasattr(schema, "to_schema"):
        schema = schema.to_schema()
    if not hasattr(schema, "columns"):
        raise TypeError("expected a pandera DataFrameSchema or DataFrameModel")
    cols: dict[str, ColumnSpec] = {}
    unmapped: list[str] = []
    for name, col in schema.columns.items():
        spec = ColumnSpec(
            type=_family(col.dtype) if col.dtype is not None else None,
            nullable=bool(col.nullable),
            unique=bool(getattr(col, "unique", False)),
            required=bool(getattr(col, "required", True)),
        )
        for chk in col.checks:
            stats = dict(getattr(chk, "statistics", {}) or {})
            cname = getattr(chk, "name", None) or ""
            if cname in {"greater_than_or_equal_to", "ge"}:
                spec.min = stats.get("min_value")
            elif cname in {"greater_than", "gt"}:
                spec.min = stats.get("min_value")  # contract min is inclusive; stricter bound is noted
                unmapped.append(f"{name}: {cname} mapped to inclusive min")
            elif cname in {"less_than_or_equal_to", "le"}:
                spec.max = stats.get("max_value")
            elif cname in {"less_than", "lt"}:
                spec.max = stats.get("max_value")
                unmapped.append(f"{name}: {cname} mapped to inclusive max")
            elif cname == "in_range":
                spec.min, spec.max = stats.get("min_value"), stats.get("max_value")
            elif cname == "isin":
                spec.allowed = list(stats.get("allowed_values") or [])
            elif cname == "str_matches":
                pat = stats.get("pattern")
                spec.pattern = getattr(pat, "pattern", pat)
            elif cname == "str_length":
                spec.min_length = stats.get("min_value")
                spec.max_length = stats.get("max_value")
            else:
                unmapped.append(f"{name}: {cname or 'custom check'}")
        cols[str(name)] = spec
    unique_cols = getattr(schema, "unique", None)
    key = list(unique_cols) if isinstance(unique_cols, (list, tuple)) else []
    desc = "Converted from Pandera schema " + str(getattr(schema, "name", None) or "")
    if unmapped:
        desc += ". Not converted exactly: " + "; ".join(unmapped)
    strict = getattr(schema, "strict", False)
    return Contract(
        dataset=getattr(schema, "name", None),
        description=desc.strip(),
        key=key,
        columns=cols,
        schema_=SchemaSpec(extra_columns="forbid" if strict is True else "allow"),
    )
