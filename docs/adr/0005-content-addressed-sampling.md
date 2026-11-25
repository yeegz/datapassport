# 0005 Content-addressed sampling

Status: accepted, 25 Nov 2026

## Context

Profiling every row of a very large dataset can be slower than needed for a dashboard or a drift check. Random sampling makes two runs over the same data disagree, and DuckDB's reservoir sampling is not guaranteed repeatable under multithreading.

## Decision

`sample=` keeps a row when DuckDB's `hash(seed, columns…)` modulo 10^6 falls under a threshold derived from the target size. Columns are hashed in canonical (sorted-name) order. The fingerprint, duplicate counts and contract rules still use **all** rows. Only the profile is sampled.

## Consequences

- An earlier version hashed the fingerprint encoding with MD5. That cost a full extra hashing pass (about 6 s at 10M rows), so sampling saved nothing. DuckDB's native hash costs about 0.25 s. It is deterministic for a given DuckDB version, which is recorded in the passport, but the selection may change when DuckDB changes its hash function. Fingerprints never depend on it.

- The same data gives the same sample, whatever the row order. Tests cover this.
- Unchanged rows are sampled identically in two versions, which reduces noise when comparing sampled profiles.
- The sample size is approximate (binomial around the target).
- Exact duplicates are either all kept or all dropped. Accuracy trade-offs are measured in [sampling.md](../sampling.md).
