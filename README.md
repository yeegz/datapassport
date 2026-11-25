# DataPassport

**Know exactly which data you have, and what changed.**

DataPassport gives every version of a dataset a small JSON *passport*: a content fingerprint that ignores row order and file format, a column profile, and enough summary to compare against later versions without keeping the old data. Use it from Python or the command line, in notebooks, pipelines and CI.

```python
import datapassport as dp

passport = dp.inspect("orders.parquet", key="order_id")
passport.to_json("orders.passport.json")                 # commit this next to your data

diff = dp.compare("orders.passport.json", "orders_new.parquet")
print(diff.summary())        # rows 5,000 → 5,200; 2 schema change(s); drift in amount

dp.check("orders_new.parquet", "contract.yml", baseline="orders.passport.json").raise_for_status()
```

## Why

Data changes quietly. A file is rewritten as Parquet, a column is renamed, a vendor adds a status value, a join duplicates rows, prices drift. The tools you already have answer different questions:

- **DVC, Croissant and file checksums** hash *bytes*. The same rows in another format or order look like a total change.
- **Pandera, Great Expectations and Soda** validate *one* version. They don't tell you how it differs from the last one, and they need setup.
- **datafold's data-diff**, the go-to open-source table differ, was archived in May 2024. Its successors need a database.
- **Engine row hashes** (Polars `hash_rows`, DuckDB `hash`) are documented as unstable across versions, so they can't serve as long-lived identity.

DataPassport fills the gap between them. It adds a documented, version-stable content fingerprint, file-to-file comparison without a server, privacy-safe summaries you can attach to a pull request, and a CI gate with documented exit codes. The research behind these choices is in [docs/research.md](docs/research.md).

## What you can do

- **Fingerprint content, not bytes.** The same values and logical types get the same fingerprint across CSV, Parquet, JSON Lines, Polars, pandas and Arrow, regardless of row or column order. The specification is tested against a pure-Python reference: [docs/fingerprint-spec.md](docs/fingerprint-spec.md).
- **Profile columns.** Nulls, distinct counts, numeric stats with 101 quantiles, text lengths, blank values, categories, dates, duplicate rows and duplicate keys.
- **Compare versions.** Rows added, removed and changed by key (and which columns changed); schema evolution including likely renames; and drift (PSI, KS, Wasserstein, Jensen–Shannon), all from two passports if that's all you have.
- **Validate with contracts.** YAML rules for types, nulls, uniqueness, ranges, allowed values, patterns, row counts, schema compatibility and drift thresholds. Draft one from your data with `datapassport contract init`.
- **Run it in CI.** Exit codes, GitHub annotations and a job summary. There's a composite GitHub Action.
- **Prove which version you used.** `datapassport verify passport.json data.parquet` checks that data is exactly the recorded version.
- **Share reports safely.** Self-contained HTML (light and dark, keyboard and screen-reader friendly), Markdown and JSON. No rows, no raw category values, and no string min or max unless you opt in.
- **Extend it.** Custom rules, metrics and source adapters, as decorators or installable plugins.

## Install

DataPassport 0.1.0 is a local prerelease. In a source checkout with Python 3.11 or later:

```bash
python -m pip install .
datapassport --help
```

Use `python -m pip install '.[polars]'` or `python -m pip install '.[pandas]'` for the corresponding frame integrations.

More options and fixes for common problems: [docs/installation.md](docs/installation.md).

## Command line

```console
$ datapassport inspect orders_v1.csv -k order_id -o orders_v1.passport.json --html report.html
orders_v1  5,000 rows × 7 columns  fingerprint 7f0030f298ff  key order_id: 0 dup / 0 null

column          type        nulls  distinct   min    max     mean  shape
order_id        integer      0.0%     5,000     1  5,000    2,500  ████████████
amount          float        0.0%     3,206  2.45  259.9     28.9  █▆▂
status          string       0.0%         4     –      –        –  len 3–9
...

$ datapassport compare orders_v1.csv orders_v2.parquet -k order_id
CHANGED   7f0030f298ff → b21f583e65c0
rows 5,000 → 5,200   +300 added  −100 removed  ~100 changed  (key: order_id)
changed values: amount 100

Schema
  BREAKING  renamed country → country_code (likely: similar values)

$ datapassport check orders_v2.parquet -c contract.yml -b orders_v1.passport.json --output github
```

