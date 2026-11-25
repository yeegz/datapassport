"""DataPassport: portable evidence about datasets.

Quick start::

    import datapassport as dp

    passport = dp.inspect("orders.parquet", key="order_id")
    passport.to_json("orders.passport.json")

    diff = dp.compare("orders.passport.json", "orders_new.parquet")
    print(diff.summary())

    report = dp.check("orders_new.parquet", "contract.yml", baseline="orders.passport.json")
    report.raise_for_status()
"""

from __future__ import annotations

import os
from typing import Any

from .__about__ import __version__
from .compare import Comparison, RowChanges, SchemaChange, compare
from .contract import CheckSpec, ColumnSpec, Contract
from .drift import ColumnDrift
from .engine import Engine, fingerprint, inspect
from .errors import (
    CheckFailed,
    ContractError,
    DataPassportError,
    IncompatibleError,
    PluginError,
    SourceError,
)
from .models import ColumnProfile, Fingerprint, Passport
from .plugins import MetricContext, Outcome, RuleContext, metric, rule
from .rules import CheckReport, CheckResult, check
from .sources import Source, SourceInfo, register_source, sql


def load(path: str) -> Passport:
    """Load a passport JSON file."""
    return Passport.load(path)


def _same_kind_options(passport: Passport, source: Any) -> dict[str, Any] | None:
    """Reuse the passport's reader options only for data of the same format."""
    from .sources import FileSource

    try:
        kind = FileSource(source).kind if isinstance(source, (str, os.PathLike)) else None
    except DataPassportError:
        return None
    return (passport.source.read_options or None) if kind == passport.source.kind else None


def verify(passport: Passport | str, source: Any, **kwargs: Any) -> bool:
    """Recompute the fingerprint of ``source`` and check it matches ``passport``.

    Uses the passport's own float precision and read options, so a passport plus
    the data is enough to prove the data is the version described.
    """
    if not isinstance(passport, Passport):
        passport = Passport.load(passport)
    kwargs.setdefault("read_options", _same_kind_options(passport, source))
    fp = fingerprint(source, float_digits=passport.fingerprint.float_digits, **kwargs)
    return fp.dataset == passport.fingerprint.dataset


__all__ = [
    "CheckFailed",
    "CheckReport",
    "CheckResult",
    "CheckSpec",
    "ColumnDrift",
    "ColumnProfile",
    "ColumnSpec",
    "Comparison",
    "Contract",
    "ContractError",
    "DataPassportError",
    "Engine",
    "Fingerprint",
    "IncompatibleError",
    "MetricContext",
    "Outcome",
    "Passport",
    "PluginError",
    "RowChanges",
    "RuleContext",
    "SchemaChange",
    "Source",
    "SourceError",
    "SourceInfo",
    "__version__",
    "check",
    "compare",
    "fingerprint",
    "inspect",
    "load",
    "metric",
    "register_source",
    "rule",
    "sql",
    "verify",
]
