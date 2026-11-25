"""Command line interface: ``datapassport`` (alias ``dpp``).

Exit codes
  0  success (checks passed, or passed with warnings without --strict)
  1  a check failed, verification did not match, or a --fail-on condition was met
  2  bad input: missing file, unreadable data, invalid contract or options
  3  unexpected internal error (please report it)
"""

from __future__ import annotations

import json
import os
import sys
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

import typer

from . import __version__
from .errors import DataPassportError

app = typer.Typer(
    name="datapassport",
    help="Portable evidence about datasets: fingerprint, profile, compare and validate.",
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode="rich",
    context_settings={"help_option_names": ["-h", "--help"]},
)
contract_app = typer.Typer(help="Create and inspect contracts.", no_args_is_help=True)
app.add_typer(contract_app, name="contract")


class Fmt(StrEnum):
    text = "text"
    json = "json"
    markdown = "markdown"
    github = "github"


class FailOn(StrEnum):
    none = "none"
    change = "change"
    schema = "schema"
    breaking = "breaking"
    drift = "drift"


def _out(stderr: bool = False) -> Any:
    from .report.terminal import console

    return console(stderr=stderr)


def _parse_read(items: list[str] | None) -> dict[str, Any] | None:
    if not items:
        return None
    out: dict[str, Any] = {}
    for item in items:
        if "=" not in item:
            raise DataPassportError(f"--read expects key=value, got {item!r}", hint="Example: --read delim=';'")
        k, v = item.split("=", 1)
        try:
            out[k.strip()] = json.loads(v)
        except json.JSONDecodeError:
            out[k.strip()] = v
    return out


def _sample(value: str | None) -> int | float | None:
    if value is None:
        return None
    try:
        return float(value) if "." in value else int(value)
    except ValueError:
        raise DataPassportError(f"--sample must be a row count or a fraction, got {value!r}") from None


def _run(fn: Any) -> Any:
    try:
        return fn()
    except DataPassportError as e:
        err = _out(stderr=True)
        err.print(f"[bold red]error:[/] {e.message}", markup=True, highlight=False)
        if e.hint:
            err.print(f"[dim]hint:[/] {e.hint}", markup=True, highlight=False)
        raise typer.Exit(2) from None
    except (typer.Exit, typer.Abort, KeyboardInterrupt):
        raise
    except Exception as e:  # pragma: no cover - last resort
        if os.environ.get("DATAPASSPORT_DEBUG"):
            raise
        err = _out(stderr=True)
        err.print(f"[bold red]unexpected error:[/] {type(e).__name__}: {e}", markup=True)
        err.print("[dim]Set DATAPASSPORT_DEBUG=1 for a traceback, and please report it.[/]", markup=True)
        raise typer.Exit(3) from None


def _write_summary(markdown: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(markdown + "\n")


Key = Annotated[list[str] | None, typer.Option("--key", "-k", help="Key column(s). Repeat for composite keys.")]
Format = Annotated[
    str | None, typer.Option("--format", "-f", help="Force the input format: csv, json, jsonl, parquet.")
]
Read = Annotated[list[str] | None, typer.Option("--read", help="Reader option key=value, e.g. delim=';'. Repeatable.")]
FloatDigits = Annotated[
    int, typer.Option("--float-digits", min=1, max=17, help="Significant digits used to fingerprint floats.")
]


def _version(value: bool) -> None:
    if value:
        typer.echo(f"datapassport {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool, typer.Option("--version", callback=_version, is_eager=True, help="Show the version and exit.")
    ] = False,
) -> None:
    """DataPassport."""


