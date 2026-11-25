# Sampling and accuracy

`inspect(..., sample=N)` (CLI `--sample N`) profiles a sample. Read the trade-offs below before relying on it.

## What is sampled and what isn't

| Always on every row | On the sample when `sample=` is set |
| --- | --- |
| Fingerprint (dataset and per-column) | Null counts and fractions |
| Row count | Distinct counts |
| Duplicate rows, duplicate and null keys | Min, max, mean, std, quantiles |
| Contract rules (`check` counts violations on all rows) | Text lengths, empty and blank counts |
| Keyed and multiset diffs | Category frequencies, custom metrics |

## How rows are chosen

A row is kept when DuckDB's `hash(seed, columns…) mod 10^6` is below a threshold set from the target size (see [ADR 0005](adr/0005-content-addressed-sampling.md)). The same data gives the same sample on every run and in any row or column order (for a given DuckDB version), and unchanged rows are sampled identically across versions. The realised size varies around the target, binomially.

## Measured accuracy

<!-- accuracy-meta -->
File `v1_10m.parquet`, 10,000,000 rows. Full profile took 98.15 s.
<!-- /accuracy-meta -->

Each sample size was run with seeds 0, 1 and 2. "Worst" is the largest error over those runs and over the numeric columns `amount`, `score`, `qty` and `user_id`. Relative mean error is unstable near zero. The centered normal `score` column drives the large relative percentages below. Quantile errors are expressed as a fraction of the full-data interquartile range (IQR). "Drift flags vs full" counts columns that drift detection would flag (warn or fail) when comparing the sample's profile with the full profile: ideally 0.

<!-- accuracy -->
| Target sample | Rows profiled (3 seeds) | Time | Worst mean error | Worst p50 error | Worst p99 error | Worst null-rate error | Worst category TVD | Distinct ratio user_id / email | Drift flags vs full |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| 10,000 | 9,898, 9,893, 10,039 | 60.4 s | 8302.445% | 0.018 IQR | 0.420 IQR | 0.0020 | 0.0141 | 0.010 / 0.002 | 0 (max PSI 0.0168) |
| 100,000 | 100,322, 99,971, 100,298 | 38.3 s | 2585.488% | 0.006 IQR | 0.150 IQR | 0.0007 | 0.0048 | 0.097 / 0.015 | 0 (max PSI 0.0147) |
| 1,000,000 | 1,000,287, 1,000,121, 999,261 | 17.4 s | 347.964% | 0.001 IQR | 0.044 IQR | 0.0002 | 0.0017 | 0.624 / 0.149 | 0 (max PSI 0.0147) |
<!-- /accuracy -->

Source: `benchmarks/accuracy.py`, raw results in `benchmarks/accuracy.json`.

## Rules of thumb

- **Means, null rates, quantiles and category shares** converge quickly. Their standard error shrinks like 1/√n, independent of the full size.
- **Min, max and extreme quantiles** (p0, p1, p99, p100) are the least reliable. A sample usually misses the true extremes. Use the contract rules (`min`/`max`), which always check every row.
- **Distinct counts don't scale up.** A sample's distinct count isn't an estimate of the full count for high-cardinality columns (see the ratios above). Profile without sampling when you need it.
- **Rare categories** (below about 1/n of rows) can vanish from a sample.
- **Drift on sampled profiles** carries sampling noise. Use the same sample size on both sides, and a larger one for columns where small shifts matter.
