"""Behavior and compatibility checks for the public Helm chart."""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path
from typing import Any, Iterable

import yaml


ROOT = Path(__file__).resolve().parents[1]
CHART = ROOT / "chart"
BASELINE_COMMIT = "0794e6e65eb00100cad7d888051a6ca96588f9b0"
RELEASE_NAME = "amp-orb-provider"
RELEASE_NAMESPACE = "orb-provider"
EXTERNAL_POSTGRES_KEYS = {
    "ATE_API_POSTGRES_OWNER_CONNECTION_STRING",
    "ATE_API_POSTGRES_READ_WRITE_CONNECTION_STRING",
    "ATE_API_POSTGRES_OWNER_ROLE",
    "ATE_API_POSTGRES_READ_WRITE_ROLE",
    "ATE_API_POSTGRES_SCHEMA",
}


def valid_values(cloud: str = "gke") -> dict[str, Any]:
    """Return the smallest old-chart values override that renders a valid release."""
    values: dict[str, Any] = {
        "cloud": cloud,
        "snapshots": {"location": "gs://test-bucket/amp-orbs"},
    }
    if cloud == "eks":
        values["snapshots"]["eks"] = {
            "region": "us-west-2",
            "ateletRoleArn": "arn:aws:iam::123456789012:role/amp-orbs-test",
        }
    elif cloud == "aks":
        values["snapshots"]["aks"] = {
            "storageAccount": "amporbstest",
            "clientId": "00000000-0000-0000-0000-000000000001",
        }
    return values


def merge_values(*values: dict[str, Any]) -> dict[str, Any]:
    """Build nested Helm values without mutating the input mappings."""
    result: dict[str, Any] = {}
    for override in values:
        for key, value in override.items():
            if isinstance(value, dict) and isinstance(result.get(key), dict):
                result[key] = merge_values(result[key], value)
            elif isinstance(value, dict):
                result[key] = merge_values(value)
            else:
                result[key] = value
    return result


def resource_identity(resource: dict[str, Any]) -> tuple[str, str, str, str]:
    metadata = resource.get("metadata") or {}
    return (
        resource.get("apiVersion", ""),
        resource.get("kind", ""),
        metadata.get("namespace", ""),
        metadata.get("name", metadata.get("generateName", "")),
    )


def resources_by_identity(documents: Iterable[dict[str, Any]]) -> dict[tuple[str, str, str, str], dict[str, Any]]:
    resources: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for document in documents:
        identity = resource_identity(document)
        if identity in resources:
            raise AssertionError(f"duplicate rendered resource identity: {identity}")
        resources[identity] = document
    return resources


def get_resource(
    resources: dict[tuple[str, str, str, str], dict[str, Any]],
    kind: str,
    name: str,
    namespace: str | None = None,
) -> dict[str, Any]:
    matches = [
        resource
        for identity, resource in resources.items()
        if identity[1] == kind
        and identity[3] == name
        and (namespace is None or identity[2] == namespace)
    ]
    if len(matches) != 1:
        raise AssertionError(
            f"expected one {kind}/{name} resource in namespace {namespace!r}, found {len(matches)}"
        )
    return matches[0]


def pod_spec(resource: dict[str, Any]) -> dict[str, Any]:
    if resource["kind"] == "Pod":
        return resource["spec"]
    return resource["spec"]["template"]["spec"]


def container_named(pod: dict[str, Any], name: str, section: str = "containers") -> dict[str, Any]:
    matches = [container for container in pod.get(section, []) if container.get("name") == name]
    if len(matches) != 1:
        raise AssertionError(f"expected one {section} entry named {name!r}, found {len(matches)}")
    return matches[0]


def env_values(container: dict[str, Any]) -> dict[str, Any]:
    return {entry["name"]: entry.get("value") for entry in container.get("env", [])}


def secret_references(container: dict[str, Any]) -> set[str]:
    """Return direct Secret refs from a container's env and envFrom entries."""
    references: set[str] = set()
    for entry in container.get("env", []):
        name = entry.get("valueFrom", {}).get("secretKeyRef", {}).get("name")
        if name:
            references.add(name)
    for entry in container.get("envFrom", []):
        name = entry.get("secretRef", {}).get("name")
        if name:
            references.add(name)
    return references


