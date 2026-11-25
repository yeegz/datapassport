# 0004 Privacy by default

Status: accepted, 25 Nov 2026

## Context

Profiling tools often embed sample rows, frequent values and string min/max in reports, and reports get attached to CI runs and pull requests. Issue trackers show users asking how to keep personal data out of them (for example fg-data-profiling #1432).

## Decision

- Passports and reports **never contain rows**.
- String columns record lengths, empty and blank counts, and category frequencies. They never record min/max.
- Category values are stored as `sha256` tokens (16 hex digits). `privacy="values"` opts in to storing the values themselves.
- Set `DATAPASSPORT_TOKEN_SALT` to salt tokens with a secret. Tokens then stay comparable inside your organisation, but nobody outside can guess them.
- Columns marked `sensitive` (argument or contract) keep only counts, nulls and distinct counts.
- Keyed diffs list example *keys* only when asked (`examples=N`), never values.

## Consequences

- Unsalted tokens of low-cardinality values can be guessed by hashing candidates. That is pseudonymisation, not anonymisation, and the docs say so.
- Numeric min, max and quantiles are still recorded for non-sensitive columns. Mark a column sensitive if they would reveal something (salaries, for example).
