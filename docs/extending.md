# Extending DataPassport

There are three extension points. All of them are part of the stable plugin API (see [compatibility.md](compatibility.md)).

## Custom rules

A rule receives a `RuleContext` and returns an `Outcome`.

```python
import datapassport as dp

@dp.rule("total_matches_items")
def total_matches_items(ctx: dp.RuleContext) -> dp.Outcome:
    tolerance = ctx.params.get("tolerance", 0.01)
    bad = ctx.count_where(f"abs(total - price * quantity) > {float(tolerance)}")
    return dp.Outcome(passed=bad == 0, observed=bad, failing_rows=bad,
                      message=f"{bad} rows where total ≠ price × quantity")
```

Use it from a contract. Extra keys become `ctx.params`:

```yaml
checks:
  - {rule: total_matches_items, tolerance: 0.05, severity: warn}
columns:
  sku:
    checks: [{rule: no_lowercase}]   # column-scoped: ctx.column / ctx.col are set
```

`RuleContext` gives you:

- `passport`, the full profile.
- `baseline`, the previous passport, or `None`.
- `params` and `column`.
- `col`, the quoted column name.
- `sql(query)`, where the dataset is written as `{data}`.
- `scalar(expr)` and `count_where(condition)`.

Rules that only look at `ctx.passport` also work when no data is available. A rule that raises is reported with status `error`, not as a crash.

On the command line, make sure the rule is imported: `datapassport check data.parquet -c contract.yml --plugin my_rules` (a module on the current path), or package it as a plugin (below).

## Custom metrics

Metrics add values to every matching column profile under `extras`:

```python
@dp.metric("share_negative", types=["integer", "float"])
def share_negative(ctx: dp.MetricContext) -> float:
    return ctx.scalar(f"avg(CASE WHEN {ctx.col} < 0 THEN 1.0 ELSE 0.0 END)")
```

`ctx.relation` is the (possibly sampled) data. Sensitive columns are skipped. The return value must be JSON-serialisable.

## Source adapters

Teach DataPassport to read a new kind of object. An adapter registers a view or table called `name` on DuckDB connection `con`:

```python
class DeltaSource:
    kind = "delta"

    def __init__(self, table, **_):
        self.table = table

    def register(self, con, name):
        con.register(name + "_arrow", self.table.to_pyarrow_dataset())
        con.execute(f'CREATE TEMP VIEW "{name}" AS SELECT * FROM "{name}_arrow"')
        return dp.SourceInfo(kind="delta", uri=self.table.table_uri)

dp.register_source("delta", lambda o: type(o).__name__ == "DeltaTable", DeltaSource)
```

## Packaging a plugin

Expose a module or a zero-argument function in the `datapassport.plugins` entry-point group. DataPassport loads entry points the first time it resolves a source, runs metrics or looks up a rule.

```toml
# your package's pyproject.toml
[project.entry-points."datapassport.plugins"]
acme = "acme_dp.rules"            # importing the module registers its @dp.rule functions
```

A complete example lives in [`examples/plugin_example`](../examples/plugin_example).

## Renderers and exporters

Passports are plain JSON with a published schema (`datapassport schema passport`), so you can write new renderers outside the package. The built-in ones in `datapassport/report/` are a good starting point.
