# Privacy

DataPassport reports are made to be shared: attached to CI runs, posted in pull requests, kept next to data. So by default they hold **aggregates only**.

| Kept in a passport | Never kept |
| --- | --- |
| Row and column counts, null counts, distinct counts | Rows or sample records |
| Numeric min, max, mean, std, 101 quantiles | String min or max |
| String length stats, empty and blank counts | Raw category values (unless `privacy="values"`) |
| Category frequencies as tokens | Values of `sensitive` columns' distributions |
| Date and timestamp min and max | Key values (unless you ask for `examples`) |

## Options

- `privacy="values"` (CLI `--privacy values`) stores the top-k category values in clear text. Use it for internal reports on non-personal columns.
- `sensitive=[...]` (CLI `--sensitive col`, contract `sensitive: true`) keeps only counts, nulls and distinct counts for those columns.
- `DATAPASSPORT_TOKEN_SALT=<secret>` salts category tokens. Passports made with the same salt stay comparable. A party without the secret salt cannot check guesses against salted tokens.

## What tokens do and don't protect

A token is `sha256("dp-token/1:" + value)[:16]`. For a low-cardinality column like `country`, anyone can hash every country name and match the tokens. That makes unsalted tokens **pseudonymous, not anonymous**. Use a salt, or mark the column sensitive, when that matters.

Passports also include schema and source metadata. Review source paths, column names and contract descriptions before sharing them.

Numeric quantiles reveal the shape of a distribution, and p0 and p100 are the min and max. Mark columns such as salaries sensitive.

## Checking it

`tests/test_profile.py::test_safe_mode_has_no_raw_values` asserts that raw string values from the test data don't appear in the JSON or HTML output.
