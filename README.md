# amp-orb-provider-chart

Unofficial Amp self-hosted Orbs chart with optional on-premises support.

**Existing GKE, EKS, and AKS defaults are preserved. Talos settings are opt-in.**

## Choose a path

| Setup | Start here |
| --- | --- |
| Existing cloud deployment | Keep your values; use [Amp's guide](https://ampcode.com/docs/orbs/self-hosted/kubernetes) |
| Talos + external PostgreSQL/S3 | [Talos guide](docs/talos.md) · [example values](examples/talos-values.yaml) |
| Existing Substrate installation | [example values](examples/external-substrate-values.yaml) |

The chart keeps its upstream package name, `chart`. The adaptation version is
`0.20261021.1930-onprem.1`; runtime images stay pinned to the upstream release.

## What's added

- `cloud: onprem`: certificate agents, without cloud identity or host credential-provider requirements.
- Optional external PostgreSQL, S3-compatible storage, and existing Substrate.
- Optional in-cluster JWT signing-key discovery and image-cache eviction settings.

For upgrades, keep your values file or use `--reset-then-reuse-values` to load new defaults.

Read [changes](CHANGELOG.md), [security notes](docs/security.md), or the
[upstream change map](docs/upstream-changes.md).

## Check locally

Requires a full Git checkout, Helm 3.14+, Python 3, Node.js, and `uv`.

```sh
uv run --with pyyaml python -m unittest discover -s tests -v
helm lint chart -f examples/talos-values.yaml
helm template amp-orbs chart -n amp-orbs -f examples/talos-values.yaml
```

Tests compare parsed cloud resources against the untouched baseline commit.
Render checks do not prove a successful installation. The public chart has not
been installed over an existing production release; see the Talos guide for limits.

## Upstream provenance

| Field | Value |
| --- | --- |
| Publisher | Amp |
| Chart | `chart` |
| Version | `0.20261021.1930` |
| App version | `bfdfc50-7ace5f7` |
| OCI source | `oci://us-central1-docker.pkg.dev/amp-prod-0/orb-provider/chart` |
| OCI manifest digest | `sha256:701785c1f98ea5b1599d77cbf10d54e525fbaf0065461137e818f7a9e79095c4` |
| Original archive SHA-256 | `da744430e52f4f5ace601a3a5d01372b2433f4bd83546bc8dcf0145dba395765` |
| Original download date | 2026-10-22 |

The baseline commit's 18 chart files matched that archive byte-for-byte.
Current adaptations are listed in the change map. The archive and generated
deployment manifests are not committed.

The untouched import is [commit 0794e6e](https://github.com/saliagadotcom/amp-orb-provider-chart/commit/0794e6e65eb00100cad7d888051a6ca96588f9b0).
Current changes are kept in a separate adaptation commit.

## Licensing and attribution

The original chart archive includes no `LICENSE` or `NOTICE` file, and its chart
metadata specifies no license. No chart-specific redistribution grant was found
in the official deployment guide during this import. Upstream licensing remains
unspecified here; this repository does not assign a license to Amp's material.
Consult Amp for applicable reuse and redistribution terms. Substrate's separate
open-source license should not be assumed to cover the complete Amp chart.

Amp names and image references are retained for provenance and compatibility.
This repository is not an official Amp project and is not endorsed by Amp.
