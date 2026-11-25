# Integrations

## GitHub Actions

Use the composite action from this repository:

```yaml
# .github/workflows/data.yml
on: [pull_request]
jobs:
  data:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: yeegz/datapassport@v0.1.0
        with:
          data: data/orders.parquet
          contract: contracts/orders.yml
          baseline: passports/orders.passport.json   # optional: committed passport of main
```

Failures show up as inline annotations, and the report is added to the job summary. Or call the CLI yourself:

```yaml
      - run: pip install datapassport
      - run: datapassport check data/orders.parquet -c contracts/orders.yml -b passports/orders.passport.json --output github
```

A useful pattern is to commit a passport next to each dataset. Pull requests then show how the data changed, and `verify` proves which version a model was trained on.

## Polars, pandas, Arrow and DuckDB

```python
dp.inspect(pl.scan_parquet("lake/*.parquet"))                    # LazyFrame, collected with the streaming engine
dp.inspect(pd.read_csv("x.csv", dtype_backend="pyarrow"))        # Arrow-backed pandas keeps dates
dp.inspect(pa_table)
dp.inspect(dp.sql("SELECT * FROM orders WHERE day = '2026-11-24'", con=duckdb_con))
```

## Jupyter

Passports and comparisons render as rich HTML when they're the last expression in a cell. See [`examples/notebooks/quickstart.ipynb`](../examples/notebooks/quickstart.ipynb).

## OpenLineage

```python
facets = dp.inspect("orders.parquet").to_openlineage()
# {"facets": {"schema": ..., "version": {"datasetVersion": <fingerprint>}},
#  "inputFacets": {"dataQualityMetrics": {...}}}
```

Attach `facets` to an input or output dataset of a `RunEvent` (`inputFacets` belongs on inputs). The fingerprint becomes the dataset version, so lineage tools can tell when the content actually changed. String min and max are never exported, and sensitive columns export counts only.

## Pandera

Reuse existing Pandera schemas as contracts: see [contracts.md](contracts.md#from-pandera).

## Airflow and Dagster

No plugin is needed. Five lines in a task:

- [`examples/airflow_dag.py`](../examples/airflow_dag.py): a task that checks a partition and pushes the passport to XCom.
- [`examples/dagster_asset_check.py`](../examples/dagster_asset_check.py): an asset check that runs a contract and attaches the fingerprint as metadata.

## dbt

dbt tests cover warehouse models. For file exports produced by dbt (or any DuckDB-backed project), point `dp.sql()` at the model, or inspect the exported file.
