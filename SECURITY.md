# Security

Please report vulnerabilities privately through GitHub's "Report a vulnerability" (Security → Advisories) on this repository, not in public issues.

Scope notes:

- Fingerprints are integrity evidence, not signatures. A deliberately constructed collision is a documented limitation, not a vulnerability (see `docs/fingerprint-spec.md`).
- Raw data appearing in a passport or report made in the default `safe` privacy mode **is** in scope.
- Contracts can contain regular expressions and custom rules can run SQL. Treat contracts and plugins from untrusted sources like code.
