{{- define "orb-provider.validate" -}}
{{- if not (has .Values.cloud (list "gke" "eks" "aks" "onprem")) }}{{ fail "cloud must be gke, eks, aks or onprem" }}{{ end }}
{{- $_ := required "amp.url is required (https://ampcode.com)" .Values.amp.url }}
{{- if not (or (hasPrefix "https://" .Values.amp.url) (hasPrefix "http://" .Values.amp.url)) }}{{ fail "amp.url must be an http(s) URL" }}{{ end }}
{{- if and .Release.IsInstall .Values.amp.token }}{{ fail "amp.token was removed: create the amp-orb-spawner Secret before installing (doc/self-hosted.md, Install)" }}{{ end }}
{{- $_ := required "snapshots.location is required" .Values.snapshots.location }}
{{- if and .Values.substrate.enabled (eq .Values.cloud "eks") (not .Values.snapshots.s3.endpoint) }}
{{- $_ := required "snapshots.eks.region is required" .Values.snapshots.eks.region }}
{{- $_ := required "snapshots.eks.ateletRoleArn is required" .Values.snapshots.eks.ateletRoleArn }}
{{- end }}
{{- if and .Values.substrate.enabled (eq .Values.cloud "aks") (not .Values.snapshots.s3.endpoint) }}
{{- $_ := required "snapshots.aks.storageAccount is required" .Values.snapshots.aks.storageAccount }}
{{- $_ := required "snapshots.aks.clientId is required" .Values.snapshots.aks.clientId }}
{{- end }}
{{- if .Values.substrate.enabled }}
{{- if not .Values.postgres.enabled }}
{{- $_ := required "postgres.external.existingSecret is required when postgres.enabled=false" .Values.postgres.external.existingSecret }}
{{- $_ := required "postgres.external.caSecret is required when postgres.enabled=false" .Values.postgres.external.caSecret }}
{{- end }}
{{- if eq .Values.cloud "onprem" }}
{{- $_ := required "snapshots.s3.endpoint is required for bundled onprem runtime" .Values.snapshots.s3.endpoint }}
{{- end }}
{{- else }}
{{- $_ := required "substrate.external.apiAddress is required" .Values.substrate.external.apiAddress }}
{{- $_ := required "substrate.external.routerAddress is required" .Values.substrate.external.routerAddress }}
{{- if .Values.substrate.authentication.inClusterJWKS }}{{ fail "inClusterJWKS requires substrate.enabled=true; configure the external runtime separately" }}{{ end }}
{{- end }}
{{- if .Values.snapshots.s3.endpoint }}
{{- $_ := required "snapshots.s3.region is required" .Values.snapshots.s3.region }}
{{- $_ := required "snapshots.s3.existingSecret is required" .Values.snapshots.s3.existingSecret }}
{{- end }}
{{- $high := int (get .Values.atelet.imageCache "highPercent" | default 85) }}
{{- $low := 80 }}{{- if hasKey .Values.atelet.imageCache "lowPercent" }}{{- $low = int .Values.atelet.imageCache.lowPercent }}{{- end }}
{{- if ge $low $high }}{{ fail "atelet.imageCache.lowPercent must be below highPercent (defaults: 80/85)" }}{{ end }}
{{- $_ := required "images.registry is required (the registry the release images are pulled from)" .Values.images.registry }}
{{- if contains "://" .Values.images.registry }}{{ fail "images.registry is a registry host and path, not a URL" }}{{ end }}
{{- range $name, $image := dict "spawner" .Values.images.spawner "provider" .Values.images.provider "orbd" .Values.images.orbd "sandbox" .Values.images.sandbox }}
{{- if not (contains "@sha256:" $image) }}{{ fail (printf "images.%s must be a digest-pinned image, got %q" $name $image) }}{{ end }}
{{- end }}
{{- range $name, $image := .Values.images.substrate }}
{{- if not (contains "@sha256:" $image) }}{{ fail (printf "images.substrate.%s must be a digest-pinned image, got %q" $name $image) }}{{ end }}
{{- end }}
{{- end }}

{{/*
Pull reference of a release image. Takes (list $ <images.* value>). A value whose first path
segment is not a registry host (no "." or ":", not "localhost"), or that has no path at all, is
<images.registry>/<value>; a value with its own host is returned as is. Same rule as Docker's.
*/}}
{{- define "orb-provider.image" -}}
{{- $root := index . 0 }}
{{- $image := index . 1 }}
{{- $segments := splitList "/" $image }}
{{- $first := index $segments 0 }}
{{- if or (eq (len $segments) 1) (not (or (contains "." $first) (contains ":" $first) (eq $first "localhost"))) }}
{{- printf "%s/%s" (trimSuffix "/" $root.Values.images.registry) $image }}
{{- else }}
{{- $image }}
{{- end }}
{{- end }}

