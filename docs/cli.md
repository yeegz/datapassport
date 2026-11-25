# Command line

`datapassport` (short alias `dpp`). Run `datapassport COMMAND --help` for every option.

| Command | What it does |
| --- | --- |
| `inspect DATA` | Profile, then print a summary. `-o passport.json`, `--html report.html`, `--json`, `-k KEY`, `--sample 100000`, `--privacy values`, `--sensitive COL` |
| `fingerprint DATA` | Print the content fingerprint only (one pass) |
| `compare BASE TARGET` | Compare two versions (data or passports). `-k KEY`, `--examples N`, `--html`, `-o comparison.json`, `--output text\|json\|markdown`, `--fail-on change\|schema\|breaking\|drift` |
| `check DATA -c CONTRACT` | Validate. `-b baseline.passport.json`, `--output text\|json\|markdown\|github`, `--strict`, `--passport-out`, `--plugin my_rules`, `-v` |
| `verify PASSPORT DATA` | Exit 0 if DATA has exactly the recorded content; otherwise say what differs |
| `report FILE.json -o report.html` | Render a saved passport or comparison as HTML |
| `contract init DATA` | Draft a contract from data |
| `contract rules` | List contract rules, including registered custom rules |
| `schema passport\|comparison\|check\|contract` | Print a JSON Schema |

Reader options for any command that reads data: `--format csv|json|jsonl|parquet`, `--read key=value` (repeatable; values are parsed as JSON when possible: `--read header=false --read delim=';'`).

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Success. Checks passed, or passed with warnings without `--strict` |
| 1 | A check failed, `verify` didn't match, or a `--fail-on` condition was met |
| 2 | Bad input: missing file, unreadable data, invalid contract or option. The message includes a hint |
| 3 | Unexpected internal error. Set `DATAPASSPORT_DEBUG=1` for a traceback |

## Environment variables

| Variable | Effect |
| --- | --- |
| `DATAPASSPORT_THREADS` | DuckDB threads |
| `DATAPASSPORT_MEMORY_LIMIT` | e.g. `2GB`. DuckDB spills to disk above it |
| `DATAPASSPORT_TEMP_DIRECTORY` | Where DuckDB spills |
| `DATAPASSPORT_TOKEN_SALT` | Secret salt for category tokens |
| `DATAPASSPORT_DEBUG` | Show tracebacks for unexpected errors |
| `NO_COLOR` | Disable colour (status is always written as a word too) |
| `GITHUB_STEP_SUMMARY` | Set by GitHub Actions; `--output github`/`markdown` append the report to it |
