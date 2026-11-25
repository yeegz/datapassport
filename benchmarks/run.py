"""Benchmark DataPassport against simple baselines.

Every task runs in a fresh Python process. We record wall time of the work
itself (imports excluded) and the process's peak resident memory (imports
included, so a baseline that imports less looks lighter; that is fair, it is
what you would pay). Each task is repeated and the median time is reported.

    uv run python benchmarks/generate.py 1000000 10000000
    uv run python benchmarks/run.py            # writes benchmarks/results.json
"""

from __future__ import annotations

import json
import os
import platform
import statistics
import subprocess
import sys
import textwrap
from pathlib import Path

HERE = Path(__file__).parent
DATA = HERE / "data"

WRAP = """
import json, resource, sys, time
{imports}
t0 = time.perf_counter()
{body}
dt = time.perf_counter() - t0
rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
rss = rss if sys.platform == "darwin" else rss * 1024
print("@@" + json.dumps({{"seconds": dt, "peak_rss_bytes": rss, "result": str(result)[:120]}}))
"""

TASKS: dict[str, tuple[str, str, str]] = {
    # name: (group, imports, body). {v1}, {v2}, {csv} are substituted.
    "sha256 of file bytes": ("identity", "import hashlib", textwrap.dedent("""
        h = hashlib.sha256()
        with open({v1!r}, 'rb') as f:
            for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
        result = h.hexdigest()""")),
    "polars hash_rows().sum()": ("identity", "import polars as pl",
                                 "result = pl.read_parquet({v1!r}).hash_rows().sum()"),
    "datapassport fingerprint": ("identity", "import datapassport as dp",
                                 "result = dp.fingerprint({v1!r}).dataset"),
    "duckdb SUMMARIZE": ("profile", "import duckdb",
                         "result = duckdb.sql(\"SUMMARIZE SELECT * FROM read_parquet({v1!r})\").fetchall()[0]"),
    "polars describe()": ("profile", "import polars as pl", "result = pl.read_parquet({v1!r}).describe().shape"),
    "pandas describe(include='all')": ("profile", "import pandas as pd",
                                       "result = pd.read_parquet({v1!r}).describe(include='all').shape"),
    "datapassport inspect": ("profile", "import datapassport as dp",
                             "result = dp.inspect({v1!r}, key='id').fingerprint.short"),
    "datapassport inspect, sample=100k": ("profile", "import datapassport as dp",
                                          "result = dp.inspect({v1!r}, key='id', sample=100_000).sample.rows_profiled"),
    "polars keyed diff (join)": ("diff", "import polars as pl", textwrap.dedent("""
        a = pl.read_parquet({v1!r}); b = pl.read_parquet({v2!r})
        j = a.join(b, on='id', how='full', suffix='_b', coalesce=True, nulls_equal=True)
        cols = [c for c in a.columns if c != 'id']
        added = j.filter(pl.col('user_id').is_null() & pl.col('user_id_b').is_not_null()).height
        removed = j.filter(pl.col('user_id_b').is_null() & pl.col('user_id').is_not_null()).height
        both = j.filter(pl.col('user_id').is_not_null() & pl.col('user_id_b').is_not_null())
        changed = both.filter(pl.any_horizontal([pl.col(c).ne_missing(pl.col(c + '_b')) for c in cols])).height
        result = (added, removed, changed)""")),
    "datapassport compare --key id": ("diff", "import datapassport as dp", textwrap.dedent("""
        r = dp.compare({v1!r}, {v2!r}, key='id').rows
        result = (r.added, r.removed, r.changed)""")),
    "polars read_csv + describe()": ("csv", "import polars as pl", "result = pl.read_csv({csv!r}).describe().shape"),
    "datapassport inspect (CSV)": ("csv", "import datapassport as dp",
                                   "result = dp.inspect({csv!r}, key='id').fingerprint.short"),
    "datapassport inspect (CSV), memory_limit=1GB": (
        "csv", "import datapassport as dp",
        "result = dp.inspect({csv!r}, key='id', engine=dp.Engine(memory_limit='1GB')).fingerprint.short"),
}


def run(name: str, tag: str, repeats: int) -> dict[str, object]:
    group, imports, body = TASKS[name]
    paths = {"v1": str(DATA / f"v1_{tag}.parquet"), "v2": str(DATA / f"v2_{tag}.parquet"),
             "csv": str(DATA / f"v1_{tag}.csv")}
    code = WRAP.format(imports=imports, body=body.format(**paths))
    times, rss, result = [], [], None
    for _ in range(repeats):
        proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=1800)
        line = next((ln for ln in proc.stdout.splitlines() if ln.startswith("@@")), None)
        if proc.returncode != 0 or line is None:
            return {"task": name, "group": group, "size": tag, "error": (proc.stderr or proc.stdout)[-400:]}
        m = json.loads(line[2:])
        times.append(m["seconds"])
        rss.append(m["peak_rss_bytes"])
        result = m["result"]
    return {"task": name, "group": group, "size": tag, "repeats": repeats, "seconds_median": statistics.median(times),
            "seconds_all": times, "peak_rss_mb": round(max(rss) / 2**20), "result": result}


def machine() -> dict[str, object]:
    import duckdb
    import polars

    import datapassport

    info: dict[str, object] = {
        "load_average_at_start": [round(x, 2) for x in os.getloadavg()],
        "platform": platform.platform(), "machine": platform.machine(), "cpus": os.cpu_count(),
        "python": platform.python_version(), "datapassport": datapassport.__version__,
        "duckdb": duckdb.__version__, "polars": polars.__version__,
    }
    try:
        import pandas
        info["pandas"] = pandas.__version__
        mem = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True).stdout.strip()
        info["memory_gb"] = round(int(mem) / 2**30) if mem else None
        cpu = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True).stdout
        info["cpu"] = cpu.strip() or None
    except Exception:
        pass
    return info


def wait_for_quiet(max_load: float = 4.0, timeout_s: int = 3 * 3600) -> None:
    """Benchmarks on a busy machine measure the other work, not DataPassport."""
    import time

    start = time.time()
    while os.getloadavg()[0] > max_load and time.time() - start < timeout_s:
        print(f"waiting for a quiet machine (1-min load {os.getloadavg()[0]:.1f} > {max_load})", flush=True)
        time.sleep(60)


def main() -> None:
    sizes = sys.argv[1:] or ["1m", "10m"]
    wait_for_quiet()
    out = {"machine": machine(), "results": []}
    for tag in sizes:
        for name in TASKS:
            if tag == "10m" and name.startswith("pandas"):
                pass
            reps = 3 if tag != "10m" else 2
            res = run(name, tag, reps)
            res["load_average_after"] = round(os.getloadavg()[0], 2)
            out["results"].append(res)
            if "error" in res:
                print(f"{tag:>4}  {name:<48} ERROR {res['error'][-200:]}", flush=True)
            else:
                print(f"{tag:>4}  {name:<48} {res['seconds_median']:8.2f} s  {res['peak_rss_mb']:6} MB  {res['result']}",
                      flush=True)
    (HERE / "results.json").write_text(json.dumps(out, indent=2) + "\n")


if __name__ == "__main__":
    main()
