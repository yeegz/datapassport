"""The analysis engine: runs fingerprint and profile queries in DuckDB."""

from __future__ import annotations

import datetime as _dt
import hashlib
import itertools
import os
import platform
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

import duckdb

from . import __about__
from ._types import is_nested, is_numeric, is_temporal, is_textual, quote_ident
from .errors import SourceError
from .fingerprint import (
    DEFAULT_FLOAT_DIGITS,
    SPEC,
    column_order,
    combine,
    combine_column,
    schema_digest,
    sql_field,
)
from .models import (
    Categories,
    ColumnProfile,
    ColumnSchema,
    DuplicateStats,
    Fingerprint,
    KeyStats,
    NumericStats,
    Options,
    Passport,
    Producer,
    SampleInfo,
    TemporalStats,
    TextStats,
)
from .sources import Column, Loaded, QuerySource, load, resolve

MASK64 = (1 << 64) - 1
QUANTILE_POINTS = [i / 100 for i in range(101)]
EXACT_DISTINCT_LIMIT = 1_000_000
EXACT_QUANTILE_LIMIT = 1_000_000
_counter = itertools.count()


@dataclass
class Engine:
    """DuckDB settings. ``None`` keeps DuckDB's default.

    Environment variables ``DATAPASSPORT_THREADS``, ``DATAPASSPORT_MEMORY_LIMIT`` and
    ``DATAPASSPORT_TEMP_DIRECTORY`` fill in unset fields.
    """

    threads: int | None = None
    memory_limit: str | None = None
    temp_directory: str | None = None

    def connect(self) -> duckdb.DuckDBPyConnection:
        con = duckdb.connect(":memory:")
        threads = self.threads or _env_int("DATAPASSPORT_THREADS")
        memory = self.memory_limit or os.environ.get("DATAPASSPORT_MEMORY_LIMIT")
        temp = self.temp_directory or os.environ.get("DATAPASSPORT_TEMP_DIRECTORY")
        if threads:
            con.execute(f"SET threads = {int(threads)}")
        if memory:
            con.execute("SET memory_limit = ?", [memory])
        if temp:
            con.execute("SET temp_directory = ?", [temp])
        con.execute("SET TimeZone = 'UTC'")
        # Avoid changing the setting if it is already off. DuckDB may initialise
        # the Jupyter progress renderer when changing it, which requires ipywidgets.
        [(progress_enabled,)] = con.execute("SELECT current_setting('enable_progress_bar')").fetchall()
        if progress_enabled:
            con.execute("SET enable_progress_bar = false")
        return con


def _env_int(name: str) -> int | None:
    v = os.environ.get(name)
    return int(v) if v and v.isdigit() else None


def producer() -> Producer:
    return Producer(
        version=__about__.__version__,
        engine=f"duckdb {duckdb.__version__}",
        python=platform.python_version(),
        platform=f"{sys.platform}-{platform.machine()}",
    )


def token(value: str, salt: str | None = None) -> str:
    """Stable 16-hex-digit token for a category value."""
    prefix = f"dp-token/1:{salt}:" if salt else "dp-token/1:"
    return hashlib.sha256((prefix + value).encode("utf-8")).hexdigest()[:16]


# ------------------------------------------------------------------ open source


def open_source(
    source: Any,
    *,
    engine: Engine | None = None,
    format: str | None = None,
    read_options: dict[str, Any] | None = None,
    hash_bytes: bool = True,
    con: duckdb.DuckDBPyConnection | None = None,
) -> Loaded:
    src = resolve(source, format=format, read_options=read_options, hash_bytes=hash_bytes)
    if isinstance(src, QuerySource) and src.con is not None:
        con = src.con
    if con is None:
        con = (engine or Engine()).connect()
    return load(src, con, f"__dp_{next(_counter)}")


# ----------------------------------------------------------------- fingerprint


@dataclass
class FingerprintResult:
    fingerprint: Fingerprint
    duplicate_rows: int | None


