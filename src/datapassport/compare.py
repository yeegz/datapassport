"""Compare two versions of a dataset: schema evolution, row changes and drift."""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from ._types import quote_ident
from .drift import ColumnDrift, column_drift
from .engine import Engine, inspect, open_source
from .errors import IncompatibleError
from .fingerprint import sql_field
from .models import ColumnProfile, Passport, is_passport_file
from .sources import Loaded


class SchemaChange(BaseModel):
    kind: Literal["added", "removed", "renamed", "type_changed", "moved"]
    column: str
    to_column: str | None = None
    from_type: str | None = None
    to_type: str | None = None
    breaking: bool = Field(description="Removed, renamed or narrowed columns can break readers.")
    confidence: Literal["exact", "likely"] | None = Field(
        None, description="For renames: exact = identical values; likely = same type and similar distribution."
    )

    def describe(self) -> str:
        if self.kind == "added":
            return f"added {self.column} ({self.to_type})"
        if self.kind == "removed":
            return f"removed {self.column} ({self.from_type})"
        if self.kind == "renamed":
            hedge = " (likely: similar values)" if self.confidence == "likely" else ""
            return f"renamed {self.column} → {self.to_column}{hedge}"
        if self.kind == "type_changed":
            return f"{self.column}: {self.from_type} → {self.to_type}"
        return f"moved {self.column}"


class RowChanges(BaseModel):
    method: Literal["key", "multiset", "summary"]
    key: list[str] = Field(default_factory=list)
    before: int
    after: int
    added: int | None = None
    removed: int | None = None
    changed: int | None = None
    unchanged: int | None = None
    changed_by_column: dict[str, int] = Field(default_factory=dict)
    examples: dict[str, list[list[Any]]] | None = Field(
        None, description="Key values of example rows (only when examples > 0 was requested)."
    )
    note: str | None = None


class VersionRef(BaseModel):
    name: str | None
    uri: str | None
    fingerprint: str
    rows: int
    created_at: _dt.datetime


class Comparison(BaseModel):
    format: Literal["datapassport/comparison"] = "datapassport/comparison"
    format_version: int = 1
    base: VersionRef
    target: VersionRef
    identical: bool = Field(description="Same content fingerprint (row order ignored).")
    schema_changes: list[SchemaChange] = Field(default_factory=list)
    changed_columns: list[str] = Field(
        default_factory=list, description="Columns present in both whose values changed (by column fingerprint)."
    )
    rows: RowChanges
    duplicates: dict[str, int] = Field(default_factory=dict)
    drift: dict[str, ColumnDrift] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)

    # Passports are kept for reports but not serialised.
    _base_passport: Passport | None = None
    _target_passport: Passport | None = None

    @property
    def breaking_changes(self) -> list[SchemaChange]:
        return [c for c in self.schema_changes if c.breaking]

    @property
    def drifted(self) -> dict[str, ColumnDrift]:
        return {k: v for k, v in self.drift.items() if v.status in {"warn", "fail"}}

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)

    def to_json(self, path: str | Path | None = None, *, indent: int = 2) -> str:
        text = json.dumps(self.to_dict(), indent=indent, ensure_ascii=False) + "\n"
        if path is not None:
            Path(path).write_text(text, encoding="utf-8")
        return text

    def to_markdown(self) -> str:
        from .report.markdown import comparison_markdown

        return comparison_markdown(self)

    def to_html(self, path: str | Path | None = None) -> str:
        from .report.html import comparison_html

        html = comparison_html(self)
        if path is not None:
            Path(path).write_text(html, encoding="utf-8")
        return html

    def _repr_html_(self) -> str:
        from .report.html import comparison_fragment

        return comparison_fragment(self)

    def summary(self) -> str:
        """One-line summary, e.g. for logs."""
        if self.identical:
            return "identical content"
        bits = []
        r = self.rows
        if r.added is not None:
            bits.append(f"+{r.added} -{r.removed}" + (f" ~{r.changed}" if r.changed is not None else "") + " rows")
        else:
            bits.append(f"rows {r.before} → {r.after}")
        if self.schema_changes:
            bits.append(f"{len(self.schema_changes)} schema change(s)")
        if self.changed_columns:
            bits.append(f"{len(self.changed_columns)} column(s) changed")
        if self.drifted:
            bits.append(f"drift in {', '.join(self.drifted)}")
        return "; ".join(bits)


# ------------------------------------------------------------------- schema


_WIDENING = {("integer", "float"), ("integer", "decimal"), ("decimal", "float"), ("date", "timestamp"), ("null", "*")}


