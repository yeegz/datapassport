# 0006 Integrations we did and didn't build

Status: accepted, 25 Nov 2026

| Integration | Decision | Why |
| --- | --- | --- |
| Polars, pandas, Arrow, DuckDB | Built in (sources) | They are how data reaches Python. Zero-copy through Arrow |
| Jupyter | Built in (`_repr_html_`) | Free with the HTML renderer |
| GitHub Actions | Composite action + `--output github` | CI is the main place a gate runs |
| OpenLineage | Facet export, no dependency | Plugs passports into Marquez, Airflow and Dagster lineage without a new standard |
| Pandera | `contract_from_pandera` | Reuse schemas teams already have. We don't re-implement Pandera's frame validation |
| Airflow, Dagster | Examples only | A task or asset check is about five lines; a provider package would be maintenance with no added value |
| dbt | Not built | dbt has its own tests. `dp.sql()` on a DuckDB/dbt target covers file-level evidence |
| Great Expectations, Soda | Not built | Different layer (SQL warehouses, large suites). Interop isn't worth the dependency weight now |
| Desktop app | Deferred | The self-contained HTML report covers viewing. Revisit once the SDK API is stable (1.0) |
