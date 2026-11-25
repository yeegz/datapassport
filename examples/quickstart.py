"""The five-minute tour. Run from the repository root:

    uv run python examples/make_data.py
    uv run python examples/quickstart.py
"""

from pathlib import Path

import datapassport as dp

DATA = Path(__file__).parent / "data"
OUT = Path(__file__).parent / "output"
OUT.mkdir(exist_ok=True)

# 1. Inspect: profile + fingerprint. CSV and Parquet copies of the same data match.
v1 = dp.inspect(DATA / "orders_v1.csv", key="order_id")
print(v1)
assert v1.fingerprint.dataset == dp.fingerprint(DATA / "orders_v1.parquet").dataset
v1.to_json(OUT / "orders_v1.passport.json")
v1.to_html(OUT / "orders_v1.html")

# 2. Compare: what changed between versions, row by row and in distribution.
diff = dp.compare(DATA / "orders_v1.parquet", DATA / "orders_v2.parquet", key="order_id")
print(diff.summary())
for change in diff.schema_changes:
    print(" ", change.describe())
diff.to_html(OUT / "orders_v1_v2.html")

# 3. Compare against a passport only: no old data needed.
print(dp.compare(OUT / "orders_v1.passport.json", DATA / "orders_v2.parquet").summary())

# 4. Check against a contract, with the old passport as baseline.
contract = dp.Contract.from_dict({
    "key": ["order_id"],
    "columns": {
        "order_id": {"type": "integer", "nullable": False},
        "status": {"allowed": ["new", "paid", "shipped", "cancelled"]},
        "amount": {"type": "number", "min": 0},
        "customer_email": {"sensitive": True, "pattern": r"[^@\s]+@[^@\s]+"},
    },
    "checks": [{"rule": "row_count_change", "max_fraction": 0.2}],
})
report = dp.check(DATA / "orders_v2.parquet", contract, baseline=OUT / "orders_v1.passport.json")
for r in report.failures + report.warnings:
    print(f"  {r.status.upper():5} {r.label}: {r.message}")
print("status:", report.status)