@app.command()
def inspect(
    data: Annotated[str, typer.Argument(help="File, glob or directory (CSV, TSV, JSON, JSONL, Parquet).")],
    key: Key = None,
    out: Annotated[Path | None, typer.Option("--out", "-o", help="Write the passport JSON here.")] = None,
    html: Annotated[Path | None, typer.Option("--html", help="Write an HTML report here.")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Print the passport JSON instead of a table.")] = False,
    sample: Annotated[
        str | None, typer.Option("--sample", help="Profile a sample: row count (100000) or fraction (0.1).")
    ] = None,
    seed: Annotated[int, typer.Option(help="Sampling seed.")] = 0,
    privacy: Annotated[str, typer.Option(help="safe (default): no raw values. values: include top values.")] = "safe",
    sensitive: Annotated[
        list[str] | None, typer.Option("--sensitive", help="Column whose distribution is withheld. Repeatable.")
    ] = None,
    name: Annotated[str | None, typer.Option(help="Dataset name (defaults to the file name).")] = None,
    float_digits: FloatDigits = 17,
    format: Format = None,
    read: Read = None,
) -> None:
    """Profile a dataset and print its passport."""
    from .engine import inspect as _inspect

    def go() -> None:
        p = _inspect(
            data,
            key=key,
            sample=_sample(sample),
            seed=seed,
            privacy=privacy,
            sensitive=sensitive or (),
            name=name,
            float_digits=float_digits,
            format=format,
            read_options=_parse_read(read),
        )
        if out:
            p.to_json(out)
        if html:
            p.to_html(html)
        if as_json:
            sys.stdout.write(p.to_json())
            return
        from .report.terminal import passport_view

        con = _out()
        con.print(passport_view(p))
        for label, path in (("passport", out), ("report", html)):
            if path:
                con.print(f"[dim]wrote {label} to {path}[/]", markup=True)

    _run(go)


@app.command()
def fingerprint(
    data: Annotated[str, typer.Argument(help="File, glob or directory.")],
    float_digits: FloatDigits = 17,
    as_json: Annotated[bool, typer.Option("--json", help="Print the full fingerprint as JSON.")] = False,
    format: Format = None,
    read: Read = None,
) -> None:
    """Print the content fingerprint (row-order-insensitive). One pass, no profile."""
    from .engine import fingerprint as _fp

    def go() -> None:
        fp = _fp(data, float_digits=float_digits, format=format, read_options=_parse_read(read))
        if as_json:
            sys.stdout.write(json.dumps(fp.model_dump(by_alias=True), indent=2) + "\n")
        else:
            typer.echo(f"{fp.dataset}  {fp.rows} rows  {data}")

    _run(go)


@app.command()
def compare(
    base: Annotated[str, typer.Argument(help="Old version: data or a passport JSON.")],
    target: Annotated[str, typer.Argument(help="New version: data or a passport JSON.")],
    key: Key = None,
    out: Annotated[Path | None, typer.Option("--out", "-o", help="Write the comparison JSON here.")] = None,
    html: Annotated[Path | None, typer.Option("--html", help="Write an HTML report here.")] = None,
    output: Annotated[Fmt, typer.Option("--output", help="text, json or markdown.")] = Fmt.text,
    examples: Annotated[int, typer.Option(help="Show up to N key values per kind of change (keys only).")] = 0,
    fail_on: Annotated[
        FailOn, typer.Option("--fail-on", help="Exit 1 on: change, schema, breaking, drift.")
    ] = FailOn.none,
    sample: Annotated[str | None, typer.Option("--sample", help="Profile a sample for drift.")] = None,
    float_digits: FloatDigits = 17,
    format: Format = None,
    read: Read = None,
) -> None:
    """Compare two versions: schema changes, row changes and distribution drift."""
    from .compare import compare as _compare

    def go() -> None:
        c = _compare(
            base,
            target,
            key=key,
            examples=examples,
            sample=_sample(sample),
            float_digits=float_digits,
            format=format,
            read_options=_parse_read(read),
        )
        if out:
            c.to_json(out)
        if html:
            c.to_html(html)
        if output == Fmt.json:
            sys.stdout.write(c.to_json())
        elif output in {Fmt.markdown, Fmt.github}:
            md = c.to_markdown()
            sys.stdout.write(md)
            _write_summary(md)
        else:
            from .report.terminal import comparison_view

            _out().print(comparison_view(c))
            if c.rows.examples:
                for kind, keys in c.rows.examples.items():
                    if keys:
                        _out().print(
                            f"[dim]{kind}:[/] "
                            + ", ".join("(" + ", ".join(map(str, k)) + ")" if len(k) > 1 else str(k[0]) for k in keys),
                            markup=True,
                        )
        failed = {
            FailOn.none: False,
            FailOn.change: not c.identical,
            FailOn.schema: bool(c.schema_changes),
            FailOn.breaking: bool(c.breaking_changes),
            FailOn.drift: any(d.status == "fail" for d in c.drift.values()),
        }[fail_on]
        if failed:
            raise typer.Exit(1)

    _run(go)


@app.command()
def check(
    data: Annotated[str, typer.Argument(help="Data to validate.")],
    contract: Annotated[Path, typer.Option("--contract", "-c", help="Contract file (YAML, JSON or TOML).")],
    baseline: Annotated[Path | None, typer.Option("--baseline", "-b", help="Passport of the previous version.")] = None,
    output: Annotated[
        Fmt, typer.Option("--output", help="text, json, markdown or github (annotations + step summary).")
    ] = Fmt.text,
    strict: Annotated[bool, typer.Option(help="Treat warnings as failures.")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="List passing checks too.")] = False,
    out: Annotated[Path | None, typer.Option("--out", "-o", help="Write the check report JSON here.")] = None,
    passport_out: Annotated[
        Path | None, typer.Option("--passport-out", help="Also write the data's passport here.")
    ] = None,
    html: Annotated[Path | None, typer.Option("--html", help="Write an HTML report of the results here.")] = None,
    plugin: Annotated[
        list[str] | None, typer.Option("--plugin", help="Import this module first (custom rules). Repeatable.")
    ] = None,
    sample: Annotated[
        str | None, typer.Option("--sample", help="Profile a sample (rules still check every row).")
    ] = None,
    format: Format = None,
    read: Read = None,
) -> None:
    """Validate data against a contract (and a baseline passport). Exit 1 on failure."""
    from .rules import check as _check

    def go() -> None:
        import importlib

        sys.path.insert(0, os.getcwd())
        for mod in plugin or []:
            try:
                importlib.import_module(mod)
            except ImportError as e:
                raise DataPassportError(f"Could not import plugin module {mod!r}: {e}") from e
        rep = _check(
            data, contract, baseline=baseline, sample=_sample(sample), format=format, read_options=_parse_read(read)
        )
        if out:
            rep.to_json(out)
        if passport_out and rep.passport is not None:
            rep.passport.to_json(passport_out)
        if html:
            from .report.html import check_html

            html.write_text(check_html(rep), encoding="utf-8")
        if output == Fmt.json:
            sys.stdout.write(rep.to_json())
        elif output == Fmt.markdown:
            sys.stdout.write(rep.to_markdown())
        elif output == Fmt.github:
            ann = rep.github_annotations()
            if ann:
                sys.stdout.write(ann + "\n")
            sys.stdout.write(rep.to_markdown())
            _write_summary(rep.to_markdown())
        else:
            from .report.terminal import check_view

            _out().print(check_view(rep, verbose=verbose))
        raise typer.Exit(rep.exit_code(strict))

    _run(go)