def compute_fingerprint(
    data: Loaded,
    *,
    float_digits: int = DEFAULT_FLOAT_DIGITS,
    duplicates: bool = True,
    columns: bool = True,
) -> FingerprintResult:
    cols = data.columns
    fields = [f"{sql_field(c.name, c.type, c.type_id, float_digits=float_digits)} AS f{i}" for i, c in enumerate(cols)]
    # The row encoding (see fingerprint.sql_row_encoding) is assembled from the
    # f-columns so each field expression is computed once.
    by_name = {c.name: i for i, c in enumerate(cols)}
    row_from_fields = ("concat(" + ", ".join(f"f{by_name[n]}" for n in column_order(by_name)) + ")") if cols else "''"
    # md5_number() hashes once and returns all 128 bits. Its low 64 bits equal
    # md5_number_upper() and its high 64 bits md5_number_lower() (the spec's
    # "hi" and "lo" lanes), so each value is hashed exactly once.
    hashes = ["md5_number(r) AS h"] + [f"md5_number(f{i}) AS h{i}" for i in range(len(cols) if columns else 0)]

    def lanes(h: str) -> list[str]:
        # Mask the shifted high 64 bits too: DuckDB 1.1 returns signed HUGEINT from md5_number().
        return [f"sum(CAST({h} & {MASK64} AS UBIGINT))", f"sum(CAST(({h} >> 64) & {MASK64} AS UBIGINT))"]

    aggs = ["count(*) AS n", *lanes("h")]
    if duplicates:
        aggs.append("count(DISTINCT h) AS d")
    if columns:
        for i in range(len(cols)):
            aggs += lanes(f"h{i}")
    select_fields = ", ".join(fields) if fields else "1 AS _dp_empty"
    query = (
        f"WITH e AS (SELECT {select_fields} FROM {data.ref}), "
        f"x AS (SELECT {', '.join(hashes)} FROM (SELECT *, {row_from_fields} AS r FROM e)) "
        f"SELECT {', '.join(aggs)} FROM x"
    )
    res = data.con.execute(query).fetchone()
    assert res is not None
    n = int(res[0])
    hi = int(res[1] or 0) & MASK64
    lo = int(res[2] or 0) & MASK64
    pos = 3
    dup = None
    if duplicates:
        dup = n - int(res[3]) if n else 0
        pos = 4
    schema = schema_digest([(c.name, c.type) for c in cols])
    col_fps: dict[str, str] = {}
    if columns:
        for i, c in enumerate(cols):
            chi = int(res[pos + 2 * i] or 0)
            clo = int(res[pos + 2 * i + 1] or 0)
            col_fps[c.name] = combine_column(c.name, c.type, n, chi, clo, float_digits=float_digits)
    fp = Fingerprint(
        spec=SPEC,
        dataset=combine(schema, n, hi, lo, float_digits=float_digits),
        schema_=schema,
        rows=n,
        float_digits=float_digits,
        columns=col_fps,
    )
    return FingerprintResult(fp, dup)


def fingerprint(
    source: Any,
    *,
    float_digits: int = DEFAULT_FLOAT_DIGITS,
    engine: Engine | None = None,
    format: str | None = None,
    read_options: dict[str, Any] | None = None,
) -> Fingerprint:
    """Compute only the content fingerprint of a dataset (one pass, no profile)."""
    data = open_source(source, engine=engine, format=format, read_options=read_options, hash_bytes=False)
    return compute_fingerprint(data, float_digits=float_digits, duplicates=False).fingerprint


# --------------------------------------------------------------------- profile


def _key_stats(data: Loaded, key: Sequence[str]) -> KeyStats:
    missing = [k for k in key if k not in {c.name for c in data.columns}]
    if missing:
        raise SourceError(
            f"Key column(s) not found: {', '.join(missing)}",
            hint=f"Available columns: {', '.join(c.name for c in data.columns)}",
        )
    ks = [quote_ident(k) for k in key]
    any_null = " OR ".join(f"{k} IS NULL" for k in ks)
    tup = ks[0] if len(ks) == 1 else "(" + ", ".join(ks) + ")"
    q = (
        f"SELECT count(*) FILTER (WHERE {any_null}), "
        f"count(*) FILTER (WHERE NOT ({any_null})) - count(DISTINCT {tup}) FILTER (WHERE NOT ({any_null})) "
        f"FROM {data.ref}"
    )
    nulls, dups = data.con.execute(q).fetchone()  # type: ignore[misc]
    return KeyStats(columns=list(key), duplicates=int(dups), nulls=int(nulls))


