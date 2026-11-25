"""Distribution drift computed from two passports.

Drift is computed from the stored summaries (101 quantiles for numeric and
temporal columns, top-k frequencies for categorical columns), so two passports
are enough: you do not need the old data.

Accuracy: quantile summaries have 1 percentile resolution. KS and PSI computed
from them are approximations of the exact statistics; tests/test_drift.py checks
them against exact values on synthetic data (KS within 0.02 on samples of 10k).
"""

from __future__ import annotations

import bisect
import math
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, Field

from .models import ColumnProfile

EPS = 1e-4
Status = Literal["pass", "warn", "fail", "skipped"]


class ColumnDrift(BaseModel):
    column: str
    kind: Literal["numeric", "categorical", "temporal", "none"]
    psi: float | None = Field(None, description="Population Stability Index (reference deciles or categories).")
    ks: float | None = Field(None, description="Approximate Kolmogorov-Smirnov statistic (numeric/temporal).")
    wasserstein: float | None = Field(None, description="Wasserstein-1 distance in the column's own units.")
    wasserstein_norm: float | None = Field(None, description="Wasserstein-1 divided by the reference IQR (or std).")
    js: float | None = Field(None, description="Jensen-Shannon distance, base 2, 0..1 (categorical).")
    tvd: float | None = Field(None, description="Total variation distance, 0..1 (categorical).")
    null_fraction_delta: float = 0.0
    mean_delta: float | None = None
    status: Status = "pass"
    metric: str | None = Field(None, description="Metric the status was judged on.")
    note: str | None = None


def cdf(qs: Sequence[float], x: float) -> float:
    """Right-continuous CDF from 101 quantiles at p = 0, .01, ..., 1."""
    n = len(qs)
    if x < qs[0]:
        return 0.0
    if x >= qs[-1]:
        return 1.0
    i = bisect.bisect_right(qs, x) - 1  # largest i with qs[i] <= x
    p_i = i / (n - 1)
    if qs[i + 1] > qs[i]:
        frac = (x - qs[i]) / (qs[i + 1] - qs[i])
        return p_i + frac / (n - 1)
    return p_i


def psi_from_props(a: Sequence[float], b: Sequence[float]) -> float:
    total = 0.0
    for pa, pb in zip(a, b, strict=True):
        pa = max(pa, EPS)
        pb = max(pb, EPS)
        total += (pb - pa) * math.log(pb / pa)
    return total


def numeric_drift(ref: Sequence[float], cur: Sequence[float]) -> dict[str, float]:
    """PSI, KS and Wasserstein-1 from two 101-point quantile arrays."""
    # PSI over reference deciles (deduplicated edges handle discrete data).
    edges = sorted(set(ref[10:100:10]))

    def props(qs: Sequence[float]) -> list[float]:
        cuts = [0.0] + [cdf(qs, e) for e in edges] + [1.0]
        return [max(0.0, cuts[i + 1] - cuts[i]) for i in range(len(cuts) - 1)]

    psi = psi_from_props(props(ref), props(cur))
    # KS: evaluate both CDFs at every quantile point of either distribution,
    # and just below each point to catch jumps.
    points = sorted(set(ref) | set(cur))
    ks = 0.0
    for x in points:
        below = math.nextafter(x, -math.inf)
        ks = max(ks, abs(cdf(ref, x) - cdf(cur, x)), abs(cdf(ref, below) - cdf(cur, below)))
    # Wasserstein-1 = integral over p of |Q_ref(p) - Q_cur(p)|, trapezoid rule.
    diffs = [abs(a - b) for a, b in zip(ref, cur, strict=True)]
    w1 = sum((diffs[i] + diffs[i + 1]) / 2 for i in range(len(diffs) - 1)) / (len(diffs) - 1)
    iqr = ref[75] - ref[25]
    spread = iqr if iqr > 0 else (ref[-1] - ref[0])
    return {
        "psi": psi,
        "ks": min(ks, 1.0),
        "wasserstein": w1,
        "wasserstein_norm": (w1 / spread) if spread > 0 else (0.0 if w1 == 0 else math.inf),
    }