{{/* Fetches the given path from inside the provider container (it binds loopback). Renders as a JSON list. */}}
{{- define "orb-provider.probe" -}}
{{- list "node" "-e" (printf "fetch('http://127.0.0.1:8080%s').then(function (r) { process.exit(r.ok ? 0 : 1) }, function () { process.exit(1) })" .) | toJson }}
{{- end }}

{{/* GKE serves certificates.k8s.io/v1beta1 natively; EKS and AKS get them from the podcert-agent sidecar. */}}
{{- define "orb-provider.pkiDelivery" -}}
{{- if not .Values.substrate.enabled }}
{{- .Values.substrate.external.pkiDelivery }}
{{- else }}
{{- eq .Values.cloud "gke" | ternary "native" "agent" }}
{{- end }}
{{- end }}

{{/*
Substrate API credentials (ServiceAccount token and trust bundle) as a projected volume source.
*/}}
{{- define "orb-provider.substrateVolume" -}}
projected:
  sources:
    - serviceAccountToken:
        path: token
        audience: {{ include "orb-provider.apiAudience" . | quote }}
        expirationSeconds: 3600
    {{- if eq (include "orb-provider.pkiDelivery" .) "agent" }}
    - configMap:
        name: {{ include "orb-provider.trustBundleConfigMap" . | quote }}
        items:
          - key: servicedns.podcert.ate.dev-identity.pem
            path: trust-bundle.pem
    {{- else }}
    - clusterTrustBundle:
        signerName: servicedns.podcert.ate.dev/identity
        labelSelector:
          matchLabels:
            podcert.ate.dev/canarying: live
        path: trust-bundle.pem
    {{- end }}
{{- end }}

{{/*
Digest of the values that roll Substrate itself; provider/upgrade.yaml runs when it changes.
*/}}
{{- define "orb-provider.substrateRevision" -}}
{{- $atelet := deepCopy .Values.atelet }}
{{- if empty $atelet.imageCache }}{{- $_ := unset $atelet "imageCache" }}{{- end }}
{{- $snapshots := deepCopy .Values.snapshots }}
{{- if not $snapshots.s3.endpoint }}{{- $_ := unset $snapshots "s3" }}{{- end }}
{{- $parts := list .Values.cloud .Values.images.substrate $atelet $snapshots }}
{{- if or (not .Values.postgres.enabled) .Values.substrate.authentication.inClusterJWKS }}
{{- $parts = append $parts (dict "postgres" .Values.postgres "authentication" .Values.substrate.authentication) }}
{{- end }}
{{- $parts | toJson | sha256sum }}
{{- end }}

{{- define "orb-provider.apiAudience" -}}
{{- if .Values.substrate.enabled }}api.ate-system.svc{{ else }}{{ .Values.substrate.external.audience }}{{ end -}}
{{- end }}

{{- define "orb-provider.s3Env" -}}
- name: ATE_STORAGE_BACKEND
  value: s3
- name: AWS_REGION
  value: {{ .Values.snapshots.s3.region | quote }}
- name: AWS_ENDPOINT_URL
  value: {{ .Values.snapshots.s3.endpoint | quote }}
- name: AWS_S3_USE_PATH_STYLE
  value: {{ .Values.snapshots.s3.forcePathStyle | quote }}
- name: AWS_EC2_METADATA_DISABLED
  value: 'true'
{{- end }}

{{- define "orb-provider.imageCacheArgs" -}}
{{- if hasKey .Values.atelet.imageCache "maxBytes" }}
- --image-cache-max-bytes={{ .Values.atelet.imageCache.maxBytes | int64 }}
{{- end }}
{{- if hasKey .Values.atelet.imageCache "highPercent" }}
- --image-cache-high-percent={{ .Values.atelet.imageCache.highPercent }}
{{- end }}
{{- if hasKey .Values.atelet.imageCache "lowPercent" }}
- --image-cache-low-percent={{ .Values.atelet.imageCache.lowPercent }}
{{- end }}
{{- if hasKey .Values.atelet.imageCache "gcPeriod" }}
- --image-cache-gc-period={{ .Values.atelet.imageCache.gcPeriod }}
{{- end }}
{{- end }}

{{- define "orb-provider.trustBundleConfigMap" -}}
{{- if .Values.substrate.enabled }}podcert-trust-bundles{{ else }}{{ .Values.substrate.external.trustBundleConfigMap }}{{ end -}}
{{- end }}
