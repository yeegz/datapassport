"""Source adapters: turn files, data frames and queries into a DuckDB relation.

All analysis runs in DuckDB, whatever the input. That keeps one set of semantics
(and one fingerprint implementation) across CSV, Parquet, JSON, Polars, pandas
and Arrow, and lets DuckDB spill to disk for inputs larger than memory.

Add your own adapter with :func:`register_source`.
"""

from __future__ import annotations

import glob as _glob
import hashlib
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import duckdb

from ._types import logical_type, quote_ident, quote_literal
from .errors import SourceError
from .models import SourceInfo as SourceInfo

FILE_FORMATS = {
    ".csv": "csv",
    ".tsv": "csv",
    ".txt": "csv",
    ".csv.gz": "csv",
    ".tsv.gz": "csv",
    ".json": "json",
    ".json.gz": "json",
    ".jsonl": "jsonl",
    ".ndjson": "jsonl",
    ".jsonl.gz": "jsonl",
    ".ndjson.gz": "jsonl",
    ".parquet": "parquet",
    ".pq": "parquet",
}


@dataclass
class Column:
    name: str
    type: str  # logical
    physical: str  # engine type text
    type_id: str  # engine type id


@dataclass
class Loaded:
    """A source registered on a connection as relation ``name``."""

    con: duckdb.DuckDBPyConnection
    name: str
    info: SourceInfo
    columns: list[Column] = field(default_factory=list)

    @property
    def ref(self) -> str:
        return quote_ident(self.name)


@runtime_checkable
class Source(Protocol):
    """Anything that can register itself as a relation on a DuckDB connection."""

    kind: str

    def register(self, con: duckdb.DuckDBPyConnection, name: str) -> SourceInfo: ...


# ----------------------------------------------------------------------- files


def detect_format(path: str) -> str | None:
    lower = path.lower()
    for suffix in sorted(FILE_FORMATS, key=len, reverse=True):
        if lower.endswith(suffix):
            return FILE_FORMATS[suffix]
    return None


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _sql_value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, dict):
        inner = ", ".join(f"{quote_literal(str(k))}: {_sql_value(x)}" for k, x in v.items())
        return "{" + inner + "}"
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_sql_value(x) for x in v) + "]"
    return quote_literal(str(v))