def _is_widening(a: str, b: str) -> bool:
    return (a, b) in _WIDENING or a == "null" or b == "string"


def _similar(a: ColumnProfile, b: ColumnProfile) -> bool:
    """Same-typed columns whose distributions are close: a probable rename."""
    if a.sensitive or b.sensitive or min(a.count, b.count) == 0:
        return False
    if not 0.5 <= b.count / a.count <= 2:
        return False
    d = column_drift(a, b, min_count=1)
    if d.kind == "categorical" or (d.js is not None and d.kind != "numeric"):
        return d.js is not None and d.js < 0.1
    if d.kind in {"numeric", "temporal"}:
        return d.ks is not None and d.ks < 0.05
    return False


def schema_diff(base: Passport, target: Passport) -> list[SchemaChange]:
    bt, tt = base.types, target.types
    removed = [c for c in base.column_names if c not in tt]
    added = [c for c in target.column_names if c not in bt]
    changes: list[SchemaChange] = []
    bfp, tfp = base.fingerprint.columns, target.fingerprint.columns
    for r in list(removed):
        match = next((a for a in added if bfp.get(r) and bfp.get(r) == tfp.get(a)), None)
        if match:
            changes.append(
                SchemaChange(
                    kind="renamed",
                    column=r,
                    to_column=match,
                    confidence="exact",
                    from_type=bt[r],
                    to_type=tt[match],
                    breaking=True,
                )
            )
            removed.remove(r)
            added.remove(match)
    for r in list(removed):
        match = next((a for a in added if bt[r] == tt[a] and _similar(base.columns[r], target.columns[a])), None)
        if match:
            changes.append(
                SchemaChange(
                    kind="renamed",
                    column=r,
                    to_column=match,
                    confidence="likely",
                    from_type=bt[r],
                    to_type=tt[match],
                    breaking=True,
                )
            )
            removed.remove(r)
            added.remove(match)
    changes += [SchemaChange(kind="removed", column=c, from_type=bt[c], breaking=True) for c in removed]
    changes += [SchemaChange(kind="added", column=c, to_type=tt[c], breaking=False) for c in added]
    for c in base.column_names:
        if c in tt and bt[c] != tt[c]:
            changes.append(
                SchemaChange(
                    kind="type_changed",
                    column=c,
                    from_type=bt[c],
                    to_type=tt[c],
                    breaking=not _is_widening(bt[c], tt[c]),
                )
            )
    common_b = [c for c in base.column_names if c in tt]
    common_t = [c for c in target.column_names if c in bt]
    if common_b != common_t:
        changes += [
            SchemaChange(kind="moved", column=c, breaking=False) for i, c in enumerate(common_t) if common_b[i] != c
        ]
    return changes


# --------------------------------------------------------------------- rows


def _common(a: Loaded, b: Loaded) -> list[str]:
    bn = {c.name for c in b.columns}
    return [c.name for c in a.columns if c.name in bn]


def _fields(data: Loaded, names: list[str], float_digits: int) -> list[str]:
    cols = {c.name: c for c in data.columns}
    return [sql_field(n, cols[n].type, cols[n].type_id, float_digits=float_digits) for n in names]


