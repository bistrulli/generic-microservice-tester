"""Unit tests for locustfile generator."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "tools"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from locustfile_gen import generate_locustfile
from lqn_parser import parse_lqn_file

GROUNDTRUTH = Path(__file__).parent.parent.parent / "test" / "lqn-groundtruth"


class TestSingleEntryModel:
    """validation-model.lqn: TClient calls process×1.0 sync (phase-based)."""

    @pytest.fixture()
    def source(self) -> str:
        model = parse_lqn_file(str(GROUNDTRUTH / "validation-model.lqn"))
        return generate_locustfile(model)

    def test_generates_valid_python(self, source: str) -> None:
        compile(source, "<test>", "exec")

    def test_contains_locust_imports(self, source: str) -> None:
        assert "from locust import HttpUser, task" in source

    def test_relative_url(self, source: str) -> None:
        """URL must be relative so --host works."""
        assert 'self.client.get("/process")' in source
        assert "http://" not in source.split("class")[1]  # no absolute URLs in class

    def test_wait_time_zero(self, source: str) -> None:
        """All timing in cycle, Locust wait_time = 0."""
        assert "return 0" in source

    def test_no_expovariate(self, source: str) -> None:
        """No exponential wait — deterministic timing via time.sleep."""
        assert "expovariate" not in source


class TestMultiEntryModel:
    """template_annotated.lqn: TClient calls visit×3, save×1, read×1, buy×1.2, notify×1."""

    @pytest.fixture()
    def source(self) -> str:
        model = parse_lqn_file(str(GROUNDTRUTH / "template_annotated.lqn"))
        return generate_locustfile(model)

    def test_generates_valid_python(self, source: str) -> None:
        compile(source, "<test>", "exec")

    def test_relative_urls(self, source: str) -> None:
        assert '"/visit"' in source
        assert '"/save"' in source
        assert '"/buy"' in source
        assert '"/read"' in source

    def test_visit_called_3_times(self, source: str) -> None:
        assert "for _ in range(3):" in source
        assert '"/visit"' in source

    def test_fractional_calls_buy(self, source: str) -> None:
        assert "random.random() < 0.2" in source
        assert '"/buy"' in source

    def test_async_calls_included(self, source: str) -> None:
        assert '"/notify"' in source

    def test_no_absolute_urls(self, source: str) -> None:
        """All URLs must be relative paths."""
        class_body = source.split("class")[1]
        assert "http://" not in class_body


class TestActivityBasedRefTask:
    """lqn01-5f.lqn: Task0 has activity-based entry with service times + calls."""

    LQN01_PATH = Path("/Users/emilio-imt/git/TLG/tests/lqntest_model/lqn01-5f.lqn")

    @pytest.fixture()
    def source(self) -> str:
        if not self.LQN01_PATH.exists():
            pytest.skip(f"Model not found: {self.LQN01_PATH}")
        model = parse_lqn_file(str(self.LQN01_PATH))
        return generate_locustfile(model)

    def test_generates_valid_python(self, source: str) -> None:
        compile(source, "<test>", "exec")

    def test_no_pass_in_cycle(self, source: str) -> None:
        assert "pass" not in source

    def test_calls_gw1_with_relative_url(self, source: str) -> None:
        assert 'self.client.get("/gw1")' in source

    def test_service_time_as_sleep(self, source: str) -> None:
        """Activity service times become time.sleep()."""
        assert "time.sleep(0.105)" in source
        assert "import time" in source


class TestActivityThinkTimeModel:
    """test_app_2_gt.lqn: Task0 with acti0 s=1.0 (think time as activity)."""

    MODEL_PATH = Path(
        "/Users/emilio-imt/git/TLG/tests/lqn_structure_test/test_app_2/test_app_2_gt.lqn"
    )

    @pytest.fixture()
    def source(self) -> str:
        if not self.MODEL_PATH.exists():
            pytest.skip(f"Model not found: {self.MODEL_PATH}")
        model = parse_lqn_file(str(self.MODEL_PATH))
        return generate_locustfile(model)

    def test_generates_valid_python(self, source: str) -> None:
        compile(source, "<test>", "exec")

    def test_think_time_as_sleep(self, source: str) -> None:
        """acti0 with s=1.0 becomes time.sleep(1.0)."""
        assert "time.sleep(1.0)" in source

    def test_relative_call(self, source: str) -> None:
        assert 'self.client.get("/Entr1")' in source

    def test_no_absolute_urls(self, source: str) -> None:
        class_body = source.split("class")[1]
        assert "http://" not in class_body


class TestEdgeCases:
    """Edge cases and error handling."""

    def test_no_reference_task_raises(self) -> None:
        model = parse_lqn_file(str(GROUNDTRUTH / "validation-model.lqn"))
        model.tasks = [t for t in model.tasks if not t.is_reference]
        with pytest.raises(ValueError, match="No reference task"):
            generate_locustfile(model)
