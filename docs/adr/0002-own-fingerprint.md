# 0002 Defining our own fingerprint

Status: accepted, 25 Nov 2026

## Context

Existing "dataset hashes" are byte hashes (DVC, Croissant, Frictionless). They change when the same rows are rewritten in another format, compressed differently or reordered. Engine row hashes (DuckDB `hash()`, Polars `hash_rows`) are explicitly not stable across versions. data-diff's order-insensitive checksum depends on each database's text casts, and the project is archived.

## Decision

Publish a versioned spec (`dp-fp/1`, [fingerprint-spec.md](../fingerprint-spec.md)) built from:

- a type-tagged, length-prefixed canonical encoding,
- MD5 per row, summed in two 64-bit lanes for order insensitivity,
- sha256 over the schema digest, row count, sums and options.

Ship a pure-Python reference implementation and test the SQL against it with Hypothesis.

## Consequences

- The same content gives the same fingerprint across CSV, Parquet, JSON Lines and in-memory frames. Tests cover this.
- It isn't a cryptographic commitment. We say so, and we record the file sha256 for byte identity.
- Changing any canonical form requires a new spec version, so the golden vectors are effectively a public contract.
