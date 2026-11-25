# Example plugin: `acme-dp`

Shows how a team packages its own rules and metrics.

```bash
uv pip install -e examples/plugin_example
datapassport contract rules        # lists no_lowercase, max_share_of_top_value
```

The entry point in `pyproject.toml` points at `acme_dp.rules`. DataPassport imports it on first use, and the `@dp.rule` / `@dp.metric` decorators register everything.

Without installing, pass the module on the command line instead: `PYTHONPATH=examples/plugin_example/src datapassport check data.csv -c contract.yml --plugin acme_dp.rules`.
