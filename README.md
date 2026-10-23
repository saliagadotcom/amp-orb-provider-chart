# amp-orb-provider-chart

Unofficial mirror of Amp's self-hosted Orbs Helm chart.

This initial commit contains the unchanged upstream chart in `chart/`. The chart
still installs the Amp provider and its bundled Substrate runtime for GKE, EKS,
and AKS. Talos adaptations and other local changes are not included in this baseline.

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

Every file under `chart/` was checked byte-for-byte against that original archive.
The archive itself and generated deployment manifests are not committed.

Fetch the pinned upstream package directly:

```sh
helm pull oci://us-central1-docker.pkg.dev/amp-prod-0/orb-provider/chart \
  --version 0.20261021.1930
```

For platform prerequisites and installation, use Amp's
[official Kubernetes deployment guide](https://ampcode.com/docs/orbs/self-hosted/kubernetes).
The retained upstream defaults require platform-specific settings and credentials;
this repository does not configure or deploy a cluster.

## Licensing and attribution

The original chart archive includes no `LICENSE` or `NOTICE` file, and its chart
metadata specifies no license. No chart-specific redistribution grant was found
in the official deployment guide during this import. Upstream licensing remains
unspecified here; this repository does not assign a license to Amp's material.
Consult Amp for applicable reuse and redistribution terms. Substrate's separate
open-source license should not be assumed to cover the complete Amp chart.

Amp names and image references are retained for provenance and compatibility.
This repository is not an official Amp project and is not endorsed by Amp.
