# Installation

DataPassport needs Python 3.11 or newer. Version 0.1.0 is available from a local source checkout or wheel.

```bash
python -m pip install .                # DuckDB, Pydantic, Typer, Rich, PyYAML
python -m pip install '.[polars]'      # Polars and PyArrow
python -m pip install '.[pandas]'      # pandas and PyArrow
python -m pip install '.[all]'         # both frame integrations
datapassport --help
```

To inspect the project and run the test suite with the checked-in dependency lock:

```bash
uv sync --locked
uv run --locked pytest
```

To build and install the wheel in a clean environment:

```bash
uv build
uv venv .venv-package
uv pip install --python .venv-package/bin/python dist/datapassport-0.1.0-py3-none-any.whl
.venv-package/bin/datapassport --help
```

On Windows, use `.venv-package\Scripts\python.exe` and `.venv-package\Scripts\datapassport.exe`.

## Troubleshooting

**"Can't tell the format of …".** The extension isn't one of `.csv .tsv .txt .json .jsonl .ndjson .parquet .pq` (optionally `.gz`). Pass `--format csv` (or `format="csv"`).

**"rows have different numbers of fields".** The CSV is ragged. DataPassport refuses to guess, because DuckDB's sniffer may otherwise skip leading lines without saying so. Pass the delimiter: `--read delim=','`. Add `--read null_padding=true` to pad short rows, or `--read ignore_errors=true` to skip bad rows. Then compare the row count with `wc -l` to see how many were dropped.

**"A value later in the file doesn't match the type guessed".** DuckDB guesses CSV types from a sample of rows. Use `--read sample_size=-1` (scan everything; slower) or `--read all_varchar=true` (read every column as text).

**A file with a title line before the header.** Pass `--read skip=1`.

**Different fingerprints for "the same" data.** Run `datapassport verify passport.json data` or `datapassport compare a b`. Common causes:

- a column changed type (for example dates in NumPy-backed pandas become timestamps);
- float noise (try `--float-digits 15`);
- `float32` vs `float64` (try `--float-digits 7`);
- CSV empty fields (unquoted empty means NULL, `""` means an empty string).

See [fingerprint-spec.md](fingerprint-spec.md).

**Out of memory on a large CSV.** Set `DATAPASSPORT_MEMORY_LIMIT=2GB` (and optionally `DATAPASSPORT_TEMP_DIRECTORY`). DuckDB then spills to disk. Parquet needs far less memory than CSV, because it isn't loaded into a table first. Profiling a sample (`--sample 1000000`) also helps; the fingerprint still covers every row.

**Custom rule "Unknown rule".** The rule must be registered before checking. In Python, import the module that defines it. On the command line, pass `--plugin module_name` or install it as an entry-point plugin.

**Polars frame: "DuckDB could not read this polars object".** Install `pyarrow` (`pip install "datapassport[polars]"`).
