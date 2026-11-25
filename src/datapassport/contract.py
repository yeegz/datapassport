"""Contracts: reusable, declarative expectations about a dataset.

A contract is a YAML, JSON or TOML file (or a :class:`Contract` built in Python)::

    version: 1
    dataset: orders
    key: [order_id]
    rows: {min: 1}
    schema: {extra_columns: warn}
    columns:
      order_id: {type: integer, nullable: false, unique: true}
      status:   {type: string, allowed: [new, paid, shipped]}
      amount:   {type: number, min: 0, max_null_fraction: 0.01}
      email:    {type: string, sensitive: true, pattern: '^[^@]+@[^@]+$'}
    checks:
      - {rule: no_duplicate_rows}
      - {rule: row_count_change, max_fraction: 0.2, severity: warn}
    drift:
      default: {metric: psi, warn: 0.1, fail: 0.25}
      amount: {metric: wasserstein_norm, fail: 0.3}
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from ._types import SCALAR_TYPES
from .errors import ContractError

Severity = Literal["error", "warn"]
_TYPES = set(SCALAR_TYPES) | {"number", "any", "list", "struct", "map"}


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CheckSpec(_M):
    """A named rule with parameters. Extra keys become parameters."""

    rule: str
    severity: Severity = "error"
    model_config = ConfigDict(extra="allow")

    @property
    def params(self) -> dict[str, Any]:
        return dict(self.model_extra or {})


class ColumnSpec(_M):
    type: str | None = Field(None, description="Logical type, or number/any/list/struct/map.")
    required: bool = True
    nullable: bool = True
    max_null_fraction: float | None = Field(None, ge=0, le=1)
    unique: bool = False
    min: int | float | str | None = None
    max: int | float | str | None = None
    allowed: list[Any] | None = None
    pattern: str | None = Field(None, description="Regular expression every non-null value must fully match.")
    min_length: int | None = None
    max_length: int | None = None
    not_blank: bool = False
    sensitive: bool = Field(False, description="Withhold distributions and values of this column from reports.")
    severity: Severity = "error"
    checks: list[CheckSpec] = Field(default_factory=list)
    description: str | None = None

    @field_validator("type")
    @classmethod
    def _known_type(cls, v: str | None) -> str | None:
        if v is not None and v not in _TYPES and not v.startswith(("list<", "struct<", "map<")):
            raise ValueError(f"unknown type {v!r}; use one of {', '.join(sorted(_TYPES))}")
        return v


class SchemaSpec(_M):
    extra_columns: Literal["allow", "warn", "forbid"] = "allow"
    column_order: Literal["ignore", "enforce"] = "ignore"


class RowSpec(_M):
    min: int | None = None
    max: int | None = None


class DriftSpec(_M):
    metric: Literal["psi", "ks", "wasserstein_norm", "js", "tvd"] | None = None
    warn: float | None = None
    fail: float | None = None
    skip: bool = False
    min_count: int | None = Field(None, description="Skip drift when either side has fewer non-null values.")


class Contract(_M):
    version: int = 1
    dataset: str | None = None
    description: str | None = None
    key: list[str] = Field(default_factory=list)
    rows: RowSpec = Field(default_factory=RowSpec)
    schema_: SchemaSpec = Field(default_factory=SchemaSpec, alias="schema")
    columns: dict[str, ColumnSpec] = Field(default_factory=dict)
    checks: list[CheckSpec] = Field(default_factory=list)
    drift: dict[str, DriftSpec] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @field_validator("key", mode="before")
    @classmethod
    def _key_list(cls, v: Any) -> Any:
        return [v] if isinstance(v, str) else v

    @property
    def sensitive_columns(self) -> list[str]:
        return [n for n, c in self.columns.items() if c.sensitive]

    def drift_config(self) -> dict[str, dict[str, Any]]:
        return {k: v.model_dump(exclude_none=True) for k, v in self.drift.items()}

    # ------------------------------------------------------------------ io
    @classmethod
    def load(cls, path: str | Path) -> Contract:
        p = Path(path)
        try:
            text = p.read_text(encoding="utf-8")
        except FileNotFoundError as e:
            raise ContractError(
                f"Contract file not found: {p}",
                hint="Create one with `datapassport contract init DATA > contract.yml`.",
            ) from e
        suffix = p.suffix.lower()
        try:
            if suffix in {".yml", ".yaml"}:
                import yaml

                data = yaml.safe_load(text)
            elif suffix == ".toml":
                import tomllib

                data = tomllib.loads(text)
            else:
                data = json.loads(text)
        except Exception as e:  # parse errors from three libraries
            raise ContractError(f"Could not parse {p}: {e}") from e
        return cls.from_dict(data or {}, source=str(p))

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, source: str = "contract") -> Contract:
        try:
            return cls.model_validate(data)
        except ValidationError as e:
            lines = []
            for err in e.errors():
                loc = ".".join(str(x) for x in err["loc"])
                lines.append(f"  {loc}: {err['msg']}")
            raise ContractError(
                f"{source} is not a valid contract:\n" + "\n".join(lines), hint="See docs/contracts.md for every field."
            ) from None

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True, exclude_defaults=True)

    def to_yaml(self, path: str | Path | None = None) -> str:
        import yaml

        text = yaml.safe_dump(self.to_dict(), sort_keys=False, allow_unicode=True, width=100)
        if path is not None:
            Path(path).write_text(text, encoding="utf-8")
        return text

    # --------------------------------------------------------------- infer
    @classmethod
    def infer(cls, passport: Any, *, strict: bool = False) -> Contract:
        """Draft a contract from a passport (or anything ``dp.inspect`` accepts).

        The draft records types, required columns, non-null columns, unique
        columns and small category sets. ``strict=True`` also pins numeric
        ranges to the observed min and max. Review it before relying on it.
        """
        from .models import Passport

        if not isinstance(passport, Passport):
            from .engine import inspect

            passport = inspect(passport, privacy="values")
        cols: dict[str, ColumnSpec] = {}
        for name in passport.column_names:
            prof = passport.columns[name]
            spec = ColumnSpec(type=prof.type if prof.type != "null" else None)
            if prof.nulls == 0 and passport.rows > 0:
                spec.nullable = False
            if (
                prof.distinct_exact
                and prof.distinct == prof.count
                and prof.count > 1
                and prof.type in {"integer", "string", "uuid"}
            ):
                spec.unique = True
            cats = prof.categories
            if (
                cats
                and cats.values
                and cats.other == 0
                and prof.type == "string"
                and len(cats.values) <= 12
                and prof.count >= 10 * len(cats.values)
            ):
                spec.allowed = sorted(cats.values)
            if strict and prof.numeric and prof.numeric.min is not None:
                spec.min, spec.max = prof.numeric.min, prof.numeric.max
            elif prof.numeric and prof.numeric.min is not None and prof.numeric.min >= 0:
                spec.min = 0
            cols[name] = spec
        key = passport.options.key or [n for n, c in cols.items() if c.unique][:1]
        return cls(
            dataset=passport.name,
            key=key,
            rows=RowSpec(min=1),
            columns=cols,
            checks=[CheckSpec(rule="no_duplicate_rows", severity="warn")],
        )