def _sample(
    data: Loaded, rows: int, target: int | float | None, seed: int, float_digits: int
) -> tuple[str, SampleInfo]:
    if target is None:
        return data.ref, SampleInfo(method="full", rows_profiled=rows)
    want = int(target * rows) if isinstance(target, float) and target <= 1 else int(target)
    if want >= rows:
        return data.ref, SampleInfo(method="full", target_rows=want, seed=seed, rows_profiled=rows)
    # Content-addressed sampling: a row is kept when a seeded hash of its values
    # falls under a threshold. Unchanged rows are sampled the same way in every
    # version and in any row order. DuckDB's native hash() is used because it is
    # ~25x cheaper than the fingerprint encoding; it is deterministic for a given
    # DuckDB version (recorded in the passport), which is all sampling needs.
    del float_digits
    threshold = max(1, round(want / rows * 1_000_000))
    cols = ", ".join(quote_ident(n) for n in column_order([c.name for c in data.columns]))
    name = f"{data.name}_sample"
    data.con.execute(
        f"CREATE OR REPLACE TEMP TABLE {quote_ident(name)} AS SELECT * FROM {data.ref} "
        f"WHERE hash({int(seed)}, {cols}) % 1000000 < {threshold}"
    )
    got = data.con.execute(f"SELECT count(*) FROM {quote_ident(name)}").fetchone()[0]  # type: ignore[index]
    return quote_ident(name), SampleInfo(method="hash", target_rows=want, seed=seed, rows_profiled=int(got))


