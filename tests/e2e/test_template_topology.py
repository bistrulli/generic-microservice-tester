"""E2E tests: deploy template_annotated.lqn topology on K8s and verify behavior.

Prerequisites:
- K8s cluster accessible via kubectl (e.g., Rancher Desktop)
- GMT Docker image built and available in the cluster
- Run with: pytest tests/e2e/ -v -s

These tests deploy 3 microservices (TServer, TFileServer, TBackup),
send requests to each entry, and verify the topology behaves correctly.
"""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests

# Add tools/ and src/ to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "tools"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from lqn_compiler import compile_model
from lqn_parser import parse_lqn_file

GROUNDTRUTH = (
    Path(__file__).parent.parent.parent
    / "test"
    / "lqn-groundtruth"
    / "template_annotated.lqn"
)
NAMESPACE = "gmt-e2e-test"
IMAGE = os.environ.get("GMT_E2E_IMAGE", "gmt-test:latest")
TSERVER_URL = None  # Set during setup


def _run(cmd: str, check: bool = True, timeout: int = 30) -> str:
    """Run a shell command and return stdout."""
    result = subprocess.run(
        cmd, shell=True, capture_output=True, text=True, timeout=timeout
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"Command failed: {cmd}\n{result.stderr}")
    return result.stdout.strip()


def _wait_for_pods_ready(namespace: str, timeout: int = 120):
    """Wait until all pods in namespace are Running."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        output = _run(
            f"kubectl get pods -n {namespace} --no-headers -o custom-columns=':status.phase'",
            check=False,
        )
        if not output:
            time.sleep(3)
            continue
        phases = output.strip().split("\n")
        if all(p.strip() == "Running" for p in phases if p.strip()):
            return
        time.sleep(3)
    raise TimeoutError(f"Pods not ready in {namespace} after {timeout}s")


@pytest.fixture(scope="module", autouse=True)
def deploy_topology():
    """Deploy the template_annotated topology and tear it down after tests."""
    if not GROUNDTRUTH.exists():
        pytest.skip(f"Ground truth not found: {GROUNDTRUTH}")

    # Check kubectl works
    try:
        _run("kubectl cluster-info", timeout=10)
    except Exception:
        pytest.skip("K8s cluster not available")

    # Create namespace
    _run(f"kubectl create namespace {NAMESPACE}", check=False)

    # Compile and deploy
    model = parse_lqn_file(str(GROUNDTRUTH))
    yaml_output = compile_model(model, image=IMAGE)

    # Write to temp file and apply
    manifest_path = Path("/tmp/gmt-e2e-manifest.yaml")
    manifest_path.write_text(yaml_output)
    _run(f"kubectl apply -f {manifest_path} -n {NAMESPACE}")

    # Wait for pods
    try:
        _wait_for_pods_ready(NAMESPACE, timeout=120)
    except TimeoutError:
        # Show pod status for debugging
        print(_run(f"kubectl get pods -n {NAMESPACE}", check=False))
        print(_run(f"kubectl describe pods -n {NAMESPACE}", check=False))
        pytest.skip("Pods not ready — check Docker image availability in cluster")

    # Port-forward tserver-svc
    global TSERVER_URL
    port = 28080
    pf_proc = subprocess.Popen(
        f"kubectl port-forward svc/tserver-svc -n {NAMESPACE} {port}:80".split(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    TSERVER_URL = f"http://localhost:{port}"
    time.sleep(3)  # Wait for port-forward to establish

    yield

    # Teardown
    pf_proc.terminate()
    pf_proc.wait(timeout=5)
    _run(f"kubectl delete namespace {NAMESPACE} --wait=false", check=False)


class TestDeployTopology:
    def test_all_pods_running(self):
        output = _run(f"kubectl get pods -n {NAMESPACE} --no-headers")
        lines = [line for line in output.split("\n") if line.strip()]
        assert len(lines) == 3, f"Expected 3 pods, got {len(lines)}: {output}"
        for line in lines:
            assert "Running" in line, f"Pod not running: {line}"

    def test_services_exist(self):
        output = _run(f"kubectl get svc -n {NAMESPACE} --no-headers")
        assert "tserver-svc" in output
        assert "tfileserver-svc" in output
        assert "tbackup-svc" in output


class TestVisitEntry:
    def test_visit_returns_200(self):
        resp = requests.get(f"{TSERVER_URL}/visit", timeout=10)
        assert resp.status_code == 200

    def test_visit_response_structure(self):
        resp = requests.get(f"{TSERVER_URL}/visit", timeout=10)
        data = resp.json()
        assert "message" in data
        assert "entry" in data
        assert data["entry"] == "visit"


class TestBuyEntry:
    def test_buy_returns_200(self):
        resp = requests.get(f"{TSERVER_URL}/buy", timeout=10)
        assert resp.status_code == 200

    def test_buy_response_structure(self):
        resp = requests.get(f"{TSERVER_URL}/buy", timeout=10)
        data = resp.json()
        assert data["entry"] == "buy"


class TestNotifyEntry:
    def test_notify_returns_200(self):
        resp = requests.get(f"{TSERVER_URL}/notify", timeout=10)
        assert resp.status_code == 200

    def test_notify_is_fast(self):
        """Notify has only 0.08s service time, no outbound calls → fast."""
        start = time.monotonic()
        resp = requests.get(f"{TSERVER_URL}/notify", timeout=10)
        elapsed = time.monotonic() - start
        assert resp.status_code == 200
        # Should be reasonably fast (< 2s including network)
        assert elapsed < 2.0, f"Notify took {elapsed:.3f}s"


class TestSaveEntry:
    def test_save_returns_200(self):
        resp = requests.get(f"{TSERVER_URL}/save", timeout=30)
        assert resp.status_code == 200
