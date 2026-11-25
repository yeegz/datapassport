# Contributing

Thanks for helping. Bug reports, docs fixes, new rules and adapters are all welcome.

## Set up

```bash
git clone https://github.com/yeegz/datapassport && cd datapassport
uv sync                       # creates .venv with dev dependencies
uv run pytest                 # fast suite (~30 s)
uv run pytest -m slow         # adds large-file tests
uv run ruff check src tests && uv run ruff format src tests
uv run mypy                   # strict
```

## Ground rules

- **Fingerprint changes are spec changes.** If `tests/test_fingerprint.py::test_golden_vectors` fails, you changed what a fingerprint means. That needs a new spec version (`dp-fp/2`), a section in `docs/fingerprint-spec.md` and a changelog entry. Don't just update the pinned values.
- **No raw values in reports by default.** New statistics must not put row values in passports unless `privacy="values"`. Add a test like `test_safe_mode_has_no_raw_values`.
- **Label approximations.** If a number is estimated, say so in the output (see `distinct_exact` and `sample.method`).
- **Benchmarks are measured, never typed in.** Update `docs/benchmarks.md` only from `benchmarks/run.py` output, and keep the machine details.
- **Readable errors.** Raise a `DataPassportError` subclass with a `hint` that says what to try.
- Public API changes follow [docs/compatibility.md](docs/compatibility.md).

## Where things live

See [docs/architecture.md](docs/architecture.md). Short version: `engine.py` runs SQL, `fingerprint.py` is the spec, `compare.py` and `drift.py` compare, `rules.py` checks contracts, and `report/` renders.

## Pull requests

- One topic per PR, with tests.
- Add a line to `CHANGELOG.md` under "Unreleased".
- CI runs lint, mypy, tests on Linux, macOS and Windows with Python 3.11–3.14, a lowest-dependency run, and a wheel smoke test.

## Releasing (maintainers)

1. Update `src/datapassport/__about__.py` and `CHANGELOG.md`.
2. Tag `vX.Y.Z` and publish a GitHub release. `.github/workflows/release.yml` publishes to PyPI through trusted publishing.

Please follow the [Code of Conduct](CODE_OF_CONDUCT.md).
