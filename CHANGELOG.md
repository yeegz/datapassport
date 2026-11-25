# Changelog

All notable changes are listed here. Versions follow [Semantic Versioning](https://semver.org); see [docs/compatibility.md](docs/compatibility.md).

## Unreleased

## 0.1.0 (not yet published)

First release.

- `inspect`: passports with an order-insensitive content fingerprint (spec `dp-fp/1`), column profiles, duplicate and key statistics, and content-addressed sampling.
- `compare`: schema evolution (added, removed, renamed exact or likely, type changes with breaking flag), keyed and multiset row diffs with per-column change counts, and drift (PSI, KS, Wasserstein-1, Jensen–Shannon, TVD) from passports alone.
- `check`: YAML, JSON or TOML contracts with column, dataset and baseline rules, custom rules, GitHub annotations and step summaries, and exit codes for CI.
- `verify`, `fingerprint`, `contract init`, `report`, `schema` commands.
- Inputs: CSV/TSV, JSON, JSON Lines, Parquet (files, globs, directories, gzip, remote URLs through DuckDB), Polars, pandas, Arrow, DuckDB queries.
- Reports: Rich terminal output, Markdown, and self-contained accessible HTML. Jupyter display.
- Integrations: OpenLineage facets, Pandera schema conversion, a GitHub composite action, Airflow and Dagster examples.
- Plugins: `@dp.rule`, `@dp.metric`, `register_source`, and the `datapassport.plugins` entry-point group.
