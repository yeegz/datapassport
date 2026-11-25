# Contracts

A contract is a reusable description of what a dataset must look like. Write it in YAML, JSON or TOML, or build a `dp.Contract` in Python. Start from a draft:

```bash
datapassport contract init data/orders.parquet --key order_id -o contract.yml
```

The draft describes the data **as it is today**. Review it: loosen what may legitimately change, tighten what must never change.

## Full reference

```yaml
version: 1
dataset: orders                 # name used in reports
description: Daily order export
key: [order_id]                 # must be unique and non-null; used for keyed diffs
rows: {min: 1, max: 5000000}
schema:
  extra_columns: warn           # allow (default) | warn | forbid
  column_order: ignore          # ignore (default) | enforce
columns:
  order_id:
    type: integer               # see types below
    nullable: false
    unique: true
  status:
    type: string
    allowed: [new, paid, shipped, cancelled]
    max_null_fraction: 0.01
  amount:
    type: number                # integer, float or decimal
    min: 0
    max: 100000
  email:
    type: string
    pattern: '^[^@\s]+@[^@\s]+$' # full match
    sensitive: true             # withhold its distribution from passports and reports
  note:
    required: false             # may be absent
    max_length: 500
    not_blank: true
    severity: warn              # failures in this column only warn
  total:
    checks:
      - {rule: my_custom_rule, threshold: 3}
checks:
  - {rule: no_duplicate_rows}
  - {rule: row_count_change, max_decrease: 0.05, max_increase: 0.5, severity: warn}
  - {rule: fingerprint_matches, fingerprint: 8f08565fa552}
drift:                          # only used with a baseline passport
  default: {metric: psi, warn: 0.1, fail: 0.25}
  amount: {metric: wasserstein_norm, fail: 0.3}
  created_at: {skip: true}
```

### Types

`integer`, `float`, `decimal`, `number` (any of the three), `string`, `boolean`, `date`, `time`, `timestamp`, `timestamp_tz`, `binary`, `uuid`, `interval`, `list`, `struct`, `map`, an exact nested type such as `list<integer>`, or `any`. An all-null column satisfies any type.

### Column rules

| Field | Fails when | Evaluated on |
| --- | --- | --- |
| `required` (default true) | the column is missing | schema |
| `type` | the logical type isn't compatible | schema |
| `nullable: false` | any null | all rows |
| `max_null_fraction` | share of nulls above the limit | all rows |
| `unique` | any repeated non-null value | all rows |
| `min`, `max` | a value outside the range (inclusive). Dates and timestamps accept ISO strings | all rows |
| `allowed` | a non-null value outside the list (compared as text) | all rows |
| `pattern` | a non-null value that doesn't fully match the regex (RE2 syntax) | all rows |
| `min_length`, `max_length` | text length outside the range | all rows |
| `not_blank` | an empty or whitespace-only value | all rows |

Column rules always run on **every row**, even when `--sample` is used for the profile. Violations are counted in a single scan.

### Dataset rules

| Rule | Fails when |
| --- | --- |
| `key` | duplicate or null key values |
| `rows.min` / `rows.max` | row count out of range |
| `schema.extra_columns` | columns not in the contract (`warn` or `forbid`) |
| `schema.column_order: enforce` | contract columns appear in a different order |
| `no_duplicate_rows` | any exact duplicate row |
| `row_count_change` | rows changed by more than `max_fraction` (or `max_decrease` / `max_increase`) relative to the baseline |
| `fingerprint_matches` | content differs from `fingerprint` (a prefix is fine), or from the baseline |

### Baseline checks

With `--baseline previous.passport.json` (or `baseline=` in Python), the check also reports:

- **Schema changes.** Removed, renamed and narrowed columns fail. Added columns and widening (`integer` → `float`) pass.
- **Drift** per column using the `drift` section, with defaults PSI warn 0.1 and fail 0.25. Key columns are skipped, and so are columns with fewer than 50 values (`min_count`).

### Severity and exit codes

Each rule has `severity: error` (default) or `warn`. The report status is `fail` if any error-severity rule failed, `warn` if only warnings, and `pass` otherwise. `datapassport check` exits 1 on `fail`, or on `warn` with `--strict`.

### From Pandera

```python
from datapassport.integrations.pandera import contract_from_pandera
contract = contract_from_pandera(OrdersSchema)   # DataFrameModel or DataFrameSchema
```

Checks that don't map exactly are listed in `contract.description`, so nothing is dropped silently.
