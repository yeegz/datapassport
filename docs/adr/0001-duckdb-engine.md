# 0001 DuckDB as the single compute engine

Status: accepted, 25 Nov 2026

## Context

We need CSV, JSON, JSON Lines and Parquet readers, larger-than-memory aggregation, exact and approximate quantiles, joins for keyed diffs, and a hash function that is stable across releases. Users bring Polars, pandas and Arrow frames too.

## Options

1. **Polars everywhere.** Fast, with a streaming engine. But `hash_rows` is documented as unstable across versions, quantiles over the streaming engine are limited, and keyed full outer joins on 10M+ rows need memory.
2. **DuckDB everywhere.** It reads all four formats natively, spills to disk under a `memory_limit`, has `quantile_cont` and `approx_quantile`, has version-stable `md5_number_upper/lower`, and scans Polars, pandas and Arrow zero-copy through Arrow.
3. **Both, chosen per input.** Two implementations of every statistic, and fingerprints that must match across engines. That doubles the testing surface.

## Decision

Option 2. DuckDB computes everything. Polars, pandas and Arrow are first-class *inputs*. Polars is also used for convenience outputs (`Passport.column_table()`) and in the examples. It is an optional dependency, so the core installs without it.

## Consequences

- One fingerprint implementation, cross-checked against a pure-Python reference.
- The `polars` extra pulls in `pyarrow` because Polars frames are handed to DuckDB as Arrow.
- We depend on DuckDB's text output for nested values (see the fingerprint spec's limitations). Golden tests detect any change.
