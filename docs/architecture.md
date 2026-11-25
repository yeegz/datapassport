# Architecture

```
            ┌──────────── sources.py ────────────┐
 path/glob ─┤ FileSource   (csv, tsv, json, jsonl, parquet, .gz)
 Polars ────┤ FrameSource  (Polars, pandas, Arrow, Arrow C stream)   ──► DuckDB relation
 dp.sql() ──┤ QuerySource  (SQL on your own connection)              (temp view / table)
 custom ────┤ register_source(...)
            └────────────────────────────────────┘
                                │
                     engine.py  ▼
        ┌──────────────────────────────────────────────┐
        │ compute_fingerprint  one pass, all rows       │
        │ _sample              content-addressed sample │
        │ profile_columns      one wide aggregate scan  │
        │                      + quantiles + top-k      │
        │ run_metrics          custom metrics (plugins) │
        └──────────────────────────────────────────────┘
                                │
                    models.py   ▼   Passport (Pydantic, JSON Schema)
                                │
       ┌────────────────┬───────┴────────┬──────────────────┐
  compare.py        rules.py          report/           integrations/
  schema diff,      contract checks,  terminal (Rich),  openlineage,
  keyed/multiset    custom rules,     markdown, html    pandera
  row diff, drift   CI report
  (drift.py)        (contract.py)
                                │
                          cli.py (Typer)
```

## Principles

1. **One engine, one semantics.** Every input becomes a DuckDB relation, and every statistic and fingerprint comes from the same SQL. A CSV and its Parquet copy can't disagree because two code paths counted nulls differently. DuckDB also spills to disk, so files larger than memory work.
2. **The passport is the product.** A passport is a small, versioned, schema-validated JSON document. Comparisons can run from two passports alone, so CI doesn't need yesterday's data.
3. **Privacy by default.** Passports hold aggregates. They never hold rows or string min/max, and category values are stored as tokens unless you opt in.
4. **Honest numbers.** Every approximation is labelled in the output: `distinct_exact`, `options.quantiles`, `sample.method`, `RowChanges.note`.
5. **Small core, open edges.** The core needs only DuckDB, Pydantic, Typer, Rich and PyYAML. Polars, pandas, Arrow and Pandera are optional. Rules, metrics and sources are plugin points.

## Module responsibilities

| Module | Responsibility | Depends on |
| --- | --- | --- |
| `_types.py` | Logical type mapping, SQL quoting | – |
| `fingerprint.py` | Spec `dp-fp/1`: SQL builder and Python reference | `_types` |
| `sources.py` | Adapters and their registry | `models` |
| `engine.py` | DuckDB connection, fingerprint pass, sampling, profiling, `inspect()` | the above |
| `models.py` | Passport format (Pydantic) | – |
| `drift.py` | PSI, KS, Wasserstein-1, Jensen-Shannon, TVD from summaries | `models` |
| `compare.py` | Schema evolution, row diff, drift → `Comparison` | `engine`, `drift` |
| `contract.py` | Contract format, load/save, `Contract.infer` | – |
| `rules.py` | Contract evaluation → `CheckReport` | `engine`, `compare`, `plugins` |
| `plugins.py` | Custom rules, custom metrics, entry-point discovery | – |
| `report/` | Terminal, Markdown and HTML renderers | models |
| `integrations/` | OpenLineage facets, Pandera conversion | models, contract |
| `cli.py` | Typer CLI, exit codes | everything |

## Data flow of `inspect()`

1. `resolve()` picks an adapter. `load()` registers a temp view (Parquet, frames) or a temp table (CSV and JSON are parsed once), then reads column types.
2. **Fingerprint pass** (one scan): encode each field once, build the row encoding, and aggregate `count`, `Σ md5_upper`, `Σ md5_lower`, `count(DISTINCT md5)` (duplicates), and per-column sums.
3. **Sample** (optional): keep rows whose seeded MD5 falls under a threshold, into a temp table.
4. **Profile pass**: one wide aggregate query over every column, then one quantile query per numeric or temporal column, then one top-k query per categorical column.
5. Custom metrics run per column. The result is assembled into a `Passport`.

The cost of a full `inspect` is roughly two to three scans plus one quantile sort per numeric column. Measured numbers are in [benchmarks.md](benchmarks.md).

## Decisions

Recorded as ADRs in [docs/adr](adr/):

- [0001 DuckDB as the single compute engine](adr/0001-duckdb-engine.md)
- [0002 Defining our own fingerprint](adr/0002-own-fingerprint.md)
- [0003 Drift from summaries, not raw data](adr/0003-drift-from-summaries.md)
- [0004 Privacy by default](adr/0004-privacy-by-default.md)
- [0005 Content-addressed sampling](adr/0005-content-addressed-sampling.md)
- [0006 Integrations we did and didn't build](adr/0006-integrations-scope.md)
