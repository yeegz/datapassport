# Fingerprint specification `dp-fp/1`

A DataPassport fingerprint identifies the **content** of a table. Two tables have the same fingerprint when they hold the same multiset of rows under the same logical schema, whatever file format, row order, column order or physical integer width they use.

This page is the normative definition. Two implementations follow it:

- `datapassport.fingerprint.sql_row_encoding` plus the aggregate in `engine.compute_fingerprint` runs in DuckDB, out of core.
- `datapassport.fingerprint.reference_fingerprint` is a slow pure-Python version of the same spec.

A property test (`tests/test_fingerprint.py::test_sql_matches_reference`) generates random tables and checks that both give identical results. Golden vectors (`test_golden_vectors`) pin exact outputs. If either test changes, the spec version must change.

## What is and isn't part of identity

| Change to the data | Same fingerprint? |
| --- | --- |
| Rows in a different order | Yes |
| Columns in a different order | Yes |
| CSV ↔ Parquet ↔ JSON Lines ↔ Polars ↔ Arrow, same values and logical types | Yes |
| `INT8` ↔ `INT64` ↔ `UINT32` holding the same numbers | Yes |
| `DECIMAL(10,2)` `1.50` ↔ `DECIMAL(18,4)` `1.5000` | Yes |
| Timestamps in `s`, `ms`, `us` or `ns` units holding the same instant | Yes |
| Time-zone-aware timestamps shown in different zones (same instant) | Yes |
| Column names in NFC vs NFD Unicode form | Yes |
| `0.0` ↔ `-0.0` | Yes |
| A row duplicated | **No** (duplicates count) |
| Integer `1` ↔ string `"1"` ↔ float `1.0` | **No** (logical types are bound) |
| Naive timestamp ↔ time-zone-aware timestamp | **No** |
| `NULL` ↔ empty string ↔ `NaN` | **No** |
| `float32` `0.1` ↔ `float64` `0.1` | **No**, unless `float_digits ≤ 7` |
| Elements of a list in a different order | **No** (list order is content) |

## Algorithm

### 1. Logical schema

Each column gets a logical type from its engine type:

| Logical type | Engine types |
| --- | --- |
| `integer` | TINYINT … HUGEINT, all unsigned variants |
| `float` | FLOAT, DOUBLE |
| `decimal` | DECIMAL(p, s) of any precision and scale |
| `string` | VARCHAR, ENUM |
| `binary` | BLOB, BIT |
| `boolean`, `date`, `time`, `interval`, `uuid` | the same-named type |
| `timestamp` | TIMESTAMP, TIMESTAMP_S, _MS, _NS (no time zone) |
| `timestamp_tz` | TIMESTAMP WITH TIME ZONE |
| `list<T>`, `struct<a:T,…>`, `map<K,V>` | nested types, recursively |
| `null` | a column whose type is NULL (e.g. an all-null JSON field) |

**Schema digest** = `sha256` of the compact JSON array of `[NFC(name), logical_type]` pairs, sorted by `(NFC(name), logical_type)`, with `ensure_ascii=False` and separators `,` and `:`.

### 2. Column order

Columns are ordered by `(NFC(name), name)` in Unicode code point order.

### 3. Canonical value text

For a non-null value of logical type:

| Type | Canonical text |
| --- | --- |
| `boolean` | `true` or `false` |
| `integer` | base-10, leading `-` for negatives |
| `float` | `nan` for NaN; `0` for ±0; otherwise the value as IEEE-754 double formatted with `{:.Ng}` where N = `float_digits` (default 17). ±infinity format as `inf`/`-inf`. 17 digits round-trip every double exactly |
| `decimal` | `0` for zero; otherwise base-10 with trailing fractional zeros and a trailing `.` removed |
| `string` | the text itself (UTF-8) |
| `uuid` | lower-case canonical text |
| `binary` | lower-case hex |
| `date` | `YYYY-MM-DD` |
| `time` | integer microseconds since midnight |
| `timestamp`, `timestamp_tz` | integer microseconds since 1970-01-01T00:00:00 UTC; for nanosecond columns with a non-zero sub-microsecond part, append `.` and the 3-digit nanosecond remainder |
| nested | DuckDB's `to_json()` text (engine-defined, see limitations) |
| `interval` | DuckDB's text cast (engine-defined) |

### 4. Field and row encoding

- A **field** is `~` for NULL, otherwise `<byte length>:<canonical text>` where the length counts UTF-8 bytes of the canonical text. The length prefix makes field boundaries unambiguous: `("ab","c")` and `("a","bc")` encode differently, and the string `"~"` (`1:~`) differs from NULL (`~`).
- A **row** is the concatenation of its fields in column order (step 2).

### 5. Combination

For each row, compute `d = MD5(row as UTF-8)`. Let `hi` be bytes 0–7 of `d` read as a little-endian unsigned 64-bit integer, and `lo` bytes 8–15 read the same way.

```
S_hi = Σ hi  (mod 2^64)
S_lo = Σ lo  (mod 2^64)
N    = number of rows
```

Addition is commutative, so row order doesn't matter. Each copy of a row adds again, so duplicates count.

**Dataset fingerprint** = `sha256` of these lines joined with `\n`:

```
dp-fp/1
<schema digest>
<N>
<S_hi as 16 hex digits><S_lo as 16 hex digits>
float_digits=<N>
```

**Column fingerprint** = `sha256` of `dp-fp/1`, `column`, logical type, `N`, the column's own `S_hi S_lo` over its fields, and the `float_digits` line. The column name is left out on purpose: a renamed column keeps its fingerprint, which is how comparisons detect exact renames.

## Why these choices

- **MD5 per row** is available as a vectorised, version-stable built-in (`md5_number_upper/lower`) in DuckDB. Engine hash functions such as DuckDB `hash()` and Polars `hash_rows()` are documented as unstable across versions (duckdb#17596, pola-rs/polars#12496), so they can't be used.
- **Additive combination** follows the approach of data-diff's segment checksums. It is order-insensitive and can be computed in parallel and out of core with a plain `SUM`.
- **Microseconds as integers** for times avoid locale- and engine-specific timestamp text.
- **Type-bound encoding** (the schema digest) avoids the cross-type collisions seen in pola-rs/polars#27222.

## Security note

The fingerprint is **integrity evidence, not a signature**. It detects accidental change with overwhelming probability. Additive hashing over MD5 is not designed to resist someone *deliberately* constructing two different tables with the same fingerprint. For tamper evidence:

- use the file `sha256` recorded in `source.sha256` (byte identity), or
- sign the passport JSON with your usual tooling (for example Sigstore or GPG).

## Limitations

- Nested values and intervals use DuckDB's text output. The golden tests pin it, but a future DuckDB could change it. If that happens the golden tests fail, and the spec version will be bumped instead of silently producing new values.
- Floats inside nested values are not normalised by `float_digits`.
- Struct field order inside nested values is significant.
- Column names containing the NUL character are not supported.
- NumPy-backed pandas has no date type. Dates arrive as timestamps and get a different logical type. Use Arrow-backed pandas (`dtype_backend="pyarrow"`) or Polars when that matters.
- CSV can't tell `NULL` from an empty field. DataPassport reads an unquoted empty field as NULL and a quoted empty field (`""`) as an empty string, which is what Polars and pandas write.

## Versioning

The spec string `dp-fp/1` is written into every passport. Any change that can alter a fingerprint for the same data bumps it to `dp-fp/2`. Comparisons refuse to compare fingerprints made under different specs or with different `float_digits`.
