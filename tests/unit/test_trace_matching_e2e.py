"""E2E trace matching: compile ground truth LQN model, execute each entry
in dry-run, collect traces, and validate against the activity graph.

This is the formal verification that the activity engine correctly
interprets the LQN model. Uses trace matching (trace membership in CFG).
"""

import sys
from pathlib import Path

import pytest

# Add src/ and tools/ to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "tools"))
sys.path.insert(0, str(Path(__file__).parent.parent / "helpers"))

import app as gmt_app
from lqn_compiler import build_task_config
from lqn_parser import parse_lqn_file
from trace_validator import validate_trace

GROUNDTRUTH = (
    Path(__file__).parent.parent.parent
    / "test"
    / "lqn-groundtruth"
    / "template_annotated.lqn"
)


@pytest.fixture(scope="module")
def tserver_config():
    """Build LQN_TASK_CONFIG for TServer from ground truth model."""
    if not GROUNDTRUTH.exists():
        pytest.skip(f"Ground truth not found: {GROUNDTRUTH}")
    model = parse_lqn_file(str(GROUNDTRUTH))
    tserver = next(t for t in model.tasks if t.name == "TServer")
    return build_task_config(tserver, model)


@pytest.fixture(autouse=True)
def _reset_config():
    gmt_app._LQN_TASK_CONFIG = None
    gmt_app._LQN_CONFIG_LOADED = False
    yield
    gmt_app._LQN_TASK_CONFIG = None
    gmt_app._LQN_CONFIG_LOADED = False


# --- Entry: visit (OR-fork: cache -> internal/external -> reply) ---


class TestTraceMatchingVisit:
    def test_visit_trace_valid(self, tserver_config):
        """Single run: trace for 'visit' must be a valid path through CFG."""
        trace = []
        gmt_app.execute_activity_graph("visit", tserver_config, trace, dry_run=True)
        valid, reason = validate_trace(trace, tserver_config, "visit")
        assert valid, f"Trace invalid: {reason}\nTrace: {trace}"

    def test_visit_starts_with_cache(self, tserver_config):
        """First activity must be 'cache' (start_activity for visit)."""
        trace = []
        gmt_app.execute_activity_graph("visit", tserver_config, trace, dry_run=True)
        first_activity = next(e for e in trace if e["type"] == "activity")
        assert first_activity["name"] == "cache"

    def test_visit_has_or_fork(self, tserver_config):
        """Trace must contain OR-fork from cache."""
        trace = []
        gmt_app.execute_activity_graph("visit", tserver_config, trace, dry_run=True)
        or_forks = [e for e in trace if e["type"] == "or_fork"]
        assert len(or_forks) == 1
        assert or_forks[0]["from"] == "cache"
        assert or_forks[0]["chosen"] in ("internal", "external")

    def test_visit_ends_with_reply(self, tserver_config):
        """Trace must end with reply to 'visit'."""
        trace = []
        gmt_app.execute_activity_graph("visit", tserver_config, trace, dry_run=True)
        assert trace[-1]["type"] == "reply"
        assert trace[-1]["entry"] == "visit"

    def test_visit_multiple_runs_probability(self, tserver_config):
        """Over 100 runs, ~95% should choose 'internal', ~5% 'external'."""
        choices = {"internal": 0, "external": 0}
        for _ in range(200):
            trace = []
            gmt_app.execute_activity_graph("visit", tserver_config, trace, dry_run=True)
            or_fork = next(e for e in trace if e["type"] == "or_fork")
            choices[or_fork["chosen"]] += 1

        ratio = choices["internal"] / 200
        assert 0.85 < ratio < 1.0, (
            f"Internal ratio {ratio:.2f} not close to 0.95. Counts: {choices}"
        )


# --- Entry: buy (AND-fork: prepare -> pack & ship -> display -> reply) ---


