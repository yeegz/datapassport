"""Render results.json and accuracy.json into docs/benchmarks.md and docs/sampling.md tables.

Numbers are copied from the JSON files, never typed by hand.

    uv run python benchmarks/render.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent


def table(results: list[dict], group: str, sizes: list[str]) -> str:
    rows = ["| Task | " + " | ".join(f"{s.upper()} rows: time · peak RSS" for s in sizes) + " |",
            "| --- | " + " | ".join("---:" for _ in sizes) + " |"]
    names = list(dict.fromkeys(r["task"] for r in results if r["group"] == group))
    for name in names:
        cells = []
        for s in sizes:
            r = next((x for x in results if x["task"] == name and x["size"] == s), None)
            if r is None:
                cells.append("–")
            elif "error" in r:
                cells.append("failed")
            else:
                cells.append(f"{r['seconds_median']:.2f} s · {r['peak_rss_mb']:,} MB")
        rows.append(f"| {name} | " + " | ".join(cells) + " |")
    return "\n".join(rows)


def machine(m: dict) -> str:
    return (f"{m.get('cpu') or m['machine']}, {m['cpus']} cores, {m.get('memory_gb')} GB RAM, {m['platform']}; "
            f"Python {m['python']}, datapassport {m['datapassport']}, DuckDB {m['duckdb']}, Polars {m['polars']}, "
            f"pandas {m.get('pandas')}; 1-minute load average when the run started: {m.get('load_average_at_start', ['?'])[0]}")


def replace_block(text: str, name: str, content: str) -> str:
    pattern = re.compile(rf"(<!-- {name} -->\n).*?(^<!-- /{name} -->$)", re.S | re.M)
    return pattern.sub(lambda m: m.group(1) + content + "\n" + m.group(2), text)


def main() -> None:
    res = json.loads((HERE / "results.json").read_text())
    sizes = list(dict.fromkeys(r["size"] for r in res["results"]))
    doc = ROOT / "docs" / "benchmarks.md"
    text = doc.read_text()
    text = replace_block(text, "machine", machine(res["machine"]))
    for g in ("identity", "profile", "diff", "csv"):
        text = replace_block(text, g, table(res["results"], g, sizes))
    doc.write_text(text)

    acc_path = HERE / "accuracy.json"
    if acc_path.exists():
        acc = json.loads(acc_path.read_text())
        lines = ["| Target sample | Rows profiled (3 seeds) | Time | Worst mean error | Worst p50 error | Worst p99 error "
                 "| Worst null-rate error | Worst category TVD | Distinct ratio user_id / email | Drift flags vs full |",
                 "| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |"]
        for s in acc["summary"]:
            lines.append(
                f"| {s['target']:,} | {', '.join(f'{x:,}' for x in s['rows_profiled'])} | {s['seconds_median']:.1f} s "
                f"| {s['worst_mean_rel_err']:.3%} | {s['worst_p50_err_iqr']:.3f} IQR | {s['worst_p99_err_iqr']:.3f} IQR "
                f"| {s['worst_null_frac_abs_err']:.4f} | {s['worst_category_tvd']:.4f} "
                f"| {min(s['user_id_distinct_ratio']):.3f} / {min(s['email_distinct_ratio']):.3f} "
                f"| {max(s['drift_flags_vs_full'])} (max PSI {s['max_psi_vs_full']:.4f}) |")
        sdoc = ROOT / "docs" / "sampling.md"
        st = sdoc.read_text()
        st = replace_block(st, "accuracy", "\n".join(lines))
        st = replace_block(st, "accuracy-meta",
                           f"File `{acc['file']}`, {acc['rows']:,} rows. Full profile took "
                           f"{acc['full_profile_seconds']} s.")
        sdoc.write_text(st)
    print("rendered")


if __name__ == "__main__":
    main()
