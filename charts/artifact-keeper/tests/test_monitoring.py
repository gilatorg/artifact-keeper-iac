"""Offline render tests for the ServiceMonitor and the Prometheus NetworkPolicy rule."""

import os
from pathlib import Path
import subprocess
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[3]
CHART = ROOT / "charts/artifact-keeper"
MONITORING_NS = "monitoring"


def render(values=None):
    result = subprocess.run(
        [
            os.environ.get("HELM", "helm"), "template", "mon-test", str(CHART),
            "--namespace", "artifacts",
            "--set", "secrets.existingSecret=render-test",
            "-f", "-",
        ],
        input=yaml.safe_dump(values or {}),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise AssertionError(result.stderr)
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def find(docs, kind, name_suffix):
    matches = [
        d for d in docs
        if d["kind"] == kind and d["metadata"]["name"].endswith(name_suffix)
    ]
    assert len(matches) == 1, f"{kind} *{name_suffix}: {len(matches)} found"
    return matches[0]


def monitoring_ports(docs):
    policy = find(docs, "NetworkPolicy", "-backend")
    for rule in policy["spec"]["ingress"]:
        for peer in rule.get("from", []):
            selector = peer.get("namespaceSelector", {}).get("matchLabels", {})
            if selector.get("kubernetes.io/metadata.name") == MONITORING_NS:
                return [p["port"] for p in rule["ports"]]
    raise AssertionError("no ingress rule for the monitoring namespace")


class ServiceMonitorTest(unittest.TestCase):
    def test_extra_labels_are_applied(self):
        docs = render({"serviceMonitor": {
            "enabled": True,
            "labels": {"release": "kube-prometheus-stack"},
        }})
        sm = find(docs, "ServiceMonitor", "-backend")
        self.assertEqual(sm["metadata"]["labels"]["release"], "kube-prometheus-stack")
        self.assertEqual(sm["metadata"]["labels"]["app.kubernetes.io/component"], "backend")

    def test_no_extra_labels_by_default(self):
        sm = find(render({"serviceMonitor": {"enabled": True}}), "ServiceMonitor", "-backend")
        self.assertNotIn("release", sm["metadata"]["labels"])

    def test_listener_scrapes_metrics_port(self):
        docs = render({
            "serviceMonitor": {"enabled": True},
            "backend": {"metricsListener": {"enabled": True}},
        })
        endpoint = find(docs, "ServiceMonitor", "-backend")["spec"]["endpoints"][0]
        self.assertEqual((endpoint["port"], endpoint["path"]), ("metrics", "/metrics"))


class NetworkPolicyTest(unittest.TestCase):
    def test_monitoring_gets_metrics_port_when_listener_enabled(self):
        docs = render({
            "networkPolicy": {"enabled": True},
            "backend": {"metricsListener": {"enabled": True, "port": 9091}},
        })
        self.assertEqual(monitoring_ports(docs), [8080, 9091])

    def test_monitoring_gets_only_http_port_without_listener(self):
        docs = render({"networkPolicy": {"enabled": True}})
        self.assertEqual(monitoring_ports(docs), [8080])


if __name__ == "__main__":
    unittest.main()
