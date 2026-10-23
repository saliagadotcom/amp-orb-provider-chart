# Changelog

## 0.20261021.1930-onprem.1

Added opt-in on-premises/Talos configuration, external PostgreSQL and S3-compatible
storage, external Substrate endpoints, in-cluster JWT key retrieval, and cache controls.

**Existing cloud values keep their resource behavior.** No runtime image changes.
No migration is needed for existing defaults. Upgrade with your values file or
`--reset-then-reuse-values` so Helm loads the new default settings; avoid
`--reuse-values` alone on this first upgrade. Switching dependency ownership or
storage backends requires a separate migration plan.

Includes concise Talos/security guides and compatibility tests. The public chart's
new installation path has not yet been exercised on a live cluster.

## Upstream baseline

Unmodified import of Amp chart `0.20261021.1930`: commit `0794e6e`.
