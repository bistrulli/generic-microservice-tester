"""Tests for the LQN-to-K8s compiler."""

import sys
from pathlib import Path

import pytest

# Add tools/ and src/ to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "tools"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from lqn_compiler import (
    build_task_config,
    compile_model,
    resolve_call_target,
    task_to_k8s_name,
)
from lqn_parser import parse_lqn_file


@pytest.fixture()
def model(groundtruth_dir):
    filepath = groundtruth_dir / "template_annotated.lqn"
    if not filepath.exists():
        pytest.skip(f"Ground truth file not found: {filepath}")
    return parse_lqn_file(str(filepath))


class TestTaskToK8sName:
    def test_simple(self):
        assert task_to_k8s_name("TServer") == "tserver"

    def test_underscore(self):
        assert task_to_k8s_name("TFile_Server") == "tfile-server"

    def test_already_lowercase(self):
        assert task_to_k8s_name("myservice") == "myservice"


class TestResolveCallTarget:
    def test_resolves_entry(self, model):
        result = resolve_call_target(model, "read")
        assert result is not None
        svc, path = result
        assert svc == "tfileserver-svc"
        assert path == "read"

    def test_resolves_unknown_returns_none(self, model):
        result = resolve_call_target(model, "nonexistent")
        assert result is None


class TestCompileGeneratesDeploymentPerTask:
    def test_non_reference_tasks_get_deployments(self, model):
        yaml_str = compile_model(model)
        # TServer, TFileServer, TBackup = 3 non-reference tasks
        assert yaml_str.count("kind: Deployment") == 3

    def test_reference_task_skipped(self, model):
        yaml_str = compile_model(model)
        assert "tclient" not in yaml_str.lower().split("kind:")[0]
        # TClient should not appear as a deployment name
        assert "tclient-deployment" not in yaml_str


class TestCompileGeneratesServicePerTask:
    def test_services_generated(self, model):
        yaml_str = compile_model(model)
        assert yaml_str.count("kind: Service") == 3

    def test_service_naming(self, model):
        yaml_str = compile_model(model)
        assert "tserver-svc" in yaml_str
        assert "tfileserver-svc" in yaml_str
        assert "tbackup-svc" in yaml_str


class TestCompileTaskMultiplicity:
    def test_gunicorn_workers_matches_multiplicity(self, model):
        yaml_str = compile_model(model)
        # TServer has m=2
        assert 'value: "2"' in yaml_str


class TestCompileEntryToConfig:
    def test_lqn_task_config_present(self, model):
        yaml_str = compile_model(model)
        assert "LQN_TASK_CONFIG" in yaml_str

    def test_tserver_config_has_entries(self, model):
        # Find TServer task and build its config
        tserver = next(t for t in model.tasks if t.name == "TServer")
        config = build_task_config(tserver, model)
        assert "visit" in config["entries"]
        assert "buy" in config["entries"]
        assert "notify" in config["entries"]
        assert "save" in config["entries"]


class TestCompileActivityGraphSerialized:
    def test_tserver_graph_in_config(self, model):
        tserver = next(t for t in model.tasks if t.name == "TServer")
        config = build_task_config(tserver, model)
        graph = config["graph"]
        assert len(graph["and_forks"]) == 1
        assert len(graph["and_joins"]) == 1
        assert len(graph["or_forks"]) == 1
        assert "internal" in graph["replies"]
        assert "display" in graph["replies"]


class TestCompileCallTargetResolution:
    def test_activity_call_resolved_to_service(self, model):
        tserver = next(t for t in model.tasks if t.name == "TServer")
        config = build_task_config(tserver, model)
        # external activity has y external read 1.0
        ext = config["activities"]["external"]
        assert "sync_calls" in ext
        # Should resolve 'read' entry to 'tfileserver-svc/read'
        urls = list(ext["sync_calls"].keys())
        assert any("tfileserver-svc/read" in url for url in urls)

    def test_phase_entry_calls_resolved(self, model):
        # save entry has y save write 1.0
        tserver = next(t for t in model.tasks if t.name == "TServer")
        config = build_task_config(tserver, model)
        save_entry = config["entries"]["save"]
        assert "sync_calls" in save_entry
        urls = list(save_entry["sync_calls"].keys())
        assert any("tfileserver-svc/write" in url for url in urls)


class TestCompileValidYaml:
    def test_yaml_structure(self, model):
        yaml_str = compile_model(model)
        # Basic YAML structure checks
        assert "apiVersion: apps/v1" in yaml_str
        assert "apiVersion: v1" in yaml_str
        assert "containerPort: 8080" in yaml_str
        assert "targetPort: 8080" in yaml_str


class TestCompileLabels:
    def test_standard_labels(self, model):
        yaml_str = compile_model(model)
        assert "app.kubernetes.io/name:" in yaml_str
        assert "app.kubernetes.io/component: lqn-task" in yaml_str
        assert "lqn.gmt/model:" in yaml_str


class TestCompileCustomImage:
    def test_custom_image(self, model):
        yaml_str = compile_model(model, image="myregistry/gmt:v2.0")
        assert "myregistry/gmt:v2.0" in yaml_str
        assert "generic-microservice-tester:latest" not in yaml_str


class TestCompileResourceLimits:
    def test_cpu_requests_present(self, model):
        yaml_str = compile_model(model)
        assert "requests:" in yaml_str
        assert "cpu:" in yaml_str
        assert "limits:" in yaml_str
