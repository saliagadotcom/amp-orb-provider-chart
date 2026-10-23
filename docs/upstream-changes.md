# Changes from Amp's chart

Baseline: `0794e6e`, upstream `0.20261021.1930`.

| Area | Opt-in change | Existing behavior |
| --- | --- | --- |
| Platform | `cloud: onprem` reuses the agent-based runtime | GKE/EKS/AKS resource renders preserved |
| Substrate | `substrate.enabled: false` uses existing endpoints | Bundled runtime stays enabled |
| PostgreSQL | `postgres.enabled: false` reads external connection/CA Secrets | Bundled PostgreSQL stays enabled |
| Snapshots | `snapshots.s3` adds endpoint, region, path style, and Secret | Cloud storage defaults preserved |
| Authentication | `substrate.authentication.inClusterJWKS` uses trusted in-cluster keys | Original discovery remains default |
| Cache | `atelet.imageCache` exposes eviction controls | Upstream defaults remain unset |

Provider/runtime images, default Orb size, warm targets, mTLS, and runtime host
cache paths are retained. No operators, Argo Applications, or private deployment
settings are installed by the chart.

Tests compare all parsed cloud resources with the baseline and exercise opt-in
combinations, validation failures, and authentication helper behavior.