class FileSource:
    """CSV, TSV, JSON, JSON Lines or Parquet; a single file, a glob or a directory of Parquet."""

    def __init__(
        self,
        path: str | os.PathLike[str],
        format: str | None = None,
        read_options: dict[str, Any] | None = None,
        hash_bytes: bool = True,
    ) -> None:
        self.path = str(path)
        self.read_options = dict(read_options or {})
        self.hash_bytes = hash_bytes
        p = Path(self.path)
        self.remote = "://" in self.path and not self.path.startswith("file://")
        if self.remote:
            # s3://, gs://, https://, hf:// ... are read by DuckDB itself (httpfs);
            # globs are expanded by DuckDB, so no local listing or byte hash.
            self.files = [self.path]
            fmt = format or detect_format(self.path.rstrip("*/"))
        elif p.is_dir():
            self.files = sorted(str(f) for f in p.rglob("*") if f.is_file() and detect_format(str(f)))
            fmt = format or (detect_format(self.files[0]) if self.files else None)
        elif any(ch in self.path for ch in "*?["):
            self.files = sorted(_glob.glob(self.path, recursive=True))
            fmt = format or (detect_format(self.files[0]) if self.files else None)
        else:
            if not p.exists():
                near = _suggest(p)
                raise SourceError(
                    f"File not found: {self.path}",
                    hint=f"Did you mean {near}?" if near else "Check the path and your working directory.",
                )
            self.files = [self.path]
            fmt = format or detect_format(self.path)
        if not self.files:
            raise SourceError(f"No data files match {self.path}")
        if fmt not in {"csv", "json", "jsonl", "parquet"}:
            raise SourceError(
                f"Can't tell the format of {self.path}",
                hint="Pass format='csv', 'json', 'jsonl' or 'parquet' (CLI: --format).",
            )
        self.kind = fmt

    def effective_options(self) -> dict[str, Any]:
        """Reader options including DataPassport's defaults (recorded in passports)."""
        opts = dict(self.read_options)
        if self.kind == "csv":
            opts.setdefault("allow_quoted_nulls", False)
            # DuckDB's sniffer may decide a file "starts" further down and skip
            # earlier lines without telling anyone. Evidence must cover every
            # line, so reading starts at line one unless the caller says otherwise.
            opts.setdefault("skip", 0)
            if any(f.lower().endswith((".tsv", ".tsv.gz")) for f in self.files):
                opts.setdefault("delim", "\t")
        elif self.kind == "jsonl":
            opts.setdefault("format", "newline_delimited")
        return opts

    def _reader(self) -> str:
        files = "[" + ", ".join(quote_literal(f) for f in self.files) + "]"
        opts = self.effective_options()
        if self.kind == "csv":
            fn = "read_csv"
        elif self.kind == "parquet":
            fn = "read_parquet"
        else:
            fn = "read_json"
            if self.kind == "jsonl":
                opts.setdefault("format", "newline_delimited")
        args = "".join(f", {k} = {_sql_value(v)}" for k, v in opts.items())
        return f"{fn}({files}{args})"

    def register(self, con: duckdb.DuckDBPyConnection, name: str) -> SourceInfo:
        reader = self._reader()
        # Parquet is columnar and cheap to rescan; text formats are parsed once
        # into a temporary table, which DuckDB spills to disk when needed.
        verb = "VIEW" if self.kind == "parquet" else "TABLE"
        try:
            con.execute(f"CREATE OR REPLACE TEMP {verb} {quote_ident(name)} AS SELECT * FROM {reader}")
        except duckdb.Error as e:
            raise SourceError(
                f"Could not read {self.path} as {self.kind}: {_first_line(e)}",
                hint=_read_hint(self.kind, str(e)),
            ) from e
        if self.kind == "csv" and "delim" not in self.read_options and "columns" not in self.read_options:
            cols = con.execute(f"SELECT * FROM {quote_ident(name)} LIMIT 0").description or []
            if len(cols) == 1 and any(d in str(cols[0][0]) for d in (",", ";", "\t", "|")):
                raise SourceError(
                    f"{self.path}: rows have different numbers of fields, so the delimiter could not be detected",
                    hint="Pass the delimiter explicitly, e.g. --read delim=',' (add --read null_padding=true to "
                    "pad short rows, or --read ignore_errors=true to skip bad rows and see how many).",
                )
        if self.remote:
            return SourceInfo(uri=self.path, kind=self.kind, read_options=self.effective_options())
        size = sum(os.path.getsize(f) for f in self.files)
        sha = _sha256(Path(self.files[0])) if self.hash_bytes and len(self.files) == 1 else None
        return SourceInfo(
            uri=self.path,
            kind=self.kind,
            files=len(self.files),
            bytes=size,
            sha256=sha,
            read_options=self.effective_options(),
        )


def _first_line(e: Exception) -> str:
    return str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__


def _read_hint(kind: str, msg: str) -> str:
    if kind == "csv":
        if "Could not convert" in msg or "conversion" in msg.lower():
            return (
                "A value later in the file doesn't match the type guessed from the first rows. "
                "Try read_options={'sample_size': -1} (CLI: --read sample_size=-1) "
                "or {'all_varchar': True}."
            )
        return "Try read_options such as {'delim': ';'}, {'header': False} or {'quote': '\"'}."
    if kind in {"json", "jsonl"}:
        return "For one JSON object per line use format='jsonl'. Nested data is supported."
    return "Check that the file is a valid Parquet file."


def _suggest(p: Path) -> str | None:
    parent = p.parent if str(p.parent) else Path(".")
    if not parent.is_dir():
        return None
    import difflib

    names = [c.name for c in parent.iterdir()]
    match = difflib.get_close_matches(p.name, names, n=1)
    return str(parent / match[0]) if match else None


# ---------------------------------------------------------------------- frames


class FrameSource:
    """Polars, pandas, Arrow, or anything exposing the Arrow C stream interface."""

    def __init__(self, obj: Any, kind: str) -> None:
        self.obj = obj
        self.kind = kind

    def register(self, con: duckdb.DuckDBPyConnection, name: str) -> SourceInfo:
        obj = self.obj
        if self.kind == "polars-lazy":
            obj = obj.collect(engine="streaming")
        if self.kind in {"polars", "polars-lazy"}:
            # Arrow export is zero-copy for most Polars types.
            obj = obj.to_arrow()
        try:
            con.register(f"__dp_src_{name}", obj)
            con.execute(
                f"CREATE OR REPLACE TEMP VIEW {quote_ident(name)} AS SELECT * FROM {quote_ident('__dp_src_' + name)}"
            )
        except duckdb.Error as e:
            raise SourceError(f"DuckDB could not read this {self.kind} object: {_first_line(e)}") from e
        return SourceInfo(uri=None, kind=self.kind)