def keyed_diff(a: Loaded, b: Loaded, key: list[str], *, float_digits: int, examples: int) -> RowChanges:
    con = a.con
    common = [n for n in _common(a, b) if n not in key]
    ka = [quote_ident(k) for k in key]
    fa = _fields(a, common, float_digits)
    fb = _fields(b, common, float_digits)
    sel_a = ", ".join([f"{k} AS k{i}" for i, k in enumerate(ka)] + [f"{e} AS v{i}" for i, e in enumerate(fa)])
    sel_b = ", ".join([f"{k} AS k{i}" for i, k in enumerate(ka)] + [f"{e} AS v{i}" for i, e in enumerate(fb)])
    join = " AND ".join(f"a.k{i} IS NOT DISTINCT FROM b.k{i}" for i in range(len(key)))
    diff_any = " OR ".join(f"a.v{i} <> b.v{i}" for i in range(len(common))) or "false"
    con.execute(
        f"CREATE OR REPLACE TEMP TABLE __dp_diff AS "
        f"WITH a AS (SELECT {sel_a}, true AS __in FROM {a.ref}), "
        f"b AS (SELECT {sel_b}, true AS __in FROM {b.ref}) "
        f"SELECT {', '.join(f'coalesce(a.k{i}, b.k{i}) AS k{i}' for i in range(len(key)))}, "
        f"CASE WHEN a.__in IS NULL THEN 'added' WHEN b.__in IS NULL THEN 'removed' "
        f"WHEN {diff_any} THEN 'changed' ELSE 'same' END AS status"
        + "".join(f", (a.__in AND b.__in AND a.v{i} <> b.v{i}) AS c{i}" for i in range(len(common)))
        + f" FROM a FULL OUTER JOIN b ON {join}"
    )
    aggs = [
        "count(*) FILTER (WHERE status = 'added')",
        "count(*) FILTER (WHERE status = 'removed')",
        "count(*) FILTER (WHERE status = 'changed')",
        "count(*) FILTER (WHERE status = 'same')",
    ]
    aggs += [f"count(*) FILTER (WHERE c{i})" for i in range(len(common))]
    res = con.execute(f"SELECT {', '.join(aggs)} FROM __dp_diff").fetchone()
    assert res is not None
    by_col = {n: int(res[4 + i]) for i, n in enumerate(common) if res[4 + i]}
    ex = None
    if examples > 0:
        ex = {}
        keys = ", ".join(f"k{i}" for i in range(len(key)))
        for status in ("added", "removed", "changed"):
            rows = con.execute(
                f"SELECT {keys} FROM __dp_diff WHERE status = ? ORDER BY {keys} LIMIT {int(examples)}", [status]
            ).fetchall()
            ex[status] = [[_jsonable(v) for v in r] for r in rows]
    con.execute("DROP TABLE __dp_diff")
    before = con.execute(f"SELECT count(*) FROM {a.ref}").fetchone()[0]  # type: ignore[index]
    after = con.execute(f"SELECT count(*) FROM {b.ref}").fetchone()[0]  # type: ignore[index]
    return RowChanges(
        method="key",
        key=key,
        before=before,
        after=after,
        added=int(res[0]),
        removed=int(res[1]),
        changed=int(res[2]),
        unchanged=int(res[3]),
        changed_by_column=by_col,
        examples=ex,
    )


def multiset_diff(a: Loaded, b: Loaded, *, float_digits: int) -> RowChanges:
    from .fingerprint import column_order

    common = _common(a, b)
    order = column_order(common)

    def enc(d: Loaded) -> str:
        fs = _fields(d, order, float_digits)
        return "md5_number(concat(" + ", ".join(fs) + "))" if fs else "0"

    res = a.con.execute(
        f"WITH a AS (SELECT {enc(a)} AS h, count(*) AS n FROM {a.ref} GROUP BY 1), "
        f"b AS (SELECT {enc(b)} AS h, count(*) AS n FROM {b.ref} GROUP BY 1) "
        "SELECT sum(greatest(coalesce(b.n,0) - coalesce(a.n,0), 0)), "
        "sum(greatest(coalesce(a.n,0) - coalesce(b.n,0), 0)), "
        "sum(least(coalesce(a.n,0), coalesce(b.n,0))), "
        "(SELECT count(*) FROM " + a.ref + "), (SELECT count(*) FROM " + b.ref + ") "
        "FROM a FULL OUTER JOIN b ON a.h = b.h"
    ).fetchone()
    assert res is not None
    note = "No key given: an edited row counts as one removed and one added row."
    if len(common) < max(len(a.columns), len(b.columns)):
        note += " Compared on the columns both versions share."
    return RowChanges(
        method="multiset",
        before=int(res[3]),
        after=int(res[4]),
        added=int(res[0] or 0),
        removed=int(res[1] or 0),
        unchanged=int(res[2] or 0),
        note=note,
    )


def _jsonable(v: Any) -> Any:
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    return str(v)


# ------------------------------------------------------------------- compare


def _is_passport_like(obj: Any) -> bool:
    return isinstance(obj, Passport) or (isinstance(obj, (str, Path)) and is_passport_file(obj))


def _ref(p: Passport) -> VersionRef:
    return VersionRef(
        name=p.name, uri=p.source.uri, fingerprint=p.fingerprint.dataset, rows=p.rows, created_at=p.created_at
    )