@app.command()
def verify(
    passport: Annotated[Path, typer.Argument(help="Passport JSON.")],
    data: Annotated[str, typer.Argument(help="Data that should match it.")],
) -> None:
    """Check that DATA has exactly the content recorded in PASSPORT. Exit 1 if not."""
    from . import _same_kind_options
    from .engine import fingerprint as _fp
    from .models import Passport

    def go() -> None:
        p = Passport.load(passport)
        fp = _fp(data, float_digits=p.fingerprint.float_digits, read_options=_same_kind_options(p, data))
        con = _out()
        if fp.dataset == p.fingerprint.dataset:
            con.print(
                f"[bold green]MATCH[/]  {data} has the content recorded in {passport} "
                f"({fp.rows:,} rows, {fp.dataset[:12]})",
                markup=True,
            )
            return
        con.print(f"[bold red]MISMATCH[/]  {data} differs from {passport}", markup=True)
        con.print(
            f"  expected {p.fingerprint.dataset[:12]} ({p.rows:,} rows)\n"
            f"  found    {fp.dataset[:12]} ({fp.rows:,} rows)"
        )
        if fp.schema_ != p.fingerprint.schema_:
            con.print("  the schema (column names or types) differs")
        else:
            changed = [c for c, h in p.fingerprint.columns.items() if fp.columns.get(c) != h]
            if changed:
                con.print("  columns with different values: " + ", ".join(changed))
        raise typer.Exit(1)

    _run(go)


