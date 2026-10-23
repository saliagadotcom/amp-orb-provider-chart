# Talos: start here

Use this for a new installation. **Do not install over an existing runtime or
switch an existing release's database in place.** Plan that migration separately.

## Before installing

1. Use Kubernetes with enforced NetworkPolicy and the APIs required by the pinned Substrate release. The reference deployment used Talos 1.14.2 / Kubernetes 1.37.1.
2. Prefer dedicated worker nodes. Merge [node settings](../examples/talos-node-patch.yaml) into your Talos or Omni configuration; preserve existing CSI labels.
3. Review and apply [namespace admission settings](../examples/talos-namespaces.yaml). The example release namespace is `amp-orbs`; runtime namespaces retain upstream names.
4. Provision PostgreSQL, an S3-compatible bucket, and the Secrets below. CNPG, Silo, 1Password, and Argo CD are optional external tools, not chart dependencies.
5. Copy [Talos values](../examples/talos-values.yaml). Replace the endpoint, bucket, region, and Secret names.

## Existing Secrets

The chart accepts Secret **names**, never raw credentials in values.

| Secret in the example | Namespace | Required keys |
| --- | --- | --- |
| `amp-orb-spawner` | `amp-orbs` | `AMP_ORB_PROVIDER_TOKEN` |
| `orb-database` | `amp-orbs` | Five connection keys below |
| `orb-database-ca` | `ate-system` | `ca.crt` |
| `orb-storage` | `ate-system` | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` |

Database connection keys:

```text
ATE_API_POSTGRES_OWNER_CONNECTION_STRING
ATE_API_POSTGRES_READ_WRITE_CONNECTION_STRING
ATE_API_POSTGRES_OWNER_ROLE
ATE_API_POSTGRES_READ_WRITE_ROLE
ATE_API_POSTGRES_SCHEMA
```

Use separate owner/runtime login users and roles. Provision the schema and grants
before startup; the API applies migrations through the owner connection. Follow
[Substrate's pinned database contract](https://github.com/agent-substrate/substrate/blob/7ace5f76f03bfc3d0d4a5867cc78ecf8591dcbd0/docs/postgres.md).

Both DSNs should use `sslmode=verify-full` and
`sslrootcert=/run/postgres-server-ca/server-ca.pem`. URL-encode passwords in DSNs.
The bootstrap reads the connection Secret from the release namespace and writes
the API's generated connection Secret into `ate-system`.

The S3 identity needs bucket list/location, object read/write/copy/delete, and
multipart permissions. Keep the bucket private. The `gs://` snapshot location
syntax also applies to S3; the bucket name must match the S3 bucket.

## Install and check

```sh
helm lint chart -f examples/talos-values.yaml
helm template amp-orbs chart -n amp-orbs -f examples/talos-values.yaml
helm upgrade --install amp-orbs ./chart -n amp-orbs \
  -f examples/talos-values.yaml --wait --timeout 15m
```

Start with one disposable Orb. Check launch, a file write, pause/resume, file
contents, and deletion. Watch node disk space throughout.

The reference runtime passed launch/pause/resume/deletion on Talos. This generic
public chart is a new packaging path: local rendering and mocked bootstrap tests
are not a live installation test. Back up PostgreSQL and snapshots before upgrades.

## Limits that matter

- Orb sizes default to upstream's 16 CPU / 32 GiB. The example opts into 2 CPU / 4 GiB, plus 1 GiB worker overhead.
- Zero warm workers is a target; idle workers can remain during the scale-down grace period.
- Cache stays at `/var/lib/ate` on each node. `maxBytes` evicts unused image layers; it does not cap active Orbs or all runtime assets.
- The example's 20 GiB / 75% / 65% settings are a starting point. Choose a disk budget and monitoring for your nodes.
- `inClusterJWKS` uses the projected Kubernetes CA/token. It preserves issuer and audience checks. Custom JSON authentication settings are preserved; unrecognized custom YAML fails closed.

## Existing Substrate

Set `substrate.enabled: false` using the [external example](../examples/external-substrate-values.yaml).
Use the matching Substrate release in this cluster. Configure its storage, database,
JWT keys, and certificate issuer separately. Authorize the provider's SPIFFE identity
in its router: `spiffe://cluster.local/ns/amp-orbs/sa/amp-orb-provider`.

Provider RBAC, WorkerPool, PDB, and provider ingress policies remain chart-managed.
Static upstream CRDs stay in `crds/`; use Helm's `--skip-crds` if another installation
owns them. Disabling bundled Substrate does not migrate or preserve resources from
a previous bundled release automatically.

## Argo CD

Use a full sync with hooks. Apply-only or selective sync can skip bootstrap.
When enabling `inClusterJWKS`, preserve the API pod annotation
`substrate.ate.dev/authentication-sha256` with a narrowly scoped `ignoreDifferences`
and `RespectIgnoreDifferences=true`. Argo configuration stays outside the chart.