def _num(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f


def _temporal_seconds(c: Column) -> str:
    q = quote_ident(c.name)
    if c.type == "time":
        return f"(hour({q}) * 3600 + minute({q}) * 60 + microsecond({q}) / 1e6)"
    return f"epoch({q})"


def profile_columns(
    data: Loaded,
    ref: str,
    rows_profiled: int,
    *,
    top_k: int,
    privacy: str,
    quantiles: str,
    sensitive: set[str],
    token_salt: str | None,
) -> dict[str, ColumnProfile]:
    con = data.con
    exact_distinct = rows_profiled <= EXACT_DISTINCT_LIMIT
    use_exact_q = quantiles == "exact" or (quantiles == "auto" and rows_profiled <= EXACT_QUANTILE_LIMIT)
    aggs: list[str] = []
    plan: list[tuple[Column, list[str]]] = []
    for c in data.columns:
        q = quote_ident(c.name)
        names: list[str] = []

        def add(expr: str, label: str, names: list[str] = names) -> None:
            aggs.append(expr)
            names.append(label)

        add(f"count({q})", "count")
        if is_nested(c.type) or c.type == "null":
            add(f"approx_count_distinct({q})" if not is_nested(c.type) else "NULL", "distinct")
        elif exact_distinct:
            add(f"count(DISTINCT {q})", "distinct")
        else:
            add(f"approx_count_distinct({q})", "distinct")
        if c.name not in sensitive:
            if is_numeric(c.type):
                d = f"CAST({q} AS DOUBLE)"
                fin = f"isfinite({d})"
                add(f"min({d}) FILTER (WHERE {fin})", "min")
                add(f"max({d}) FILTER (WHERE {fin})", "max")
                add(f"avg({d}) FILTER (WHERE {fin})", "mean")
                add(f"stddev_samp({d}) FILTER (WHERE {fin})", "std")
                add(f"count(*) FILTER (WHERE {d} = 0)", "zeros")
                add(f"count(*) FILTER (WHERE {d} < 0 AND {fin})", "negatives")
                if c.type == "float":
                    add(f"count(*) FILTER (WHERE isnan({q}))", "nan")
                    add(f"count(*) FILTER (WHERE isinf({q}))", "infinite")
            elif is_textual(c.type):
                s = f"CAST({q} AS VARCHAR)"
                add(f"min(length({s}))", "min_length")
                add(f"max(length({s}))", "max_length")
                add(f"avg(length({s}))", "mean_length")
                add(f"count(*) FILTER (WHERE {s} = '')", "empty")
                add(f"count(*) FILTER (WHERE {s} <> '' AND trim({s}) = '')", "blank")
            elif is_temporal(c.type):
                add(f"CAST(min({q}) AS VARCHAR)", "tmin")
                add(f"CAST(max({q}) AS VARCHAR)", "tmax")
            elif c.type == "boolean":
                add(f"count(*) FILTER (WHERE {q})", "true")
                add(f"count(*) FILTER (WHERE NOT {q})", "false")
        plan.append((c, names))

    values = con.execute(f"SELECT {', '.join(aggs) or '1'} FROM {ref}").fetchone() or ()
    it = iter(values)
    out: dict[str, ColumnProfile] = {}
    for c, names in plan:
        st = {label: next(it) for label in names}
        count = int(st["count"])
        nulls = rows_profiled - count
        prof = ColumnProfile(
            name=c.name,
            type=c.type,
            count=count,
            nulls=nulls,
            null_fraction=(nulls / rows_profiled) if rows_profiled else 0.0,
            distinct=int(st["distinct"]) if st.get("distinct") is not None else None,
            distinct_exact=exact_distinct and not is_nested(c.type),
            sensitive=c.name in sensitive,
        )
        if c.name not in sensitive:
            if is_numeric(c.type):
                prof.numeric = NumericStats(
                    min=_num(st["min"]),
                    max=_num(st["max"]),
                    mean=_num(st["mean"]),
                    std=_num(st["std"]),
                    zeros=int(st["zeros"]),
                    negatives=int(st["negatives"]),
                    nan=int(st.get("nan") or 0),
                    infinite=int(st.get("infinite") or 0),
                    quantiles=_quantiles(con, ref, f"CAST({quote_ident(c.name)} AS DOUBLE)", use_exact_q),
                )
            elif is_textual(c.type):
                prof.text = TextStats(
                    min_length=st["min_length"],
                    max_length=st["max_length"],
                    mean_length=_num(st["mean_length"]),
                    empty=int(st["empty"]),
                    blank=int(st["blank"]),
                )
            elif is_temporal(c.type):
                prof.temporal = TemporalStats(
                    min=st["tmin"],
                    max=st["tmax"],
                    quantiles=_quantiles(con, ref, _temporal_seconds(c), use_exact_q),
                )
            elif c.type == "boolean":
                prof.boolean = {"true": int(st["true"]), "false": int(st["false"])}
            if _wants_categories(c, prof, top_k):
                prof.categories = _categories(con, ref, c, top_k, privacy, token_salt)
        out[c.name] = prof
    return out


def _wants_categories(c: Column, prof: ColumnProfile, top_k: int) -> bool:
    if top_k <= 0 or prof.count == 0 or prof.distinct is None:
        return False
    if c.type in {"string", "boolean"}:
        # Identifier-like columns (nearly every value unique) have no useful categories.
        return not (prof.distinct > 1000 and prof.distinct > 0.5 * prof.count)
    if c.type == "integer":
        return prof.distinct <= max(top_k, 50)
    return False


def _quantiles(con: duckdb.DuckDBPyConnection, ref: str, expr: str, exact: bool) -> list[float]:
    fn = "quantile_cont" if exact else "approx_quantile"
    pts = "[" + ", ".join(str(p) for p in QUANTILE_POINTS) + "]"
    row = con.execute(
        f"SELECT {fn}(v, {pts}) FROM (SELECT {expr} AS v FROM {ref}) WHERE v IS NOT NULL AND isfinite(v)"
    ).fetchone()
    if not row or row[0] is None:
        return []
    return [float(x) for x in row[0]]


def _categories(
    con: duckdb.DuckDBPyConnection, ref: str, c: Column, top_k: int, privacy: str, salt: str | None
) -> Categories:
    q = quote_ident(c.name)
    rows = con.execute(
        f"SELECT CAST({q} AS VARCHAR) AS v, count(*) AS n FROM {ref} WHERE {q} IS NOT NULL "
        f"GROUP BY 1 ORDER BY n DESC, v LIMIT {int(top_k)}"
    ).fetchall()
    total = con.execute(f"SELECT count({q}) FROM {ref}").fetchone()[0]  # type: ignore[index]
    vals = [str(v) for v, _ in rows]
    counts = [int(n) for _, n in rows]
    return Categories(
        tokens=[token(v, salt) for v in vals],
        counts=counts,
        values=vals if privacy == "values" else None,
        other=int(total) - sum(counts),
    )


# --------------------------------------------------------------------- inspect


def inspect(
    source: Any,
    *,
    name: str | None = None,
    key: str | Sequence[str] | None = None,
    sample: int | float | None = None,
    seed: int = 0,
    privacy: str = "safe",
    sensitive: Iterable[str] = (),
    top_k: int = 20,
    float_digits: int = DEFAULT_FLOAT_DIGITS,
    quantiles: str = "auto",
    duplicates: bool = True,
    metrics: bool = True,
    engine: Engine | None = None,
    format: str | None = None,
    read_options: dict[str, Any] | None = None,
    hash_bytes: bool = True,
    _loaded: Loaded | None = None,
) -> Passport:
    """Inspect a dataset and return its :class:`Passport`.

    ``source`` may be a path (CSV, TSV, JSON, JSON Lines, Parquet, a glob or a directory),
    a Polars/pandas DataFrame, a Polars LazyFrame, an Arrow table, ``dp.sql(...)``,
    or anything a registered adapter understands.

    The fingerprint always covers every row. ``sample`` limits only the profile:
    an int is a target row count, a float in (0, 1] a fraction.
    """
    if privacy not in {"safe", "values"}:
        raise ValueError("privacy must be 'safe' or 'values'")
    if quantiles not in {"auto", "exact", "approx"}:
        raise ValueError("quantiles must be 'auto', 'exact' or 'approx'")
    data = _loaded or open_source(
        source, engine=engine, format=format, read_options=read_options, hash_bytes=hash_bytes
    )
    keys = [key] if isinstance(key, str) else list(key or [])
    sens = set(sensitive)
    unknown = sens - {c.name for c in data.columns}
    if unknown:
        raise SourceError(f"Sensitive column(s) not found: {', '.join(sorted(unknown))}")
    salt = os.environ.get("DATAPASSPORT_TOKEN_SALT") or None

    fp = compute_fingerprint(data, float_digits=float_digits, duplicates=duplicates)
    rows = fp.fingerprint.rows
    ref, sample_info = _sample(data, rows, sample, seed, float_digits)
    profiles = profile_columns(
        data,
        ref,
        sample_info.rows_profiled,
        top_k=top_k,
        privacy=privacy,
        quantiles=quantiles,
        sensitive=sens,
        token_salt=salt,
    )
    if metrics:
        from .plugins import run_metrics

        run_metrics(data, ref, profiles, sensitive=sens)
    quant_method = (
        "exact"
        if quantiles == "exact" or (quantiles == "auto" and sample_info.rows_profiled <= EXACT_QUANTILE_LIMIT)
        else "approx"
    )
    info = data.info
    return Passport(
        name=name or _default_name(info.uri),
        created_at=_dt.datetime.now(_dt.UTC).replace(microsecond=0),
        producer=producer(),
        source=info,
        options=Options(
            float_digits=float_digits,
            privacy=privacy,  # type: ignore[arg-type]
            top_k=top_k,
            quantiles=quant_method,
            key=keys,  # type: ignore[arg-type]
            token_salted=salt is not None,
            sensitive=sorted(sens),
        ),
        sample=sample_info,
        schema_=[
            ColumnSchema(name=c.name, type=c.type, physical=c.physical, position=i) for i, c in enumerate(data.columns)
        ],
        fingerprint=fp.fingerprint,
        rows=rows,
        duplicates=DuplicateStats(rows=fp.duplicate_rows or 0, key=_key_stats(data, keys) if keys else None),
        columns=profiles,
    )


def _default_name(uri: str | None) -> str | None:
    if not uri:
        return None
    base = os.path.basename(uri.rstrip("/"))
    for suffix in (".gz",):
        base = base.removesuffix(suffix)
    return os.path.splitext(base)[0] or None
