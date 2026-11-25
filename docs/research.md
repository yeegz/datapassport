# Landscape research (25 Nov 2026)

Sources: official docs, GitHub repositories and issues, checked on 25 Nov 2026. Lines marked *unverified* could not be confirmed from a primary source.

## What exists

| Tool | What it does well | Where it stops | Status, Nov 2026 |
| --- | --- | --- | --- |
| Pandera | Code-defined DataFrame schemas for pandas, Polars, PySpark | Validates a frame in memory. No fingerprint, no comparison between versions, no portable report | Active (0.36.0, 10 Nov 2026) |
| Great Expectations (GX Core 1.x) | Large library of expectations | You set up six or more concepts before the first check (context, data source, asset, batch definition, suite, validation definition). Open issues report the same expectation giving different results on pandas and SQL (#12329, #12316) | Active; now stewarded by Fivetran |
| Soda Core 4 | YAML contracts over SQL sources | Install is per source. The docs don't list CSV, Parquet or pandas | Active (4.31.0) |
| DVC | Versions files by MD5 of their bytes | Knows nothing about rows or columns. Rewriting a CSV as Parquet looks like a total change | Active |
| OpenLineage | Spec for lineage facets (schema, dataQualityMetrics, datasetVersion) | A spec, not a tool. Has no fingerprint field | Active |
| datafold/data-diff | Order-insensitive segment checksums (sum of MD5 slices) between SQL databases | **Archived 17 May 2024** | Archived |
| reladiff | data-diff fork | Needs databases. Issue #63 asks for in-memory DuckDB | Slow (last push Aug 2025) |
| ydata-profiling → fg-data-profiling | Rich HTML profiles | pandas and Spark only. Polars request open since 2022 (#1129). Embeds sample rows in reports (#1432) | Renamed |
| whylogs | Mergeable profiles | Last release Dec 2024; company absorbed | Effectively unmaintained |
| Evidently | Drift reports | No native Polars or Arrow support (#1670); reports of slow metrics and memory growth (#1034, #1851) | Active |
| deepchecks | ML data checks | No release since Dec 2024 | Stale |
| frictionless-py | Data Package metadata and validation | Hash is a byte hash. Validation of large tables is slow (#307) | Active |
| DuckDB `SUMMARIZE`, Polars `describe` | Quick stats with no extra dependency | No contract, fingerprint or comparison | Active |
| lakeFS, Nessie | Branch and commit data lakes | Need a server. Content diff of Parquet still requested (lakeFS #8439) | Active |
| Croissant | ML dataset metadata | sha256 per file only; no content hash | Active |

## How others define a "content hash"

- DVC, Croissant, Frictionless: hash of file bytes. Same rows in a new file format or a new row order give a new hash.
- data-diff: per segment, sum integer slices of MD5 over each row's key and columns. Order-insensitive, but tied to each database's text casts.
- Polars `hash_rows` and DuckDB `hash()`: documented as **not stable across versions**. DuckDB's changed between 1.2.2 and 1.3.0 (duckdb#17596). Polars documented the same (pola-rs/polars#12496).
- Polars #27222: an encoding without a type tag let values of different types collide. Lesson: bind types into the hash.

## Gaps DataPassport targets

1. A published, version-stable, row-order-insensitive content fingerprint with a type-tagged canonical encoding and golden test vectors.
2. File-to-file comparison (schema evolution, row changes by key, drift) with no database or server.
3. A single small JSON file ("passport") that travels with a dataset and is enough to compare against later, without the old data.
4. Privacy by default: no raw rows, no string min/max, category values stored as hashes unless the user opts in.
5. Polars, pandas and Arrow frames and out-of-core files through one engine.
6. Interop instead of a new standard: OpenLineage facets out; Pandera schemas in.
7. A CI gate with documented exit codes and a GitHub step summary.

## Not verified

- Whether DVC normalises line endings.
- Raw-value leakage in GX `unexpected_list` and Soda failed-row samples beyond issue titles.
- Competitor performance numbers. We publish only our own measurements.