| Command | Purpose |
| --- | --- |
| `inspect` | Profile and fingerprint; write passport, HTML or JSON |
| `fingerprint` | Content fingerprint only (one pass) |
| `compare` | Two versions (data or passports); `--fail-on change\|schema\|breaking\|drift` |
| `check` | Contract validation; exit 1 on failure |
| `verify` | Is this data the version in the passport? |
| `contract init` | Draft a contract from data |
| `report` | Render a saved passport or comparison as HTML |
| `schema` | JSON Schema of each file format |

Exit codes: `0` ok, `1` check failed or condition met, `2` bad input (with a hint), `3` internal error. See [docs/cli.md](docs/cli.md).

## Python

```python
import datapassport as dp
import polars as pl

# Anything: paths, globs, directories, Polars (eager or lazy), pandas, Arrow, DuckDB queries.
p = dp.inspect(pl.scan_parquet("lake/orders/*.parquet"), key="order_id", sample=1_000_000)
p.columns["amount"].numeric.quantiles[50]       # median
p.duplicates.key                                # KeyStats(duplicates=0, nulls=0)
p.column_table()                                # profile as a Polars DataFrame

c = dp.compare("v1.parquet", "v2.parquet", key="order_id", examples=5)
c.rows.changed_by_column                        # {'amount': 100}
[s.describe() for s in c.breaking_changes]      # ['renamed country → country_code (likely: similar values)']
c.drift["amount"].psi, c.drift["amount"].status

report = dp.check(df, "contract.yml", baseline="v1.passport.json")
report.ok, [r.label for r in report.failures]
```

Custom rule:

```python
@dp.rule("total_matches_items")
def total_matches_items(ctx: dp.RuleContext) -> dp.Outcome:
    bad = ctx.count_where("abs(total - price * quantity) > 0.01")
    return dp.Outcome(passed=bad == 0, observed=bad, message=f"{bad} rows don't add up")
```

Full reference: [docs/api.md](docs/api.md) · contracts: [docs/contracts.md](docs/contracts.md) · plugins: [docs/extending.md](docs/extending.md).

## In CI

To try the composite action in a checkout of this repository, use a local action reference. Run `python examples/make_data.py` with Polars and NumPy installed to generate the source fixture.

```yaml
- uses: actions/checkout@v4
- uses: ./
  with:
    data: examples/data/orders_v1.parquet
    contract: examples/contract.yml
```

Failures appear inline in the pull request, and the report lands in the job summary. Airflow, Dagster, OpenLineage, Pandera and Jupyter: [docs/integrations.md](docs/integrations.md).

## Performance

See the measured results below for cold-process fingerprinting, profiling and keyed comparison on synthetic data. Each baseline performs a different amount of work.

Full method, every measurement and the sampling-accuracy study: [docs/benchmarks.md](docs/benchmarks.md) and [docs/sampling.md](docs/sampling.md).

## Privacy

Passports and reports contain aggregates only: no rows, no string min or max, and category values as tokens. Use `privacy="values"` to show top values, `sensitive=[...]` to withhold a column's distribution, and `DATAPASSPORT_TOKEN_SALT` to make tokens unguessable. Unsalted tokens of low-cardinality columns can be guessed. Details: [docs/privacy.md](docs/privacy.md).

## Limits, honestly

- **Scale.** Work is done by DuckDB, which streams Parquet and spills to disk under a memory limit. The benchmark harness covers up to 10M rows × 10 columns (1.1 GB CSV). CSV and JSON are first loaded into a DuckDB table, which needs disk or memory roughly the size of the data.
- **Fingerprints are integrity evidence, not signatures.** They catch accidental change, not a deliberately crafted collision. Use the recorded file `sha256` or sign the passport for tamper evidence.
- **Approximations are labelled.** Distinct counts above 1M rows and quantiles above 1M profiled rows are approximate. KS and PSI from passports are approximations of the exact statistics (KS within 0.02 in tests).
- **Engine-defined encodings.** Nested values and intervals are canonicalised through DuckDB's text output (pinned by golden tests). NumPy-backed pandas turns dates into timestamps.
- **CSV.** An unquoted empty field is NULL and a quoted one (`""`) is an empty string. Ragged files are rejected rather than guessed.
- **Not built.** Database sources beyond DuckDB, Spark, row-level value diffs, a desktop app.

## Project

- Status: alpha (0.1.0, unreleased). The file formats and fingerprint spec are versioned from day one: [docs/compatibility.md](docs/compatibility.md).
- Design: [architecture](docs/architecture.md) and [decision records](docs/adr).
- Release preparation: [distribution, launch drafts and adoption milestones](docs/adoption.md).
- Contributing: [CONTRIBUTING.md](CONTRIBUTING.md). License: [MIT](LICENSE).
