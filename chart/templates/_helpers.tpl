{{- define "orb-provider.validate" -}}
{{- if not (has .Values.cloud (list "gke" "eks" "aks")) }}{{ fail "cloud must be gke, eks or aks" }}{{ end }}
{{- $_ := required "amp.url is required (https://ampcode.com)" .Values.amp.url }}
{{- if not (or (hasPrefix "https://" .Values.amp.url) (hasPrefix "http://" .Values.amp.url)) }}{{ fail "amp.url must be an http(s) URL" }}{{ end }}
{{- if and .Release.IsInstall .Values.amp.token }}{{ fail "amp.token was removed: create the amp-orb-spawner Secret before installing (doc/self-hosted.md, Install)" }}{{ end }}
{{- $_ := required "snapshots.location is required" .Values.snapshots.location }}
{{- if eq .Values.cloud "eks" }}
{{- $_ := required "snapshots.eks.region is required" .Values.snapshots.eks.region }}
{{- $_ := required "snapshots.eks.ateletRoleArn is required" .Values.snapshots.eks.ateletRoleArn }}
{{- end }}
{{- if eq .Values.cloud "aks" }}
{{- $_ := required "snapshots.aks.storageAccount is required" .Values.snapshots.aks.storageAccount }}
{{- $_ := required "snapshots.aks.clientId is required" .Values.snapshots.aks.clientId }}
{{- end }}
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
{{- eq .Values.cloud "gke" | ternary "native" "agent" }}
{{- end }}

{{/*
Substrate API credentials (ServiceAccount token and trust bundle) as a projected volume source.
*/}}
{{- define "orb-provider.substrateVolume" -}}
projected:
  sources:
    - serviceAccountToken:
        path: token
        audience: api.ate-system.svc
        expirationSeconds: 3600
    {{- if eq (include "orb-provider.pkiDelivery" .) "agent" }}
    - configMap:
        name: podcert-trust-bundles
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
{{- list .Values.cloud .Values.images.substrate .Values.atelet .Values.snapshots | toJson | sha256sum }}
{{- end }}
