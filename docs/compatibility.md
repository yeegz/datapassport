# Versioning and compatibility

DataPassport follows [Semantic Versioning](https://semver.org). Before 1.0, minor releases may change the Python API, with notes in `CHANGELOG.md`. The file formats and the fingerprint spec carry their own versions and are held to a stricter standard from the first release.

| Surface | Version marker | Rule |
| --- | --- | --- |
| Fingerprint | `fingerprint.spec` (`dp-fp/1`) | Never changes meaning within a spec version. Golden vectors in the test suite enforce this. A change ships as `dp-fp/2`, and the old spec stays computable for at least one major release |
| Passport JSON | `format_version` (1) | New optional fields may be added. Removing or renaming a field bumps the version. Readers reject passports newer than they understand, with a hint to upgrade |
| Comparison and check JSON | `format_version` (1) | As for passports |
| Contract files | `version` (1) | New optional fields may be added. Unknown fields are rejected (typos shouldn't pass silently) |
| CLI | – | Exit codes 0/1/2/3 and existing flags are stable from 0.1. New flags may be added |
| Python API | `__all__` in `datapassport/__init__.py` | Only names in `__all__` are public. Modules starting with `_` are private |
| Plugin API | `rule`, `metric`, `register_source`, `RuleContext`, `MetricContext`, `Outcome` | Kept backward compatible within a major version |

## Supported versions

- Python 3.11 to 3.14 (3.10 reached end of life in October 2026).
- DuckDB ≥ 1.1, Pydantic ≥ 2.6, Typer ≥ 0.12, Rich ≥ 13. CI tests the newest versions and the lowest allowed versions.
- Operating systems: Linux, macOS and Windows (CI matrix).

## Deprecation

A deprecated public name keeps working for at least one minor release, emits a `DeprecationWarning`, and is listed under "Deprecated" in the changelog.