def extract_baseline_chart(destination: Path) -> Path:
    """Extract the original public baseline chart from this repository's Git history."""
    archive = subprocess.run(
        ["git", "archive", "--format=tar", BASELINE_COMMIT, "chart"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    with tarfile.open(fileobj=io.BytesIO(archive.stdout), mode="r:") as tar:
        for member in tar.getmembers():
            relative = Path(member.name)
            if relative.is_absolute() or ".." in relative.parts:
                raise AssertionError(f"unsafe path in baseline Git archive: {member.name}")
            target = destination / relative
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                source = tar.extractfile(member)
                if source is None:
                    raise AssertionError(f"could not read baseline file {member.name}")
                target.write_bytes(source.read())
            else:
                raise AssertionError(f"unexpected non-file in baseline chart archive: {member.name}")
    return destination / "chart"


class HelmChartTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if shutil.which("helm") is None:
            raise unittest.SkipTest("Helm is required to render the chart")

    def render_result(
        self,
        values: dict[str, Any],
        chart_path: Path = CHART,
        *,
        include_crds: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory(prefix="amp-orb-chart-values-") as temporary_directory:
            values_path = Path(temporary_directory) / "values.yaml"
            values_path.write_text(yaml.safe_dump(values, sort_keys=False), encoding="utf-8")
            command = [
                "helm",
                "template",
                RELEASE_NAME,
                str(chart_path),
                "--namespace",
                RELEASE_NAMESPACE,
                "--values",
                str(values_path),
            ]
            if include_crds:
                command.append("--include-crds")
            return subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)

    def render(self, values: dict[str, Any], chart_path: Path = CHART) -> list[dict[str, Any]]:
        result = self.render_result(values, chart_path)
        self.assertEqual(
            result.returncode,
            0,
            f"helm template failed:\n{result.stderr}\n{result.stdout}",
        )
        return [document for document in yaml.safe_load_all(result.stdout) if document]

    def assert_render_fails(self, values: dict[str, Any], expected_error: str | None = None) -> None:
        result = self.render_result(values)
        self.assertNotEqual(result.returncode, 0, "helm template unexpectedly accepted invalid values")
        if expected_error:
            self.assertIn(expected_error, result.stderr + result.stdout)


class BaselineCompatibilityTests(HelmChartTestCase):
    def test_default_valid_cloud_renders_match_the_original_chart_exactly(self) -> None:
        """Keep every default rendered object, including hooks and CRDs, byte-semantic equal."""
        with tempfile.TemporaryDirectory(prefix="amp-orb-baseline-") as temporary_directory:
            baseline_chart = extract_baseline_chart(Path(temporary_directory))
            for cloud in ("gke", "eks", "aks"):
                with self.subTest(cloud=cloud):
                    overrides = valid_values(cloud)
                    old = resources_by_identity(self.render(overrides, baseline_chart))
                    new = resources_by_identity(self.render(overrides))
                    self.assertEqual(new.keys(), old.keys(), f"rendered identities changed for {cloud}")
                    for identity, old_resource in old.items():
                        self.assertEqual(
                            new[identity],
                            old_resource,
                            f"render changed {identity} for default {cloud} configuration",
                        )


class NewConfigurationTests(HelmChartTestCase):
    def test_default_values_preserve_worker_sizing_and_add_external_runtime_defaults(self) -> None:
        values = yaml.safe_load((CHART / "values.yaml").read_text(encoding="utf-8"))
        self.assertEqual(values["workers"]["sandbox"], {"cpu": 16, "memoryGi": 32})
        self.assertEqual(values["workers"]["warm"], 2)
        self.assertEqual(values["workers"]["min"], 1)
        self.assertIs(values["substrate"]["enabled"], True)
        self.assertEqual(values["substrate"]["external"], {
            "apiAddress": "api.ate-system.svc:443",
            "routerAddress": "atenet-router.ate-system.svc:443",
            "audience": "api.ate-system.svc",
            "pkiDelivery": "agent",
            "trustBundleConfigMap": "podcert-trust-bundles",
        })
        self.assertIs(values["postgres"]["enabled"], True)
        self.assertEqual(values["snapshots"]["s3"]["endpoint"], "")
        self.assertEqual(values["snapshots"]["s3"]["forcePathStyle"], True)
        self.assertEqual(values["atelet"]["imageCache"], {})

        resources = resources_by_identity(self.render(valid_values("gke")))
        pool = get_resource(resources, "WorkerPool", "amp-orbs", RELEASE_NAMESPACE)
        self.assertEqual(pool["spec"]["template"]["resources"]["limits"]["cpu"], "16")
        self.assertEqual(pool["spec"]["template"]["resources"]["limits"]["memory"], "33Gi")
        provider = get_resource(resources, "Deployment", "amp-orb-provider", RELEASE_NAMESPACE)
        environment = env_values(container_named(pod_spec(provider), "provider"))
        self.assertEqual(environment["SANDBOX_CPU"], "16")
        self.assertEqual(environment["SANDBOX_MEMORY_GI"], "32")
        self.assertEqual(environment["SUBSTRATE_WORKERS_MIN"], "1")
        self.assertEqual(environment["SUBSTRATE_WORKERS_WARM"], "2")

    def test_substrate_disabled_keeps_provider_resources_and_omits_runtime_and_hooks(self) -> None:
        values = merge_values(
            valid_values("onprem"),
            {"substrate": {"enabled": False}},
        )
        resources = resources_by_identity(self.render(values))
        get_resource(resources, "Deployment", "amp-orb-provider", RELEASE_NAMESPACE)
        get_resource(resources, "WorkerPool", "amp-orbs", RELEASE_NAMESPACE)
        get_resource(resources, "PodDisruptionBudget", "amp-orbs-busy-workers", RELEASE_NAMESPACE)
        get_resource(resources, "Role", "amp-orb-provider", RELEASE_NAMESPACE)
        get_resource(resources, "RoleBinding", "amp-orb-provider", RELEASE_NAMESPACE)
        get_resource(resources, "ClusterRole", "amp-orb-provider-nodes")
        get_resource(resources, "ClusterRoleBinding", "amp-orb-provider-nodes")
        get_resource(resources, "NetworkPolicy", "amp-orb-provider-only", "ate-system")
        get_resource(resources, "NetworkPolicy", "amp-orb-provider-api-access", "ate-system")

        self.assertFalse(
            any(identity[2] == "ate-system" and identity[1] != "NetworkPolicy" for identity in resources),
            "external-runtime mode should omit bundled Substrate resources and cloud configuration",
        )
        self.assertFalse(
            any(
                (resource.get("metadata", {}).get("annotations") or {}).get("helm.sh/hook")
                for resource in resources.values()
            ),
            "external-runtime mode should omit bootstrap and pause hooks",
        )
        crd_names = {
            identity[3]
            for identity in resources
            if identity[1] == "CustomResourceDefinition"
        }
        self.assertEqual(
            crd_names,
            {"workerpools.ate.dev", "csidriverconfigs.ate.dev", "sandboxconfigs.ate.dev"},
            "Helm's static chart CRDs remain included with --include-crds",
        )

    def test_external_runtime_defaults_and_overrides_are_used_by_provider(self) -> None:
        values = merge_values(
            valid_values("onprem"),
            {"substrate": {"enabled": False}},
        )
        resources = resources_by_identity(self.render(values))
        provider = get_resource(resources, "Deployment", "amp-orb-provider", RELEASE_NAMESPACE)
        pod = pod_spec(provider)
        main = container_named(pod, "provider")
        environment = env_values(main)
        self.assertEqual(environment["SUBSTRATE_API_ADDRESS"], "api.ate-system.svc:443")
        self.assertEqual(environment["SUBSTRATE_ROUTER_ADDRESS"], "atenet-router.ate-system.svc:443")
        projected = next(volume["projected"] for volume in pod["volumes"] if volume["name"] == "substrate")
        token = next(source["serviceAccountToken"] for source in projected["sources"] if "serviceAccountToken" in source)
        self.assertEqual(token["audience"], "api.ate-system.svc")
        trust = next(volume["configMap"] for volume in pod["volumes"] if volume["name"] == "podcert-trust")
        self.assertEqual(trust["name"], "podcert-trust-bundles")
        container_named(pod, "podcert-agent", "initContainers")

        overrides = merge_values(
            values,
            {
                "substrate": {
                    "external": {
                        "apiAddress": "api.external.example:7443",
                        "routerAddress": "router.external.example:7443",
                        "audience": "external-api.example",
                        "trustBundleConfigMap": "external-trust",
                    }
                }
            },
        )
        overridden = resources_by_identity(self.render(overrides))
        pod = pod_spec(get_resource(overridden, "Deployment", "amp-orb-provider", RELEASE_NAMESPACE))
        environment = env_values(container_named(pod, "provider"))
        self.assertEqual(environment["SUBSTRATE_API_ADDRESS"], "api.external.example:7443")
        self.assertEqual(environment["SUBSTRATE_ROUTER_ADDRESS"], "router.external.example:7443")
        projected = next(volume["projected"] for volume in pod["volumes"] if volume["name"] == "substrate")
        token = next(source["serviceAccountToken"] for source in projected["sources"] if "serviceAccountToken" in source)
        self.assertEqual(token["audience"], "external-api.example")
        trust = next(volume["configMap"] for volume in pod["volumes"] if volume["name"] == "podcert-trust")
        self.assertEqual(trust["name"], "external-trust")

    def test_bundled_onprem_ignores_external_runtime_overrides(self) -> None:
        values = merge_values(
            valid_values("onprem"),
            {
                "snapshots": {"s3": {
                    "endpoint": "https://s3.example.test",
                    "region": "us-west-2",
                    "existingSecret": "amp-s3-credentials",
                }},
                "substrate": {"external": {
                    "apiAddress": "wrong-api.example:9443",
                    "routerAddress": "wrong-router.example:9443",
                    "audience": "wrong-audience.example",
                    "pkiDelivery": "native",
                    "trustBundleConfigMap": "wrong-trust-bundles",
                }},
            },
        )
        resources = resources_by_identity(self.render(values))
        provider = get_resource(resources, "Deployment", "amp-orb-provider", RELEASE_NAMESPACE)
        pod = pod_spec(provider)
        environment = env_values(container_named(pod, "provider"))
        self.assertEqual(environment["SUBSTRATE_API_ADDRESS"], "api.ate-system.svc:443")
        self.assertEqual(environment["SUBSTRATE_ROUTER_ADDRESS"], "atenet-router.ate-system.svc:443")

        projected = next(volume["projected"] for volume in pod["volumes"] if volume["name"] == "substrate")
        token = next(
            source["serviceAccountToken"]
            for source in projected["sources"]
            if "serviceAccountToken" in source
        )
        self.assertEqual(token["audience"], "api.ate-system.svc")
        self.assertIn("podcert-agent", [
            container["name"] for container in pod.get("initContainers", [])
        ])
        self.assertEqual(
            next(volume["configMap"]["name"] for volume in pod["volumes"] if volume["name"] == "podcert-trust"),
            "podcert-trust-bundles",
        )
        substrate_trust = next(
            source["configMap"]["name"]
            for source in projected["sources"]
            if "configMap" in source
        )
        self.assertEqual(substrate_trust, "podcert-trust-bundles")
        self.assertEqual(
            next(volume for volume in pod["volumes"] if volume["name"] == "podidentity").get("emptyDir"),
            {"medium": "Memory"},
        )
        self.assertFalse(any(
            "clusterTrustBundle" in source
            for volume in pod["volumes"] if volume["name"] == "substrate"
            for source in volume.get("projected", {}).get("sources", [])
        ))

    def test_talos_example_renders_external_services_and_small_worker_configuration(self) -> None:
        example = yaml.safe_load((ROOT / "examples" / "talos-values.yaml").read_text(encoding="utf-8"))
        resources = resources_by_identity(self.render(example))
        self.assertFalse(any(identity[1] == "StatefulSet" and identity[3] == "postgres" for identity in resources))

        pool = get_resource(resources, "WorkerPool", "amp-orbs", RELEASE_NAMESPACE)
        self.assertEqual(pool["spec"]["template"]["resources"]["limits"], {
            "cpu": "2",
            "memory": "5Gi",
        })
        provider = get_resource(resources, "Deployment", "amp-orb-provider", RELEASE_NAMESPACE)
        provider_environment = env_values(container_named(pod_spec(provider), "provider"))
        self.assertEqual(provider_environment["SANDBOX_CPU"], "2")
        self.assertEqual(provider_environment["SANDBOX_MEMORY_GI"], "4")
        self.assertEqual(provider_environment["SUBSTRATE_WORKERS_MIN"], "0")
        self.assertEqual(provider_environment["SUBSTRATE_WORKERS_WARM"], "0")

        bootstrap = get_resource(resources, "Job", "substrate-bootstrap", RELEASE_NAMESPACE)
        self.assertEqual(bootstrap["metadata"]["namespace"], RELEASE_NAMESPACE)
        bootstrap_pod = pod_spec(bootstrap)
        bootstrap_container = container_named(bootstrap_pod, "bootstrap", "initContainers")
        self.assertIn("orb-database", secret_references(bootstrap_container))
        self.assertEqual(
            container_named(bootstrap_pod, "configure-authentication")["command"][:2],
            ["node", "-e"],
        )

        api = get_resource(resources, "Deployment", "ate-api-server", "ate-system")
        api_pod = pod_spec(api)
        ca_volume = next(
            volume
            for volume in api_pod["volumes"]
            if volume.get("secret", {}).get("secretName") == "orb-database-ca"
        )
        self.assertEqual(ca_volume["secret"]["items"], [{"key": "ca.crt", "path": "server-ca.pem"}])
        self.assertNotIn("orb-database", secret_references(container_named(api_pod, "ate-api-server")))
        self.assertEqual(
            {
                volume["secret"]["secretName"]
                for volume in api_pod["volumes"]
                if "secret" in volume
            },
            {"orb-database-ca"},
        )

        atelet = get_resource(resources, "DaemonSet", "atelet", "ate-system")
        atelet_container = container_named(pod_spec(atelet), "atelet")
        self.assertIn("--image-cache-max-bytes=21474836480", atelet_container["args"])
        self.assertIn("--image-cache-high-percent=75", atelet_container["args"])
        self.assertIn("--image-cache-low-percent=65", atelet_container["args"])

        objectstore_uses = set()
        for resource in resources.values():
            template = (resource.get("spec") or {}).get("template") or {}
            if "spec" not in template:
                continue
            template_pod = template["spec"]
            secret_volumes = {
                volume["name"]
                for volume in template_pod.get("volumes", [])
                if volume.get("secret", {}).get("secretName") == "orb-storage"
            }
            for section in ("containers", "initContainers"):
                for container in template_pod.get(section, []):
                    mounts_secret = any(
                        mount.get("name") in secret_volumes
                        for mount in container.get("volumeMounts", [])
                    )
                    if "orb-storage" in secret_references(container) or mounts_secret:
                        self.assertEqual(
                            {
                                key: env_values(container).get(key)
                                for key in (
                                    "ATE_STORAGE_BACKEND",
                                    "AWS_REGION",
                                    "AWS_ENDPOINT_URL",
                                    "AWS_S3_USE_PATH_STYLE",
                                )
                            },
                            {
                                "ATE_STORAGE_BACKEND": "s3",
                                "AWS_REGION": "us-east-1",
                                "AWS_ENDPOINT_URL": "https://s3.example.com",
                                "AWS_S3_USE_PATH_STYLE": "true",
                            },
                        )
                        objectstore_uses.add((resource["kind"], resource["metadata"]["name"], container["name"]))
        self.assertEqual(objectstore_uses, {
            ("Deployment", "ate-api-server", "objectstore-plugin"),
            ("DaemonSet", "atelet", "objectstore-plugin"),
        })

    def test_external_native_pki_delivery_uses_cluster_trust_bundle(self) -> None:
        values = merge_values(
            valid_values("onprem"),
            {"substrate": {"enabled": False, "external": {"pkiDelivery": "native"}}},
        )
        resources = resources_by_identity(self.render(values))
        provider = get_resource(resources, "Deployment", "amp-orb-provider", RELEASE_NAMESPACE)
        pod = pod_spec(provider)
        self.assertFalse(any(
            container.get("name") == "podcert-agent"
            for container in pod.get("initContainers", [])
        ))
        self.assertFalse(any(volume["name"] == "podcert-trust" for volume in pod["volumes"]))
        podidentity = next(volume["projected"] for volume in pod["volumes"] if volume["name"] == "podidentity")
        self.assertTrue(any("podCertificate" in source for source in podidentity["sources"]))
        projected = next(volume["projected"] for volume in pod["volumes"] if volume["name"] == "substrate")
        self.assertTrue(any("clusterTrustBundle" in source for source in projected["sources"]))

    def test_external_pki_delivery_rejects_unknown_mode(self) -> None:
        self.assert_render_fails(
            merge_values(
                valid_values("onprem"),
                {"substrate": {"enabled": False, "external": {"pkiDelivery": "unknown"}}},
            ),
            "must be one of",
        )

    def test_in_cluster_jwks_enables_the_post_bootstrap_configurer(self) -> None:
        values = merge_values(
            valid_values("gke"),
            {"substrate": {"authentication": {"inClusterJWKS": True}}},
        )
        resources = resources_by_identity(self.render(values))
        bootstrap = get_resource(resources, "Job", "substrate-bootstrap", RELEASE_NAMESPACE)
        pod = pod_spec(bootstrap)
        bootstrap_container = container_named(pod, "bootstrap", "initContainers")
        self.assertEqual(bootstrap_container["args"][0], "bootstrap")
        configurer = container_named(pod, "configure-authentication")
        self.assertEqual(configurer["command"][:2], ["node", "-e"])
        script = configurer["command"][2]
        self.assertEqual(script, (CHART / "files/configure-authentication.js").read_text(encoding="utf-8"))
        for required_fragment in (
            "kubernetes.default.svc",
            "/.well-known/openid-configuration",
            "/openid/v1/jwks",
            "ca.crt",
            "/var/run/secrets/kubernetes.io/serviceaccount",
            "/token",
            "authentication-sha256",
        ):
            self.assertIn(required_fragment, script)

        default_revision = get_resource(
            resources_by_identity(self.render(valid_values("gke"))),
            "ConfigMap",
            "amp-orb-provider-release",
            RELEASE_NAMESPACE,
        )["data"]["substrateRevision"]
        enabled_revision = get_resource(
            resources,
            "ConfigMap",
            "amp-orb-provider-release",
            RELEASE_NAMESPACE,
        )["data"]["substrateRevision"]
        repeated_revision = get_resource(
            resources_by_identity(self.render(values)),
            "ConfigMap",
            "amp-orb-provider-release",
            RELEASE_NAMESPACE,
        )["data"]["substrateRevision"]
        self.assertNotEqual(enabled_revision, default_revision)
        self.assertEqual(enabled_revision, repeated_revision)

    def test_in_cluster_jwks_is_rejected_for_external_runtime(self) -> None:
        self.assert_render_fails(
            merge_values(
                valid_values("onprem"),
                {"substrate": {"enabled": False, "authentication": {"inClusterJWKS": True}}},
            ),
            "inClusterJWKS",
        )

    def test_external_postgres_secret_and_ca_are_rendered_only_for_external_database(self) -> None:
        values = merge_values(
            valid_values("gke"),
            {
                "postgres": {
                    "enabled": False,
                    "external": {
                        "existingSecret": "amp-postgres-connection",
                        "caSecret": "amp-postgres-ca",
                    },
                }
            },
        )
        resources = resources_by_identity(self.render(values))
        self.assertFalse(any(identity[1] == "StatefulSet" and identity[3] == "postgres" for identity in resources))
        bootstrap = get_resource(resources, "Job", "substrate-bootstrap", RELEASE_NAMESPACE)
        bootstrap_pod = pod_spec(bootstrap)
        bootstrap_container = container_named(bootstrap_pod, "bootstrap")
        self.assertIn("amp-postgres-connection", secret_references(bootstrap_container))
        external_postgres_uses = set()
        for resource in resources.values():
            template = (resource.get("spec") or {}).get("template") or {}
            if "spec" not in template:
                continue
            for section in ("containers", "initContainers"):
                for container in template["spec"].get(section, []):
                    if "amp-postgres-connection" in secret_references(container):
                        external_postgres_uses.add((resource["kind"], resource["metadata"]["name"], container["name"]))
        self.assertEqual(external_postgres_uses, {("Job", "substrate-bootstrap", "bootstrap")})

        api = get_resource(resources, "Deployment", "ate-api-server", "ate-system")
        api_pod = pod_spec(api)
        api_main = container_named(api_pod, "ate-api-server")
        self.assertIn(
            "ate-api-server-secret-envvars",
            {reference for entry in api_main.get("envFrom", [])
             for reference in [entry.get("secretRef", {}).get("name")] if reference},
        )
        self.assertNotIn("amp-postgres-connection", secret_references(api_main))
        ca_volume = next(
            volume
            for volume in api_pod["volumes"]
            if volume.get("secret", {}).get("secretName") == "amp-postgres-ca"
        )
        self.assertEqual(ca_volume["secret"]["items"], [{"key": "ca.crt", "path": "server-ca.pem"}])

        custom_ca = merge_values(values, {"postgres": {"external": {"caKey": "root.pem"}}})
        custom_resources = resources_by_identity(self.render(custom_ca))
        custom_api_pod = pod_spec(get_resource(custom_resources, "Deployment", "ate-api-server", "ate-system"))
        custom_ca_volume = next(
            volume
            for volume in custom_api_pod["volumes"]
            if volume.get("secret", {}).get("secretName") == "amp-postgres-ca"
        )
        self.assertEqual(custom_ca_volume["secret"]["items"], [{"key": "root.pem", "path": "server-ca.pem"}])

    def test_external_postgres_secret_key_names_are_documented(self) -> None:
        values_text = (CHART / "values.yaml").read_text(encoding="utf-8")
        for secret_key in EXTERNAL_POSTGRES_KEYS:
            with self.subTest(secret_key=secret_key):
                self.assertIn(secret_key, values_text)

    def test_external_postgres_requires_connection_and_ca_secrets(self) -> None:
        missing_connection = merge_values(
            valid_values("gke"),
            {"postgres": {"enabled": False, "external": {"caSecret": "amp-postgres-ca"}}},
        )
        self.assert_render_fails(missing_connection, "postgres.external.existingSecret")
        missing_ca = merge_values(
            valid_values("gke"),
            {"postgres": {"enabled": False, "external": {"existingSecret": "amp-postgres-connection"}}},
        )
        self.assert_render_fails(missing_ca, "postgres.external.caSecret")

    def test_custom_s3_is_supported_on_each_cloud_and_secrets_only_reach_plugin_sidecars(self) -> None:
        for cloud in ("gke", "eks", "aks", "onprem"):
            with self.subTest(cloud=cloud):
                values = merge_values(
                    valid_values(cloud),
                    {
                        "snapshots": {
                            "s3": {
                                "endpoint": "https://s3.example.test",
                                "region": "us-west-2",
                                "existingSecret": "amp-s3-credentials",
                            }
                        }
                    },
                )
                resources = resources_by_identity(self.render(values))
                expected_uses = {
                    ("Deployment", "ate-api-server", "objectstore-plugin"),
                    ("DaemonSet", "atelet", "objectstore-plugin"),
                }
                actual_uses: set[tuple[str, str, str]] = set()
                for resource in resources.values():
                    template = (resource.get("spec") or {}).get("template") or {}
                    if "spec" not in template:
                        continue
                    pod = template["spec"]
                    secret_volumes = {
                        volume["name"]
                        for volume in pod.get("volumes", [])
                        if volume.get("secret", {}).get("secretName") == "amp-s3-credentials"
                    }
                    for section in ("containers", "initContainers"):
                        for container in pod.get(section, []):
                            mounted_secret = any(
                                mount.get("name") in secret_volumes
                                for mount in container.get("volumeMounts", [])
                            )
                            if "amp-s3-credentials" in secret_references(container) or mounted_secret:
                                actual_uses.add((resource["kind"], resource["metadata"]["name"], container["name"]))
                                self.assertEqual(container["name"], "objectstore-plugin")
                                environment = env_values(container)
                                self.assertEqual(
                                    {key: environment.get(key) for key in (
                                        "ATE_STORAGE_BACKEND",
                                        "AWS_REGION",
                                        "AWS_ENDPOINT_URL",
                                        "AWS_S3_USE_PATH_STYLE",
                                        "AWS_EC2_METADATA_DISABLED",
                                    )},
                                    {
                                        "ATE_STORAGE_BACKEND": "s3",
                                        "AWS_REGION": "us-west-2",
                                        "AWS_ENDPOINT_URL": "https://s3.example.test",
                                        "AWS_S3_USE_PATH_STYLE": "true",
                                        "AWS_EC2_METADATA_DISABLED": "true",
                                    },
                                )
                self.assertEqual(actual_uses, expected_uses)
                self.assertFalse(any(
                    identity[1] == "Secret" and identity[3] == "amp-s3-credentials"
                    for identity in resources
                ))
                provider = get_resource(resources, "Deployment", "amp-orb-provider", RELEASE_NAMESPACE)
                self.assertNotIn("amp-s3-credentials", str(provider))

    def test_custom_s3_requires_region_and_existing_secret_and_onprem_requires_endpoint(self) -> None:
        gke = valid_values("gke")
        endpoint_only = merge_values(gke, {"snapshots": {"s3": {"endpoint": "https://s3.example.test"}}})
        self.assert_render_fails(endpoint_only, "snapshots.s3.region")
        with_region = merge_values(endpoint_only, {"snapshots": {"s3": {"region": "us-west-2"}}})
        self.assert_render_fails(with_region, "snapshots.s3.existingSecret")
        self.assert_render_fails(valid_values("onprem"), "snapshots.s3.endpoint")

    def test_onprem_bundled_database_is_optional_and_custom_s3_is_sufficient(self) -> None:
        values = merge_values(
            valid_values("onprem"),
            {"snapshots": {"s3": {
                "endpoint": "https://s3.example.test",
                "region": "us-west-2",
                "existingSecret": "amp-s3-credentials",
            }}},
        )
        resources = resources_by_identity(self.render(values))
        get_resource(resources, "StatefulSet", "postgres", "ate-system")
        get_resource(resources, "DaemonSet", "atelet", "ate-system")

    def test_image_cache_accepts_zero_bytes_and_passes_all_options_to_atelet(self) -> None:
        values = merge_values(
            valid_values("gke"),
            {"atelet": {"imageCache": {
                "maxBytes": 0,
                "highPercent": 75,
                "lowPercent": 65,
                "gcPeriod": "0s",
            }}},
        )
        resources = resources_by_identity(self.render(values))
        atelet = get_resource(resources, "DaemonSet", "atelet", "ate-system")
        container = container_named(pod_spec(atelet), "atelet")
        self.assertEqual(
            {
                arg
                for arg in container["args"]
                if arg.startswith("--image-cache-")
            },
            {
                "--image-cache-max-bytes=0",
                "--image-cache-high-percent=75",
                "--image-cache-low-percent=65",
                "--image-cache-gc-period=0s",
            },
        )

    def test_image_cache_accepts_zero_low_watermark(self) -> None:
        resources = resources_by_identity(self.render(
            merge_values(valid_values("gke"), {"atelet": {"imageCache": {"highPercent": 1, "lowPercent": 0}}})
        ))
        atelet = get_resource(resources, "DaemonSet", "atelet", "ate-system")
        args = container_named(pod_spec(atelet), "atelet")["args"]
        self.assertIn("--image-cache-high-percent=1", args)
        self.assertIn("--image-cache-low-percent=0", args)

    def test_image_cache_rejects_invalid_watermarks(self) -> None:
        for image_cache in (
            {"maxBytes": -1},
            {"highPercent": 101, "lowPercent": 65},
            {"highPercent": 75},
            {"highPercent": 75, "lowPercent": 80},
            {"highPercent": 75, "lowPercent": 75},
            {"highPercent": 75, "lowPercent": -1},
        ):
            with self.subTest(image_cache=image_cache):
                self.assert_render_fails(
                    merge_values(valid_values("gke"), {"atelet": {"imageCache": image_cache}})
                )

    def test_authentication_helper_handles_safe_updates_and_failures(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node.js is required to verify the bootstrap authentication helper")

        scenarios = {
            "default-yaml": (0, ["GET", "GET", "PATCH", "GET", "PATCH"]),
            "first-install": (0, ["GET", "GET", "PATCH", "GET"]),
            "repeated-json": (0, ["GET", "GET", "PATCH", "GET"]),
            "json-other-provider": (0, ["GET", "GET", "PATCH", "GET", "PATCH"]),
            "http-failure": (1, ["GET", "GET"]),
            "timeout": (1, ["GET"]),
            "custom-issuer": (1, ["GET", "GET"]),
            "custom-yaml": (1, ["GET", "GET"]),
            "deployment-patch-failure": (1, ["GET", "GET", "PATCH", "GET", "PATCH"]),
        }
        harness = ROOT / "tests" / "authentication_harness.cjs"
        script_path = CHART / "files" / "configure-authentication.js"
        for scenario, (expected_exit, expected_methods) in scenarios.items():
            with self.subTest(scenario=scenario):
                result = subprocess.run(
                    [node, str(harness)],
                    input=json.dumps({"scriptPath": str(script_path), "scenario": scenario}),
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=10,
                )
                self.assertEqual(result.returncode, expected_exit, result.stderr)
                self.assertEqual(result.stderr, "")
                self.assertNotIn("test-token", result.stdout)
                self.assertNotIn("sensitive-http-response-body", result.stdout)
                output = json.loads(result.stdout)
                self.assertEqual(output["exitCode"], expected_exit)
                calls = output["calls"]
                self.assertEqual([call["method"] for call in calls], expected_methods)
                self.assertEqual(calls[0]["path"], "/.well-known/openid-configuration")
                self.assertEqual(len(output["logs"]), 1)
                self.assertEqual("failed" in output["logs"][0], bool(expected_exit))

                config_patch = next(
                    (call for call in calls if call["method"] == "PATCH" and "configmaps/" in call["path"]),
                    None,
                )
                if expected_exit and scenario != "deployment-patch-failure":
                    self.assertIsNone(config_patch, "failed or unrecognized configuration must not be overwritten")
                    continue
                self.assertIsNotNone(config_patch, "configuration should be written before API rollout")

                authentication = config_patch["body"]["data"]["authentication.yaml"]
                parsed = json.loads(authentication)
                kubernetes, = [provider for provider in parsed["jwtProviders"] if provider["name"] == "kubernetes"]
                self.assertEqual(kubernetes["issuer"], "https://cluster.example:6443")
                self.assertEqual(kubernetes["jwksURI"], "https://kubernetes.default.svc/openid/v1/jwks")
                self.assertEqual(
                    kubernetes["certificateAuthorityFile"],
                    "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt",
                )
                self.assertEqual(
                    kubernetes["discoveryTokenFile"],
                    "/var/run/secrets/kubernetes.io/serviceaccount/token",
                )

                deployment_patch = next(
                    (call for call in calls if call["method"] == "PATCH" and "deployments/" in call["path"]),
                    None,
                )
                if deployment_patch:
                    annotation = deployment_patch["body"]["spec"]["template"]["metadata"]["annotations"][
                        "substrate.ate.dev/authentication-sha256"
                    ]
                    self.assertEqual(annotation, hashlib.sha256(authentication.encode()).hexdigest())
                else:
                    self.assertIn(scenario, {"repeated-json", "first-install"})

                if scenario in {"repeated-json", "json-other-provider"}:
                    other = next(provider for provider in parsed["jwtProviders"] if provider["name"] == "external")
                    self.assertEqual(other["keep"], "additional provider")
                    self.assertEqual(parsed["additionalSettings"], {"keep": True})
                if scenario == "repeated-json":
                    self.assertIsNone(deployment_patch, "an unchanged auth hash should not patch the API deployment")
                if scenario == "first-install":
                    self.assertIsNone(deployment_patch, "a missing API deployment has nothing to restart")
                if scenario == "deployment-patch-failure":
                    self.assertIsNotNone(deployment_patch, "a rollout patch failure must fail after auth is updated")

    def test_invalid_cloud_is_rejected(self) -> None:
        self.assert_render_fails(valid_values("invalid"), "value must be one of")


if __name__ == "__main__":
    unittest.main()
