# 0003 Drift from summaries, not raw data

Status: accepted, 25 Nov 2026

## Context

In CI you usually have the new data and a record of the old version, not the old data itself. Keeping every old version to recompute drift is expensive, and raw data may not be allowed to sit in CI at all.

## Decision

Passports store, per numeric or temporal column, 101 quantiles (p0…p100), and per categorical column the top-k frequencies. Drift metrics are computed from these summaries:

- **PSI** over the baseline's deciles, or over categories plus an "other" bucket.
- **KS**, approximated by evaluating both piecewise-linear CDFs at every quantile point and just below it.
- **Wasserstein-1** = ∫|Q₁(p) − Q₂(p)| dp, by the trapezoid rule over the 101 points, also normalised by the baseline IQR.
- **Jensen–Shannon distance** and **total variation distance** for categories.

## Consequences

- Two passports are enough to compare versions.
- The metrics are approximations. `tests/test_drift.py` checks KS within 0.02 of the exact two-sample statistic on 10k-row normal samples, and Wasserstein within 1% for a location shift.
- Columns with fewer than 50 values are skipped by default (the `min_count` setting), because their summaries are too coarse.
- Key columns are excluded from drift: identifiers are expected to move.