def compare(
    base: Any,
    target: Any,
    *,
    key: str | list[str] | None = None,
    drift: dict[str, dict[str, Any]] | None = None,
    examples: int = 0,
    sample: int | float | None = None,
    privacy: str = "safe",
    sensitive: list[str] | tuple[str, ...] = (),
    float_digits: int = 17,
    engine: Engine | None = None,
    format: str | None = None,
    read_options: dict[str, Any] | None = None,
) -> Comparison:
    """Compare two versions of a dataset.

    Each side may be data (path, frame, ``dp.sql``) or a passport (a
    :class:`Passport` or a passport JSON file). With data on both sides and a
    ``key``, rows are matched by key and changes are counted per column. With
    data on both sides and no key, rows are compared as multisets. With a
    passport on either side, row counts, column fingerprints and drift are
    compared from the summaries.

    ``drift`` maps a column name (or ``"default"``) to ``{"metric": "psi",
    "warn": 0.1, "fail": 0.25}``.
    """
    keys = [key] if isinstance(key, str) else list(key or [])
    notes: list[str] = []
    la = lb = None
    con = None
    if not _is_passport_like(base) and not _is_passport_like(target):
        la = open_source(base, engine=engine, format=format, read_options=read_options)
        lb = open_source(target, con=la.con, format=format, read_options=read_options)
        con = la.con

    def passport(obj: Any, loaded: Loaded | None) -> Passport:
        if isinstance(obj, Passport):
            return obj
        if loaded is None and _is_passport_like(obj):
            return Passport.load(obj)
        return inspect(
            obj,
            key=keys or None,
            sample=sample,
            privacy=privacy,
            sensitive=sensitive,
            float_digits=float_digits,
            engine=engine,
            format=format,
            read_options=read_options,
            _loaded=loaded,
        )

    pa = passport(base, la)
    pb = passport(target, lb)
    if pa.fingerprint.spec != pb.fingerprint.spec or pa.fingerprint.float_digits != pb.fingerprint.float_digits:
        raise IncompatibleError(
            "These passports use different fingerprint settings "
            f"({pa.fingerprint.spec}, float_digits={pa.fingerprint.float_digits} vs "
            f"{pb.fingerprint.spec}, float_digits={pb.fingerprint.float_digits})",
            hint="Re-create one passport with the same --float-digits.",
        )
    if pa.options.token_salted != pb.options.token_salted:
        notes.append("Category tokens use different salts; categorical drift is unreliable.")

    # Rows
    if la is not None and lb is not None and con is not None:
        if keys:
            dup = (pa.duplicates.key.duplicates if pa.duplicates.key else 0) + (
                pb.duplicates.key.duplicates if pb.duplicates.key else 0
            )
            if dup:
                notes.append(f"Key {keys} is not unique ({dup} duplicate keys); compared rows as multisets instead.")
                rows = multiset_diff(la, lb, float_digits=float_digits)
            else:
                rows = keyed_diff(la, lb, keys, float_digits=float_digits, examples=examples)
        else:
            rows = multiset_diff(la, lb, float_digits=float_digits)
    else:
        rows = RowChanges(
            method="summary",
            before=pa.rows,
            after=pb.rows,
            note="Compared from passports: row-level changes need both datasets.",
        )

    changed_cols = [
        c
        for c in pa.column_names
        if c in pb.fingerprint.columns
        and c in pa.fingerprint.columns
        and pa.fingerprint.columns[c] != pb.fingerprint.columns[c]
        and pa.types.get(c) == pb.types.get(c)
    ]
    if rows.changed_by_column:
        changed_cols = [c for c in pa.column_names if rows.changed_by_column.get(c)] or changed_cols

    drift_cfg = drift or {}
    default = drift_cfg.get("default", {})
    drift_out: dict[str, ColumnDrift] = {}
    for c in pb.column_names:
        if c not in pa.columns:
            continue
        cfg = {**default, **drift_cfg.get(c, {})}
        # Keys are identifiers: their distribution shifting is expected, not drift.
        if cfg.get("skip") or (c in keys and c not in drift_cfg):
            continue
        drift_out[c] = column_drift(
            pa.columns[c],
            pb.columns[c],
            metric=cfg.get("metric"),
            warn=cfg.get("warn"),
            fail=cfg.get("fail"),
            min_count=int(cfg.get("min_count", 50)),
        )
    if pa.sample.method != "full" or pb.sample.method != "full":
        notes.append("Profiles were sampled; drift metrics carry sampling error.")

    comp = Comparison(
        base=_ref(pa),
        target=_ref(pb),
        identical=pa.fingerprint.dataset == pb.fingerprint.dataset,
        schema_changes=schema_diff(pa, pb),
        changed_columns=changed_cols,
        rows=rows,
        duplicates={"base": pa.duplicates.rows, "target": pb.duplicates.rows},
        drift=drift_out,
        notes=notes,
    )
    comp._base_passport = pa
    comp._target_passport = pb
    return comp
