"""Builds quickstart.ipynb from the cells below and executes it (outputs are saved).

    uv run --with nbformat --with nbclient --with ipykernel python examples/notebooks/build_quickstart.py
"""

from pathlib import Path

import nbformat
from nbclient import NotebookClient

HERE = Path(__file__).parent
cells = [
    ("md", "# DataPassport quickstart\n\nInspect a dataset, compare two versions, and check a contract. "
           "Run `python examples/make_data.py` first."),
    ("code", "import datapassport as dp\nimport polars as pl\nDATA = '../data'"),
    ("md", "## 1. Inspect\n\nA passport is a fingerprint plus a column profile. It renders as a report in notebooks."),
    ("code", "v1 = dp.inspect(f'{DATA}/orders_v1.csv', key='order_id')\nv1"),
    ("md", "The fingerprint ignores row order and file format. The Parquet copy and a shuffled frame match the CSV:"),
    ("code", "df = pl.read_parquet(f'{DATA}/orders_v1.parquet')\n"
             "(v1.fingerprint.dataset == dp.fingerprint(df.sample(fraction=1, shuffle=True, seed=1)).dataset)"),
    ("md", "Column statistics as a Polars frame:"),
    ("code", "v1.column_table()"),
    ("md", "## 2. Compare versions\n\nWith a key, rows are matched and changes counted per column. "
           "Schema changes, including likely renames, and drift are reported."),
    ("code", "diff = dp.compare(f'{DATA}/orders_v1.parquet', f'{DATA}/orders_v2.parquet', key='order_id')\n"
             "print(diff.summary())\ndiff"),
    ("md", "## 3. Check a contract\n\nDraft one from v1, then check v2 against it with v1 as the baseline."),
    ("code", "contract = dp.Contract.infer(v1)\nprint(contract.to_yaml()[:600])"),
    ("code", "report = dp.check(f'{DATA}/orders_v2.parquet', contract, baseline=v1)\n"
             "print(report.status)\nfor r in report.failures + report.warnings:\n    print(f'{r.status:5} {r.label}: {r.message}')"),
    ("md", "## 4. Your own rule"),
    ("code", "@dp.rule('amount_under_1000')\ndef amount_under_1000(ctx):\n"
             "    n = ctx.count_where('amount >= 1000')\n    return dp.Outcome(passed=n == 0, observed=n, message=f'{n} large orders')\n\n"
             "dp.check(f'{DATA}/orders_v2.parquet', {'checks': [{'rule': 'amount_under_1000'}]}).results"),
]
nb = nbformat.v4.new_notebook()
nb.cells = [nbformat.v4.new_markdown_cell(src) if kind == "md" else nbformat.v4.new_code_cell(src) for kind, src in cells]
nb.metadata["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
NotebookClient(nb, timeout=300, kernel_name="python3", resources={"metadata": {"path": str(HERE)}}).execute()
nbformat.write(nb, HERE / "quickstart.ipynb")
print("wrote", HERE / "quickstart.ipynb")
