# Python API

Everything public is importable from `datapassport` (conventionally `import datapassport as dp`). Return types are Pydantic models: they validate, serialise to JSON (`.to_json()`) and publish a JSON Schema (`.model_json_schema()`).

## Sources

Any function taking `source` accepts:

| Input | Example |
| --- | --- |
| File path, glob or directory | `"orders.csv"`, `"lake/orders/*.parquet"`, `Path("lake/orders")` |
| Polars `DataFrame` or `LazyFrame` | `pl.scan_parquet(...)` (collected with the streaming engine) |
| pandas `DataFrame` | NumPy- or Arrow-backed |
| Arrow `Table`, `RecordBatchReader`, any `__arrow_c_stream__` object | `pa.table(...)` |
| A DuckDB query | `dp.sql("SELECT * FROM t WHERE day = '2026-11-01'", con=my_con)` |
| Anything with a registered adapter | see [extending.md](extending.md) |

Common keyword arguments: `format=` (`"csv"`, `"json"`, `"jsonl"`, `"parquet"`), `read_options=` (passed to DuckDB's reader, e.g. `{"delim": ";"}`), and `engine=dp.Engine(threads=4, memory_limit="2GB", temp_directory="/scratch")`.

## `dp.inspect(source, **options) -> Passport`

| Option | Default | Meaning |
| --- | --- | --- |
| `name` | file stem | Dataset name in reports |
| `key` | `None` | Key column or list; duplicate and null keys are counted |
| `sample` | `None` | Profile a sample: int = target rows, float = fraction. The fingerprint always covers all rows |
| `seed` | `0` | Sampling seed |
| `privacy` | `"safe"` | `"values"` stores top category values in clear text |
| `sensitive` | `()` | Columns whose distributions are withheld |
| `top_k` | `20` | Category frequencies kept per column |
| `float_digits` | `17` | Significant digits for float fingerprints (17 = exact) |
| `quantiles` | `"auto"` | `"exact"` up to 1M profiled rows (deterministic), else `"approx"` (t-digest: fast, may differ in the last digits between runs) |
| `duplicates` | `True` | Count exact duplicate rows (costs a distinct hash aggregate) |
| `metrics` | `True` | Run registered custom metrics |

`Passport` fields: `rows`, `schema` (`schema_` in Python), `fingerprint` (`dataset`, `schema`, `columns`, `rows`, `spec`), `duplicates`, `columns` (name → `ColumnProfile`), `source`, `options`, `sample`, `producer`, `created_at`.

Methods: `to_json(path=None)`, `to_html(path=None)`, `to_markdown()`, `to_openlineage()`, `column_table()` (Polars), `Passport.load(path)`, and `_repr_html_` for notebooks.

## `dp.fingerprint(source, *, float_digits=17) -> Fingerprint`

One pass, no profile. `fp.dataset` is the order-insensitive content hash. `fp.columns` holds per-column hashes.

## `dp.compare(base, target, **options) -> Comparison`

Each side can be data or a passport (object or `.json` path).

| Option | Meaning |
| --- | --- |
| `key` | Match rows by key; counts added, removed, changed and unchanged rows, plus changes per column |
| `drift` | `{"default": {"metric": "psi", "warn": 0.1, "fail": 0.25}, "amount": {"metric": "ks", "fail": 0.1}}` |
| `examples` | Include up to N example **keys** per kind of change |
| `sample`, `privacy`, `sensitive`, `float_digits` | As for `inspect` |

| Inputs | Row comparison |
| --- | --- |
| Data + data + `key` | `method="key"`: added, removed, changed, unchanged, `changed_by_column`. Falls back to multiset if the key isn't unique |
| Data + data | `method="multiset"`: an edited row counts as one removed and one added |
| Any passport | `method="summary"`: row counts, per-column fingerprints, drift |

`Comparison` fields: `identical`, `schema_changes` (`added`, `removed`, `renamed` with `confidence` exact or likely, `type_changed` with `breaking`, `moved`), `changed_columns`, `rows`, `drift` (column → `ColumnDrift` with `psi`, `ks`, `wasserstein`, `wasserstein_norm`, `js`, `tvd`, `null_fraction_delta`, `status`), `notes`. Helpers: `summary()`, `breaking_changes`, `drifted`, `to_json/html/markdown()`.

## `dp.check(source, contract, *, baseline=None, sample=None) -> CheckReport`

`contract` is a path, a dict or a `dp.Contract`. `baseline` is a passport or passport path.

`CheckReport`: `status` (`pass`/`warn`/`fail`), `ok`, `results` (`CheckResult`: `rule`, `column`, `status`, `severity`, `observed`, `expected`, `failing_rows`, `message`), `failures`, `warnings`, `passport`, `exit_code(strict=False)`, `raise_for_status(strict=False)` (raises `dp.CheckFailed`), `to_json()`, `to_markdown()`, `github_annotations()`.

## `dp.Contract`

`Contract.load(path)`, `Contract.from_dict(d)`, `Contract.infer(passport_or_source, strict=False)`, `to_yaml(path=None)`, `to_dict()`. See [contracts.md](contracts.md).

## `dp.verify(passport, source) -> bool`

Recomputes the fingerprint with the passport's settings and returns whether the content matches.

## Errors

All deliberate errors derive from `dp.DataPassportError` and carry `.message` and `.hint`:

| Error | When |
| --- | --- |
| `SourceError` | file missing (with a "did you mean"), unknown format, unreadable data, ragged CSV, unknown object type |
| `ContractError` | unparseable or invalid contract (every bad field listed), unknown rule, invalid regex |
| `IncompatibleError` | comparing passports with different fingerprint specs or `float_digits` |
| `PluginError` | a custom metric failed, or a plugin failed to load |
| `CheckFailed` | raised by `CheckReport.raise_for_status()` |

## Extension API

`dp.rule`, `dp.metric`, `dp.RuleContext`, `dp.MetricContext`, `dp.Outcome`, `dp.register_source`, `dp.Source`, `dp.SourceInfo`. See [extending.md](extending.md).
