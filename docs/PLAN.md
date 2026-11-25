# Implementation plan

Living plan. Status as of 25 Nov 2026.

## Goal

A small, well-tested SDK and CLI that gives every dataset version portable evidence: a stable content fingerprint, a privacy-safe profile, a comparison with earlier versions, and a CI gate. Depth over breadth.

## Milestones

| # | Milestone | Status |
| --- | --- | --- |
| 1 | Landscape research and positioning ([research.md](research.md)) | Done |
| 2 | Fingerprint spec `dp-fp/1`, SQL implementation, Python reference, golden vectors, property tests | Done |
| 3 | Sources: CSV/TSV/JSON/JSONL/Parquet (files, globs, dirs, gzip, URLs), Polars, pandas, Arrow, DuckDB SQL, adapter registry | Done |
| 4 | Profile: nulls, distinct, numeric with 101 quantiles, text, temporal, boolean, categories, duplicates, keys, content-addressed sampling | Done |
| 5 | Compare: schema evolution (incl. exact and likely renames), keyed and multiset row diff, drift from passports | Done |
| 6 | Contracts: YAML/JSON/TOML, column, dataset and baseline rules, custom rules, `Contract.infer` | Done |
| 7 | Reports: Rich terminal, Markdown, self-contained HTML, Jupyter, JSON Schemas | Done |
| 8 | CLI with documented exit codes; GitHub composite action | Done |
| 9 | Integrations: OpenLineage facets, Pandera conversion, Airflow/Dagster examples | Done |
| 10 | Tests: unit, integration, property, malformed and large-file | Done |
| 11 | Benchmarks and sampling-accuracy study with measured numbers | Done |
| 12 | Docs, contributor guide, CI matrix, release workflow | Done (CI not yet run on GitHub) |

## Next (toward 0.2 and adoption)

1. Push to GitHub, let the CI matrix run (Windows paths and lowest dependencies are only exercised there), and fix what it finds.
2. Publish 0.1.0 to TestPyPI, then PyPI (trusted publishing is already configured in `release.yml`).
3. Faster profiling for wide tables: batch per-column quantile and top-k queries.
4. `datapassport diff --values` for opt-in value-level change samples, with redaction.
5. Partitioned passports: one passport per partition, merged into a dataset view. The row sums in the spec add across partitions, so storing the two lane sums in passports would make merged fingerprints exact without re-reading data.
6. Signed passports (Sigstore) for tamper evidence.
7. Gather feedback from 3–5 real pipelines before freezing the 1.0 Python API.
