# Security notes

## Certificate agents

On-premises mode reuses Amp's existing certificate-agent path. Projected,
audience-scoped service-account tokens obtain component certificates. Mutual TLS
remains enabled. The helper image stays digest-pinned.

A stolen pod token or private key can enable component impersonation. The
certificate issuer and its signing-key Secrets are sensitive infrastructure.
Restrict access to them and keep runtime images updated as a matched release.

## Talos node changes

- User namespaces must be enabled for gVisor.
- Runtime namespaces need admission rules permitting host paths and capabilities. This does not make every container privileged.
- `/var/lib/ate` is writable node-local runtime storage.
- Dedicated workers reduce the impact of a runtime escape on other workloads and control planes.

## Signing keys and credentials

In-cluster JWKS changes the key-fetch address, not the trusted issuer. HTTPS
certificate validation, JWT signature checks, issuer, and audience remain enforced.
Bootstrap fails if discovery or configuration fails. Unrecognized authentication
YAML and mismatched issuers are refused rather than silently replaced.

Keep provider tokens, database DSNs, and S3 keys in Secrets. Rotate credentials
with a controlled rollout; Secret updates alone may not restart consumers.
For S3, prefer HTTPS. Plain HTTP endpoints carry storage traffic without TLS.

## What tests prove

Compatibility and failure tests cover rendered manifests and bootstrap logic.
They do not constitute a security audit or prove protection against sandbox escapes.
