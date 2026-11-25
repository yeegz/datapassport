"""Extension points: custom rules, custom metrics and plugin discovery.

Custom rule::

    import datapassport as dp

    @dp.rule("total_matches_items")
    def total_matches_items(ctx: dp.RuleContext) -> dp.Outcome:
        bad = ctx.count_where('abs(total - (price * quantity)) > 0.01')
        return dp.Outcome(passed=bad == 0, observed=bad, message=f"{bad} rows where total != price × quantity")

Use it in a contract with ``checks: [{rule: total_matches_items}]``.

Custom metric (added to every matching column profile under ``extras``)::

    @dp.metric("p_negative", types=["integer", "float"])
    def p_negative(ctx: dp.MetricContext) -> float:
        return ctx.scalar(f"avg(CASE WHEN {ctx.col} < 0 THEN 1 ELSE 0 END)")

Packages can register plugins automatically with an entry point in the
``datapassport.plugins`` group pointing at a module or a zero-argument callable.
"""

from __future__ import annotations

import importlib.metadata
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ._types import quote_ident
from .errors import PluginError

if TYPE_CHECKING:
    from .models import ColumnProfile, Passport
    from .sources import Loaded


@dataclass
class Outcome:
    """What a rule returns."""

    passed: bool
    observed: Any = None
    message: str | None = None
    failing_rows: int | None = None


@dataclass
class RuleContext:
    """Everything a rule may look at. ``relation`` is a quoted SQL name for the data."""

    data: Loaded | None
    passport: Passport
    baseline: Passport | None
    params: dict[str, Any] = field(default_factory=dict)
    column: str | None = None

    @property
    def relation(self) -> str:
        if self.data is None:
            raise PluginError("This rule needs the data, but only a passport was given.")
        return self.data.ref

    @property
    def col(self) -> str:
        """The quoted column name, for column-scoped rules."""
        if self.column is None:
            raise PluginError("This rule must be used on a column (under columns.<name>.checks).")
        return quote_ident(self.column)

    def sql(self, query: str, params: list[Any] | None = None) -> list[tuple[Any, ...]]:
        """Run SQL. Refer to the dataset as ``{data}``."""
        if self.data is None:
            raise PluginError("This rule needs the data, but only a passport was given.")
        return self.data.con.execute(query.replace("{data}", self.relation), params or []).fetchall()

    def scalar(self, expr: str) -> Any:
        return self.sql(f"SELECT {expr} FROM {{data}}")[0][0]

    def count_where(self, condition: str) -> int:
        return int(self.scalar(f"count(*) FILTER (WHERE {condition})"))


@dataclass
class MetricContext:
    data: Loaded
    relation: str
    column: str
    type: str

    @property
    def col(self) -> str:
        return quote_ident(self.column)

    def scalar(self, expr: str) -> Any:
        row = self.data.con.execute(f"SELECT {expr} FROM {self.relation}").fetchone()
        return row[0] if row else None


RuleFn = Callable[[RuleContext], Outcome]
MetricFn = Callable[[MetricContext], Any]

_RULES: dict[str, RuleFn] = {}
_METRICS: dict[str, tuple[MetricFn, tuple[str, ...] | None]] = {}
_LOADED = False


def rule(name: str) -> Callable[[RuleFn], RuleFn]:
    """Register a custom rule usable from contracts by ``name``."""

    def deco(fn: RuleFn) -> RuleFn:
        _RULES[name] = fn
        return fn

    return deco


def metric(name: str, types: Iterable[str] | None = None) -> Callable[[MetricFn], MetricFn]:
    """Register a custom column metric. ``types`` limits it to logical types."""

    def deco(fn: MetricFn) -> MetricFn:
        _METRICS[name] = (fn, tuple(types) if types is not None else None)
        return fn

    return deco


def unregister(name: str) -> None:
    """Remove a custom rule or metric (mainly for tests)."""
    _RULES.pop(name, None)
    _METRICS.pop(name, None)


def get_rule(name: str) -> RuleFn | None:
    load_entry_points()
    return _RULES.get(name)


def registered_rules() -> list[str]:
    load_entry_points()
    return sorted(_RULES)


def run_metrics(data: Loaded, ref: str, profiles: dict[str, ColumnProfile], *, sensitive: set[str]) -> None:
    load_entry_points()
    for mname, (fn, types) in _METRICS.items():
        for col, prof in profiles.items():
            if col in sensitive or (types is not None and prof.type not in types):
                continue
            try:
                prof.extras[mname] = fn(MetricContext(data, ref, col, prof.type))
            except Exception as e:
                raise PluginError(f"Metric {mname!r} failed on column {col!r}: {e}") from e


def load_entry_points() -> None:
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    for ep in importlib.metadata.entry_points(group="datapassport.plugins"):
        try:
            obj = ep.load()
            if callable(obj):
                obj()
        except Exception as e:
            raise PluginError(f"Plugin {ep.name!r} ({ep.value}) failed to load: {e}") from e