@app.command()
def report(
    source: Annotated[Path, typer.Argument(help="A passport or comparison JSON file.")],
    out: Annotated[Path, typer.Option("--out", "-o", help="HTML file to write.")] = Path("report.html"),
) -> None:
    """Render a saved passport or comparison as a self-contained HTML report."""

    def go() -> None:
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise DataPassportError(f"File not found: {source}") from None
        fmt = data.get("format") if isinstance(data, dict) else None
        if fmt == "datapassport/passport":
            from .models import Passport

            Passport.model_validate(data).to_html(out)
        elif fmt == "datapassport/comparison":
            from .compare import Comparison

            Comparison.model_validate(data).to_html(out)
        else:
            raise DataPassportError(f"{source} is not a passport or comparison file")
        _out().print(f"wrote {out}")

    _run(go)


@app.command()
def schema(
    kind: Annotated[str, typer.Argument(help="passport, comparison, check or contract.")] = "passport",
) -> None:
    """Print the JSON Schema of a DataPassport file format."""
    from .compare import Comparison
    from .contract import Contract
    from .models import Passport
    from .rules import CheckReport

    models: dict[str, Any] = {
        "passport": Passport,
        "comparison": Comparison,
        "check": CheckReport,
        "contract": Contract,
    }

    def go() -> None:
        if kind not in models:
            raise DataPassportError(f"Unknown schema {kind!r}", hint="Use: " + ", ".join(models))
        sys.stdout.write(json.dumps(models[kind].model_json_schema(by_alias=True), indent=2) + "\n")

    _run(go)


@contract_app.command("init")
def contract_init(
    data: Annotated[str, typer.Argument(help="Data to draft a contract from.")],
    key: Key = None,
    strict: Annotated[bool, typer.Option(help="Also pin numeric ranges to the observed min and max.")] = False,
    out: Annotated[Path | None, typer.Option("--out", "-o", help="Write here instead of printing.")] = None,
    format: Format = None,
    read: Read = None,
) -> None:
    """Draft a contract from data. Review it before relying on it."""
    from .contract import Contract
    from .engine import inspect as _inspect

    def go() -> None:
        p = _inspect(data, key=key, privacy="values", format=format, read_options=_parse_read(read))
        text = (
            "# Drafted by `datapassport contract init`. Review before use: it describes\n"
            "# the data as it is today, not as it should be.\n" + Contract.infer(p, strict=strict).to_yaml()
        )
        if out:
            out.write_text(text, encoding="utf-8")
            _out().print(f"wrote {out}")
        else:
            sys.stdout.write(text)

    _run(go)


@contract_app.command("rules")
def contract_rules() -> None:
    """List rules usable in contracts, including registered custom rules."""
    from .plugins import registered_rules

    typer.echo(
        "Column fields: type, required, nullable, max_null_fraction, unique, min, max, allowed,\n"
        "               pattern, min_length, max_length, not_blank, sensitive, severity, checks"
    )
    typer.echo("Dataset fields: key, rows.min, rows.max, schema.extra_columns, schema.column_order, drift")
    typer.echo("Named checks: no_duplicate_rows, row_count_change, fingerprint_matches")
    custom = registered_rules()
    typer.echo("Custom rules: " + (", ".join(custom) if custom else "(none registered)"))


if __name__ == "__main__":  # pragma: no cover
    app()
