# Distribution and adoption

DataPassport helps people who ship CSV and Parquet files record what they delivered and explain what changed before the next file reaches production. Start with data engineers reviewing extract changes in CI and Python pipeline authors. Analysts and maintainers of downloadable datasets can use the same reports without a pipeline or hosted account.

## Demand and alternatives

- An Arrow user reported losing order when writing partitioned datasets. This is a concrete reason to compare data by content without relying on row order. [Apache Arrow issue #39030](https://github.com/apache/arrow/issues/39030)
- Datafold archived its open-source data-diff repository. Reladiff continues the cross-database comparison workflow, and ParquetKit documents comparing Parquet content with DuckDB. DataPassport's narrower proposition is a saved, versioned identity and summary that still supports later checks after the original file is gone. [data-diff](https://github.com/datafold/data-diff), [Reladiff](https://github.com/erezsh/reladiff), [ParquetKit](https://parquetkit.com/docs/check-if-two-parquet-files-are-identical)
- csvdb already documents format-independent checksums. A stable hash alone is insufficient differentiation. The first successful run should produce a passport, explain one change, and stop a bad update with a contract. [csvdb](https://github.com/jeff-gorelick/csvdb)

These sources show established workflows and competing tools. They give no evidence of DataPassport adoption. Validate the workflow with independent operators before investing in more connectors. The [technical research](research.md) explains the choice of DuckDB, privacy defaults and fingerprint format.

## Release path

1. Build the wheel and source distribution. Install the wheel outside the checkout and run `inspect`, `verify` and `check` on the same generated fixture. Check the compatibility matrix before promising Python or operating-system support.
2. Run the GitHub Actions matrix and the local composite action. Use repository topics `data-quality`, `data-contracts`, `parquet`, `duckdb` and `data-diff`.
3. Use GitHub Releases for changelogs and attached artifacts, and PyPI for Python and CLI discovery. PyPI returned no project page for `datapassport` on 25 November 2026. That checks current visibility. Reservation, moderation and publisher ownership still require confirmation before release.
4. Configure the protected `pypi` environment and PyPI Trusted Publishing, and confirm the project name before creating a public release. The workflow runs publishing when a release is published. Verify the uploaded version and install it by exact version in a fresh environment.
5. Publish a short technical walkthrough alongside the CLI and rendered sample. Keep Homebrew and container packaging off the first-release path.

## Launch drafts

**Show HN title** — Show HN: DataPassport, a portable fingerprint and change report for datasets

**Show HN body** — I built DataPassport for a common review problem: you receive an updated CSV or Parquet file and need to tell whether its contents changed. It writes a small record of the dataset and can compare a new version with that record later. The sample shows a change a checksum can't explain: the incoming file adds rows, renames a column and introduces an unexpected status. I’d like to hear how people review those changes today.

**Data engineering discussion** — How do you review recurring CSV or Parquet extracts when the previous file is no longer around? I’m developing a local CLI that keeps a fingerprint and enough column statistics to flag changes later. The contract example shows what gets blocked and why. I’m interested in real examples where a saved summary would have helped.

Include the install, quick-start and rendered sample links once those exist. Check the posting channel’s current rules and get approval before posting.

## Milestones and measurement

| Milestone | Evidence and action |
| --- | --- |
| First release and ten independent users | Observe clean installs and first runs with users who have a recurring extract. Collect anonymous task outcomes and user-reported friction by consent. |
| 100 stars and first external contributor | Publish a verified migration walkthrough, turn repeat feedback into focused issues, and track stars separately from completed installs or contributions. |
| First third-party integration | Look for a downstream repository that consumes generated passports or calls the CLI in CI. Verify from its code and ask the maintainer what could be removed or improved. |
| 1,000 stars and sustained maintenance | Watch downloads, release upgrades, documented integrations, external issue reporters and contributor activity. Keep versioning and regression tests current. Treat stars as a visibility signal. |

Use public GitHub and PyPI counters and firsthand consented feedback. The CLI and reports require no telemetry. Early contribution tasks include an interoperable schema example, a real-world sanitized schema-change fixture and a platform-specific install report.