class TestTraceMatchingBuy:
    def test_buy_trace_valid(self, tserver_config):
        """Single run: trace for 'buy' must be a valid path through CFG."""
        trace = []
        gmt_app.execute_activity_graph("buy", tserver_config, trace, dry_run=True)
        valid, reason = validate_trace(trace, tserver_config, "buy")
        assert valid, f"Trace invalid: {reason}\nTrace: {trace}"

    def test_buy_has_and_fork(self, tserver_config):
        """Trace must contain AND-fork with pack and ship."""
        trace = []
        gmt_app.execute_activity_graph("buy", tserver_config, trace, dry_run=True)
        and_forks = [e for e in trace if e["type"] == "and_fork"]
        assert len(and_forks) == 1
        assert set(and_forks[0]["branches"]) == {"pack", "ship"}

    def test_buy_has_and_join(self, tserver_config):
        """Trace must contain AND-join leading to display."""
        trace = []
        gmt_app.execute_activity_graph("buy", tserver_config, trace, dry_run=True)
        and_joins = [e for e in trace if e["type"] == "and_join"]
        assert len(and_joins) == 1
        assert and_joins[0]["to"] == "display"

    def test_buy_both_branches_executed(self, tserver_config):
        """Both pack and ship must appear as activities."""
        trace = []
        gmt_app.execute_activity_graph("buy", tserver_config, trace, dry_run=True)
        activity_names = {e["name"] for e in trace if e["type"] == "activity"}
        assert "pack" in activity_names, f"pack missing. Activities: {activity_names}"
        assert "ship" in activity_names, f"ship missing. Activities: {activity_names}"

    def test_buy_prepare_before_fork(self, tserver_config):
        """prepare must execute before AND-fork."""
        trace = []
        gmt_app.execute_activity_graph("buy", tserver_config, trace, dry_run=True)
        prepare_idx = next(
            i
            for i, e in enumerate(trace)
            if e["type"] == "activity" and e["name"] == "prepare"
        )
        fork_idx = next(i for i, e in enumerate(trace) if e["type"] == "and_fork")
        assert prepare_idx < fork_idx

    def test_buy_display_after_join(self, tserver_config):
        """display must execute after AND-join."""
        trace = []
        gmt_app.execute_activity_graph("buy", tserver_config, trace, dry_run=True)
        join_idx = next(i for i, e in enumerate(trace) if e["type"] == "and_join")
        display_idx = next(
            i
            for i, e in enumerate(trace)
            if e["type"] == "activity" and e["name"] == "display"
        )
        assert display_idx > join_idx

    def test_buy_ends_with_reply(self, tserver_config):
        trace = []
        gmt_app.execute_activity_graph("buy", tserver_config, trace, dry_run=True)
        assert trace[-1]["type"] == "reply"
        assert trace[-1]["entry"] == "buy"


# --- Entry: notify (phase-based, service time only) ---


class TestTraceMatchingNotify:
    def test_notify_trace_valid(self, tserver_config):
        trace = []
        gmt_app.execute_activity_graph("notify", tserver_config, trace, dry_run=True)
        valid, reason = validate_trace(trace, tserver_config, "notify")
        assert valid, f"Trace invalid: {reason}\nTrace: {trace}"

    def test_notify_is_phase_entry(self, tserver_config):
        trace = []
        gmt_app.execute_activity_graph("notify", tserver_config, trace, dry_run=True)
        phase_events = [e for e in trace if e["type"] == "phase_entry"]
        assert len(phase_events) == 1
        assert phase_events[0]["name"] == "notify"
        assert phase_events[0]["service_time_mean"] == 0.08


# --- Entry: save (phase-based with sync call to write) ---


class TestTraceMatchingSave:
    def test_save_trace_valid(self, tserver_config):
        trace = []
        gmt_app.execute_activity_graph("save", tserver_config, trace, dry_run=True)
        valid, reason = validate_trace(trace, tserver_config, "save")
        assert valid, f"Trace invalid: {reason}\nTrace: {trace}"

    def test_save_has_sync_call(self, tserver_config):
        """save entry must make a sync call to write."""
        trace = []
        gmt_app.execute_activity_graph("save", tserver_config, trace, dry_run=True)
        sync_calls = [e for e in trace if e["type"] == "sync_call"]
        assert len(sync_calls) >= 1
        targets = {e["target"] for e in sync_calls}
        assert any("write" in t for t in targets), (
            f"Expected sync_call to 'write', got: {targets}"
        )