class QuerySource:
    """A SQL query (or table name) on an existing DuckDB connection."""

    def __init__(self, sql: str, con: duckdb.DuckDBPyConnection | None = None) -> None:
        self.sql = sql
        self.con = con
        self.kind = "duckdb"

    def register(self, con: duckdb.DuckDBPyConnection, name: str) -> SourceInfo:
        try:
            con.execute(f"CREATE OR REPLACE TEMP VIEW {quote_ident(name)} AS {self.sql}")
        except duckdb.Error as e:
            raise SourceError(f"Query failed: {_first_line(e)}") from e
        return SourceInfo(uri=self.sql if len(self.sql) < 500 else self.sql[:497] + "...", kind="duckdb")


def sql(query: str, con: duckdb.DuckDBPyConnection | None = None) -> QuerySource:
    """Use a DuckDB query as a source. Pass ``con`` to run on your own connection.

    >>> dp.inspect(dp.sql("SELECT * FROM orders WHERE day = '2026-11-01'", con=my_con))
    """
    if not query.strip().lower().startswith(("select", "with", "from", "values", "table", "(")):
        query = f"SELECT * FROM {query}"
    return QuerySource(query, con)


# -------------------------------------------------------------------- registry

Matcher = Callable[[Any], bool]
Factory = Callable[..., Source]
_REGISTRY: list[tuple[str, Matcher, Factory]] = []


def register_source(name: str, matcher: Matcher, factory: Factory, *, first: bool = True) -> None:
    """Teach DataPassport to read a new kind of object.

    ``matcher(obj)`` returns True when the adapter handles ``obj``; ``factory(obj, **options)``
    returns an object with a ``kind`` attribute and a ``register(con, name)`` method
    that creates a view or table called ``name`` and returns a :class:`SourceInfo`.
    """
    entry = (name, matcher, factory)
    _REGISTRY[:] = [e for e in _REGISTRY if e[0] != name]
    if first:
        _REGISTRY.insert(0, entry)
    else:
        _REGISTRY.append(entry)


def _module_of(obj: Any) -> str:
    return type(obj).__module__.split(".")[0]


def _builtin() -> None:
    register_source(
        "polars-lazy",
        lambda o: _module_of(o) == "polars" and type(o).__name__ == "LazyFrame",
        lambda o, **_: FrameSource(o, "polars-lazy"),
        first=False,
    )
    register_source(
        "polars",
        lambda o: _module_of(o) == "polars" and type(o).__name__ == "DataFrame",
        lambda o, **_: FrameSource(o, "polars"),
        first=False,
    )
    register_source(
        "pandas",
        lambda o: _module_of(o) == "pandas" and type(o).__name__ == "DataFrame",
        lambda o, **_: FrameSource(o, "pandas"),
        first=False,
    )
    register_source("arrow", lambda o: _module_of(o) == "pyarrow", lambda o, **_: FrameSource(o, "arrow"), first=False)
    register_source(
        "arrow-stream", lambda o: hasattr(o, "__arrow_c_stream__"), lambda o, **_: FrameSource(o, "arrow"), first=False
    )


_builtin()


def resolve(
    obj: Any, *, format: str | None = None, read_options: dict[str, Any] | None = None, hash_bytes: bool = True
) -> Source:
    """Pick an adapter for ``obj``."""
    from .plugins import load_entry_points

    load_entry_points()
    if isinstance(obj, (QuerySource, FileSource)) or (
        isinstance(obj, Source) and not isinstance(obj, (str, os.PathLike))
    ):
        return obj  # type: ignore[return-value]
    if isinstance(obj, (str, os.PathLike)):
        return FileSource(obj, format=format, read_options=read_options, hash_bytes=hash_bytes)
    for _name, matcher, factory in _REGISTRY:
        try:
            ok = matcher(obj)
        except Exception:
            ok = False
        if ok:
            return factory(obj, format=format, read_options=read_options)
    raise SourceError(
        f"Don't know how to read an object of type {type(obj).__module__}.{type(obj).__name__}",
        hint="Pass a file path, a Polars/pandas DataFrame, an Arrow table, dp.sql(...), "
        "or register an adapter with datapassport.register_source().",
    )


def load(source: Source, con: duckdb.DuckDBPyConnection, name: str) -> Loaded:
    info = source.register(con, name)
    rel = con.sql(f"SELECT * FROM {quote_ident(name)}")
    cols = [Column(n, logical_type(t), str(t), str(t.id).lower()) for n, t in zip(rel.columns, rel.types, strict=True)]
    seen: set[str] = set()
    for c in cols:
        if c.name in seen:
            raise SourceError(
                f"Duplicate column name {c.name!r}", hint="Rename the column; DataPassport needs unique names."
            )
        seen.add(c.name)
    return Loaded(con, name, info, cols)
