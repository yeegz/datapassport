"""Measure what sampling costs in accuracy, on the 10M-row benchmark file.

For each target sample size and seed, profile a sample and compare it with the
full-data profile. Writes benchmarks/accuracy.json.

    uv run python benchmarks/accuracy.py
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

import datapassport as dp

HERE = Path(__file__).parent
PATH = HERE / "data" / (sys.argv[1] if len(sys.argv) > 1 else "v1_10m.parquet")
NUMERIC = ["amount", "score", "qty", "user_id"]
CATEGORICAL = ["status", "country"]
HIGH_CARD = ["user_id", "email"]


def tvd(a: dp.ColumnProfile, b: dp.ColumnProfile) -> float:
    pa = dict(zip(a.categories.tokens, a.categories.counts, strict=True))
    pb = dict(zip(b.categories.tokens, b.categories.counts, strict=True))
    keys = set(pa) | set(pb)
    return 0.5 * sum(abs(pa.get(k, 0) / a.count - pb.get(k, 0) / b.count) for k in keys)


def main() -> None:
    t0 = time.perf_counter()
    full = dp.inspect(PATH, duplicates=False)
    full_s = time.perf_counter() - t0
    rows = []
    for target in (10_000, 100_000, 1_000_000):
        for seed in (0, 1, 2):
            t0 = time.perf_counter()
            s = dp.inspect(PATH, sample=target, seed=seed, duplicates=False)
            secs = time.perf_counter() - t0
            row: dict[str, object] = {"target": target, "seed": seed, "rows_profiled": s.sample.rows_profiled,
                                      "seconds": round(secs, 2)}
            for c in NUMERIC:
                f, x = full.columns[c].numeric, s.columns[c].numeric
                iqr = f.quantiles[75] - f.quantiles[25]
                row[f"{c}.mean_rel_err"] = abs(x.mean - f.mean) / abs(f.mean) if f.mean else abs(x.mean)
                row[f"{c}.p50_err_iqr"] = abs(x.quantiles[50] - f.quantiles[50]) / iqr
                row[f"{c}.p99_err_iqr"] = abs(x.quantiles[99] - f.quantiles[99]) / iqr
            row["amount.null_frac_abs_err"] = abs(s.columns["amount"].null_fraction - full.columns["amount"].null_fraction)
            for c in CATEGORICAL:
                row[f"{c}.tvd"] = tvd(full.columns[c], s.columns[c])
            for c in HIGH_CARD:
                row[f"{c}.distinct_ratio"] = s.columns[c].distinct / full.columns[c].distinct
            comp = dp.compare(full, s)
            row["drift_flags_vs_full"] = sum(d.status in {"warn", "fail"} for d in comp.drift.values())
            row["max_psi_vs_full"] = max((d.psi or 0) for d in comp.drift.values() if d.status != "skipped")
            rows.append(row)
            print(json.dumps(row), flush=True)

    summary = []
    for target in (10_000, 100_000, 1_000_000):
        sel = [r for r in rows if r["target"] == target]
        def worst(key: str, sel: list = sel) -> float:
            return max(float(r[key]) for r in sel)
        summary.append({
            "target": target,
            "rows_profiled": [r["rows_profiled"] for r in sel],
            "seconds_median": statistics.median(float(r["seconds"]) for r in sel),
            "worst_mean_rel_err": max(worst(f"{c}.mean_rel_err") for c in NUMERIC),
            "worst_p50_err_iqr": max(worst(f"{c}.p50_err_iqr") for c in NUMERIC),
            "worst_p99_err_iqr": max(worst(f"{c}.p99_err_iqr") for c in NUMERIC),
            "worst_null_frac_abs_err": worst("amount.null_frac_abs_err"),
            "worst_category_tvd": max(worst(f"{c}.tvd") for c in CATEGORICAL),
            "user_id_distinct_ratio": [round(float(r["user_id.distinct_ratio"]), 4) for r in sel],
            "email_distinct_ratio": [round(float(r["email.distinct_ratio"]), 4) for r in sel],
            "drift_flags_vs_full": [r["drift_flags_vs_full"] for r in sel],
            "max_psi_vs_full": worst("max_psi_vs_full"),
        })
    out = {"file": PATH.name, "rows": full.rows, "full_profile_seconds": round(full_s, 2), "runs": rows,
           "summary": summary}
    (HERE / "accuracy.json").write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