def categorical_drift(ref: ColumnProfile, cur: ColumnProfile) -> dict[str, float] | None:
    if ref.categories is None or cur.categories is None:
        return None
    ra = dict(zip(ref.categories.tokens, ref.categories.counts, strict=True))
    ca = dict(zip(cur.categories.tokens, cur.categories.counts, strict=True))
    keys = sorted(set(ra) | set(ca))
    rt = max(ref.count, 1)
    ct = max(cur.count, 1)
    # Tokens outside one side's top-k are folded into "other" on that side.
    rp = [ra.get(k, 0) / rt for k in keys]
    cp = [ca.get(k, 0) / ct for k in keys]
    rp.append(max(0.0, 1 - sum(rp)))
    cp.append(max(0.0, 1 - sum(cp)))
    psi = psi_from_props(rp, cp)
    tvd = 0.5 * sum(abs(a - b) for a, b in zip(rp, cp, strict=True))
    m = [(a + b) / 2 for a, b in zip(rp, cp, strict=True)]

    def kl(p: list[float], q: list[float]) -> float:
        return sum(pi * math.log2(pi / qi) for pi, qi in zip(p, q, strict=True) if pi > 0)

    js = math.sqrt(max(0.0, 0.5 * kl(rp, m) + 0.5 * kl(cp, m)))
    return {"psi": psi, "tvd": tvd, "js": min(js, 1.0)}


DEFAULT_THRESHOLDS: dict[str, tuple[float, float]] = {
    # metric: (warn, fail). PSI 0.1 / 0.25 is the common credit-risk convention.
    "psi": (0.1, 0.25),
    "ks": (0.1, 0.2),
    "wasserstein_norm": (0.1, 0.25),
    "js": (0.1, 0.2),
    "tvd": (0.1, 0.2),
}


MIN_COUNT = 50


def column_drift(
    ref: ColumnProfile,
    cur: ColumnProfile,
    *,
    metric: str | None = None,
    warn: float | None = None,
    fail: float | None = None,
    min_count: int = MIN_COUNT,
) -> ColumnDrift:
    """Drift for one column. Columns with fewer than ``min_count`` non-null
    values on either side are skipped: their summaries are too coarse to judge."""
    out = ColumnDrift(column=cur.name, kind="none", null_fraction_delta=cur.null_fraction - ref.null_fraction)
    if min(ref.count, cur.count) < min_count:
        out.status = "skipped"
        out.note = f"fewer than {min_count} values on one side"
        return out
    if ref.sensitive or cur.sensitive:
        out.status = "skipped"
        out.note = "sensitive column: distributions were not recorded"
        return out
    if ref.numeric and cur.numeric and ref.numeric.quantiles and cur.numeric.quantiles:
        out.kind = "numeric"
        for k, v in numeric_drift(ref.numeric.quantiles, cur.numeric.quantiles).items():
            setattr(out, k, v)
        if ref.numeric.mean is not None and cur.numeric.mean is not None:
            out.mean_delta = cur.numeric.mean - ref.numeric.mean
    elif ref.temporal and cur.temporal and ref.temporal.quantiles and cur.temporal.quantiles:
        out.kind = "temporal"
        for k, v in numeric_drift(ref.temporal.quantiles, cur.temporal.quantiles).items():
            setattr(out, k, v)
    if ref.categories and cur.categories:
        cat = categorical_drift(ref, cur)
        if cat:
            if out.kind == "none":
                out.kind = "categorical"
                out.psi = cat["psi"]
            out.js = cat["js"]
            out.tvd = cat["tvd"]
    if out.kind == "none":
        out.status = "skipped"
        out.note = "no distribution summary for this type"
        return out
    chosen = metric or ("psi" if out.kind in {"numeric", "categorical", "temporal"} else None)
    value = getattr(out, chosen) if chosen else None
    if value is None:
        out.status = "skipped"
        out.note = f"metric {chosen} not available for {out.kind} columns"
        return out
    dw, df = DEFAULT_THRESHOLDS.get(chosen or "", (math.inf, math.inf))
    w = dw if warn is None else warn
    f = df if fail is None else fail
    out.metric = chosen
    out.status = "fail" if value >= f else "warn" if value >= w else "pass"
    return out
