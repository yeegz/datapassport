# Benchmarks

The tables are rendered from [the measurements](../benchmarks/results.json) by `benchmarks/render.py`. Re-run on your machine:

```bash
uv run python benchmarks/generate.py 1000000 10000000   # ~1.4 GB of data in benchmarks/data (git-ignored)
uv run python benchmarks/run.py 1m 10m
uv run python benchmarks/render.py
```

## Method

- **Machine:** <!-- machine -->
Apple M1 Pro, 8 cores, 16 GB RAM, macOS-27.0.1-arm64-arm-64bit; Python 3.12.16, datapassport 0.1.0, DuckDB 2.0.1, Polars 2.2.0, pandas 3.1.1; 1-minute load average when the run started: 91.11
<!-- /machine -->
- **Data:** synthetic and deterministic (seed 42). Ten columns: two 64-bit integer ids, a log-normal float with 2% nulls, a float32, an int32, two low-cardinality strings, a high-cardinality email-like string, a timestamp and a boolean. Sizes: 1M rows (28 MB Parquet / 106 MB CSV) and 10M rows (282 MB Parquet / 1.1 GB CSV). Version 2 changes 1% of amounts, removes 0.5% of rows and adds 0.5%.
- **Measurement:** each task runs in a fresh Python process. *Time* is the median wall time of the work itself (imports excluded) over 3 runs at 1M rows and 2 runs at 10M. *Peak RSS* is the process's maximum resident memory, including imported libraries.
- **Machine load:** this run used the same machine as other builds, with the quiet-machine wait bypassed and load logged in the raw results. Times are observations from a shared system. Use a quiet, dedicated run for tighter comparisons.
- **Fairness:** baselines do less than DataPassport. That is the point of including them: they show the cost of each extra guarantee. Files are warm in the OS page cache.

## Identity: "is this the same data?"

<!-- identity -->
| Task | 1M rows: time · peak RSS | 10M rows: time · peak RSS |
| --- | ---: | ---: |
| sha256 of file bytes | 0.12 s · 24 MB | 0.18 s · 24 MB |
| polars hash_rows().sum() | 0.50 s · 235 MB | 0.83 s · 1,324 MB |
| datapassport fingerprint | 8.63 s · 187 MB | 13.03 s · 324 MB |
<!-- /identity -->

- `sha256 of file bytes` is the fastest, but it's byte identity: a re-encoded or reordered file gets a new hash.
- `polars hash_rows().sum()` is order-insensitive and fast, but Polars documents it as unstable across versions, and it ignores types and column order.
- `datapassport fingerprint` is the version-stable, type-aware, format-independent content fingerprint, plus per-column fingerprints.

## Profiling

<!-- profile -->
| Task | 1M rows: time · peak RSS | 10M rows: time · peak RSS |
| --- | ---: | ---: |
| duckdb SUMMARIZE | 4.50 s · 151 MB | 6.87 s · 324 MB |
| polars describe() | 0.22 s · 251 MB | 1.45 s · 1,360 MB |
| pandas describe(include='all') | 1.43 s · 419 MB | 15.76 s · 1,706 MB |
| datapassport inspect | 5.36 s · 710 MB | 23.62 s · 867 MB |
| datapassport inspect, sample=100k | 1.94 s · 446 MB | 9.57 s · 696 MB |
<!-- /profile -->

DuckDB `SUMMARIZE` and Polars `describe()` compute a lighter summary: no fingerprint, no duplicate-row count, no key check, 3 quantiles instead of 101, no categories. DataPassport's extra time goes into the fingerprint pass, exact distinct counts and quantiles (exact up to 1M profiled rows), and per-column top-k queries. With `sample=100_000` the profile is computed on a deterministic content-addressed sample, while fingerprint, duplicates and key checks still cover every row.

## Comparing two versions by key

<!-- diff -->
| Task | 1M rows: time · peak RSS | 10M rows: time · peak RSS |
| --- | ---: | ---: |
| polars keyed diff (join) | 0.42 s · 754 MB | 4.81 s · 2,924 MB |
| datapassport compare --key id | 10.59 s · 819 MB | 71.87 s · 2,445 MB |
<!-- /diff -->

The Polars baseline is a full outer join that counts added, removed and changed rows. DataPassport computes the same three counts (both report identical numbers) plus changes per column, schema changes and drift. That needs two full passports, which is most of its time. To compare against a *stored* passport, only the new data is profiled.

## CSV and memory limits

<!-- csv -->
| Task | 1M rows: time · peak RSS | 10M rows: time · peak RSS |
| --- | ---: | ---: |
| polars read_csv + describe() | 0.23 s · 268 MB | 14.97 s · 875 MB |
| datapassport inspect (CSV) | 3.72 s · 841 MB | 77.85 s · 674 MB |
| datapassport inspect (CSV), memory_limit=1GB | 4.10 s · 811 MB | 58.17 s · 865 MB |
<!-- /csv -->

The generator writes the `score` column as Float32 in Parquet. CSV has no embedded type, and re-parsing its decimal text can change the exact floating-point values. Compare inputs with the same precision or set a shared `--float-digits` policy if the application tolerates rounding. CSV is parsed once into a DuckDB table, which accounts for most of the difference from Parquet. With `memory_limit=1GB`, DuckDB spills to disk instead of holding everything in memory. Note that peak RSS can exceed the limit somewhat: the limit covers DuckDB's buffer manager, not Python or the libraries themselves.

## What these numbers don't show

- Cold-cache I/O, network storage, or data larger than the 10M × 10 tested here.
- Wide tables. Profiling cost grows roughly linearly with columns: one quantile query per numeric or temporal column and one top-k query per categorical column.
- Other machines. Rerun the scripts; they take a few minutes.
