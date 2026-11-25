"""Pydantic models for passports. These define the portable JSON format.

The JSON Schema for a passport is available from ``Passport.model_json_schema()``
and from ``datapassport schema passport`` on the command line.
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

PASSPORT_FORMAT: Literal["datapassport/passport"] = "datapassport/passport"
PASSPORT_VERSION = 1

PrivacyMode = Literal["safe", "values"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=False)


class Producer(_Model):
    """What produced the passport. Recorded so results can be reproduced."""

    name: str = "datapassport"
    version: str
    engine: str
    python: str
    platform: str


class SourceInfo(_Model):
    """Where the data came from."""

    uri: str | None = Field(None, description="Path or description of the source.")
    kind: str = Field(description="Adapter name: csv, parquet, json, jsonl, polars, pandas, arrow, duckdb ...")
    files: int | None = None
    bytes: int | None = None
    sha256: str | None = Field(
        None, description="sha256 of the file bytes (single files only). Byte identity, order-sensitive."
    )
    read_options: dict[str, Any] = Field(default_factory=dict)


class SampleInfo(_Model):
    """How the profile was sampled. Fingerprints always cover every row."""

    method: Literal["full", "hash"] = "full"
    target_rows: int | None = None
    seed: int = 0
    rows_profiled: int


class Options(_Model):
    float_digits: int = 17
    privacy: PrivacyMode = "safe"
    top_k: int = 20
    quantiles: Literal["exact", "approx"] = "exact"
    key: list[str] = Field(default_factory=list)
    token_salted: bool = Field(False, description="Category tokens used a secret salt (DATAPASSPORT_TOKEN_SALT).")
    sensitive: list[str] = Field(default_factory=list, description="Columns whose distributions were withheld.")


class ColumnSchema(_Model):
    name: str
    type: str = Field(description="Logical type, e.g. integer, float, string, timestamp_tz, list<integer>.")
    physical: str = Field(description="Engine type as read, e.g. BIGINT or DECIMAL(10,2).")
    position: int


class Fingerprint(_Model):
    spec: str
    dataset: str = Field(description="sha256 hex. Order-insensitive content identity.")
    schema_: str = Field(alias="schema", description="sha256 of sorted (name, logical type) pairs.")
    rows: int
    float_digits: int
    columns: dict[str, str] = Field(default_factory=dict, description="Per-column content fingerprints.")

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @property
    def short(self) -> str:
        return self.dataset[:12]


class NumericStats(_Model):
    min: float | None = None
    max: float | None = None
    mean: float | None = None
    std: float | None = None
    zeros: int = 0
    negatives: int = 0
    nan: int = 0
    infinite: int = 0
    quantiles: list[float] = Field(
        default_factory=list,
        description="Values at probabilities 0.00, 0.01, ... 1.00 over finite values (101 points).",
    )


class TextStats(_Model):
    min_length: int | None = None
    max_length: int | None = None
    mean_length: float | None = None
    empty: int = 0
    blank: int = Field(0, description="Non-empty values that are only whitespace.")


class TemporalStats(_Model):
    min: str | None = None
    max: str | None = None
    quantiles: list[float] = Field(
        default_factory=list, description="Quantiles of seconds since epoch (or since midnight for time)."
    )


class Categories(_Model):
    """Most frequent values. Values are stored as salted-free sha256 tokens unless
    the passport was made with ``privacy="values"``."""

    tokens: list[str]
    counts: list[int]
    values: list[str] | None = None
    other: int = Field(0, description="Non-null rows whose value is outside the top k.")


class ColumnProfile(_Model):
    name: str
    type: str
    count: int = Field(description="Non-null values profiled.")
    nulls: int
    null_fraction: float
    distinct: int | None = None
    distinct_exact: bool = True
    sensitive: bool = False
    numeric: NumericStats | None = None
    text: TextStats | None = None
    temporal: TemporalStats | None = None
    boolean: dict[str, int] | None = None
    categories: Categories | None = None
    extras: dict[str, Any] = Field(default_factory=dict, description="Results of custom metrics.")


class KeyStats(_Model):
    columns: list[str]
    duplicates: int = Field(description="Rows whose key appeared earlier (rows - distinct keys among non-null keys).")
    nulls: int = Field(description="Rows with a null in any key column.")


class DuplicateStats(_Model):
    rows: int = Field(description="Rows that exactly repeat an earlier row.")
    key: KeyStats | None = None


class Passport(_Model):
    """Evidence about one version of a dataset."""

    format: Literal["datapassport/passport"] = PASSPORT_FORMAT
    format_version: int = PASSPORT_VERSION
    name: str | None = None
    created_at: _dt.datetime
    producer: Producer
    source: SourceInfo
    options: Options
    sample: SampleInfo
    schema_: list[ColumnSchema] = Field(alias="schema")
    fingerprint: Fingerprint
    rows: int
    duplicates: DuplicateStats
    columns: dict[str, ColumnProfile]

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    # ------------------------------------------------------------------ helpers
    @property
    def column_names(self) -> list[str]:
        return [c.name for c in sorted(self.schema_, key=lambda c: c.position)]

    @property
    def types(self) -> dict[str, str]:
        return {c.name: c.type for c in self.schema_}

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True, exclude_none=True)

    def to_json(self, path: str | Path | None = None, *, indent: int = 2) -> str:
        """Serialise to JSON. Writes to ``path`` when given and returns the text."""
        text = json.dumps(self.to_dict(), indent=indent, ensure_ascii=False) + "\n"
        if path is not None:
            Path(path).write_text(text, encoding="utf-8")
        return text

    def to_html(self, path: str | Path | None = None) -> str:
        from .report.html import passport_html

        html = passport_html(self)
        if path is not None:
            Path(path).write_text(html, encoding="utf-8")
        return html

    def to_markdown(self) -> str:
        from .report.markdown import passport_markdown

        return passport_markdown(self)

    def to_openlineage(self) -> dict[str, Any]:
        """OpenLineage dataset facets (schema, dataQualityMetrics, version)."""
        from .integrations.openlineage import passport_facets

        return passport_facets(self)

    def column_table(self) -> Any:
        """Column profiles as a Polars DataFrame (one row per column)."""
        import polars as pl

        rows = []
        for name in self.column_names:
            c = self.columns[name]
            rows.append(
                {
                    "column": name,
                    "type": c.type,
                    "count": c.count,
                    "nulls": c.nulls,
                    "null_fraction": c.null_fraction,
                    "distinct": c.distinct,
                    "min": c.numeric.min if c.numeric else None,
                    "max": c.numeric.max if c.numeric else None,
                    "mean": c.numeric.mean if c.numeric else None,
                }
            )
        return pl.DataFrame(rows)

    def _repr_html_(self) -> str:  # Jupyter
        from .report.html import passport_fragment

        return passport_fragment(self)

    def __repr__(self) -> str:
        return (
            f"Passport(name={self.name!r}, rows={self.rows}, columns={len(self.columns)}, "
            f"fingerprint={self.fingerprint.short!r})"
        )

    @classmethod
    def load(cls, path: str | Path) -> Passport:
        from .errors import SourceError

        p = Path(path)
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except FileNotFoundError as e:
            raise SourceError(f"Passport file not found: {p}") from e
        except json.JSONDecodeError as e:
            raise SourceError(f"{p} is not valid JSON: {e}") from e
        if not isinstance(data, dict) or data.get("format") != PASSPORT_FORMAT:
            raise SourceError(
                f"{p} is not a DataPassport passport",
                hint="Create one with `datapassport inspect DATA --out passport.json`.",
            )
        if int(data.get("format_version", 0)) > PASSPORT_VERSION:
            raise SourceError(
                f"{p} uses passport format {data['format_version']}, newer than this version supports",
                hint="Upgrade datapassport.",
            )
        return cls.model_validate(data)


def is_passport_file(path: str | Path) -> bool:
    p = Path(path)
    if p.suffix.lower() != ".json" or not p.is_file():
        return False
    try:
        with p.open("rb") as fh:
            head = fh.read(4096).decode("utf-8", "ignore")
    except OSError:
        return False
    return '"datapassport/passport"' in head
