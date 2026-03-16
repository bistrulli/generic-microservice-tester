"""E2E trace matching: compile ground truth LQN model, execute each entry
in dry-run, collect traces, and validate against the activity graph.

This is the formal verification that the activity engine correctly
interprets the LQN model. Uses trace matching (trace membership in CFG).
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Add src/ and tools/ to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "tools"))
sys.path.insert(0, str(Path(__file__).parent.parent / "helpers"))

import app as gmt_app
from lqn_compiler import build_task_config
from lqn_parser import parse_lqn_file
from trace_validator import validate_and_fork_parallelism, validate_trace

os_module = __import__("os")
os_module.environ.setdefault("SERVICE_NAME", "test-service")

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
        assert 0.89 < ratio < 0.99, (
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


# --- Gap 1: Reply for phase entries ---


class TestPhaseEntryReply:
    def test_notify_ends_with_reply(self, tserver_config):
        """Phase entries must now emit a reply event."""
        trace = []
        gmt_app.execute_activity_graph("notify", tserver_config, trace, dry_run=True)
        assert trace[-1]["type"] == "reply", (
            f"notify trace should end with reply, got: {trace[-1]}"
        )
        assert trace[-1]["entry"] == "notify"

    def test_save_ends_with_reply(self, tserver_config):
        trace = []
        gmt_app.execute_activity_graph("save", tserver_config, trace, dry_run=True)
        assert trace[-1]["type"] == "reply"
        assert trace[-1]["entry"] == "save"


# --- Gap 2: Validate activity outbound calls match config ---


class TestActivityCallsMatchConfig:
    def test_external_activity_has_read_call(self, tserver_config):
        """Activity 'external' in TServer has sync_call to read.
        Validate the trace contains it when external is chosen."""
        import random

        for seed in range(1000):
            random.seed(seed)
            trace = []
            gmt_app.execute_activity_graph("visit", tserver_config, trace, dry_run=True)
            or_fork = next(e for e in trace if e["type"] == "or_fork")
            if or_fork["chosen"] == "external":
                # Validate the full trace including calls
                valid, reason = validate_trace(trace, tserver_config, "visit")
                assert valid, f"Trace invalid: {reason}\nTrace: {trace}"
                # Check sync_call to read is present after external activity
                sync_calls = [e for e in trace if e["type"] == "sync_call"]
                assert len(sync_calls) >= 1, (
                    "external path should have sync_call to read"
                )
                return
        pytest.skip("Could not find seed that selects 'external'")


# --- Gap 3: Validate service_time_mean matches config ---


class TestServiceTimeMeansMatchConfig:
    def test_buy_activities_service_times(self, tserver_config):
        """Service time means in trace must match config values."""
        trace = []
        gmt_app.execute_activity_graph("buy", tserver_config, trace, dry_run=True)
        activities_config = tserver_config["activities"]

        for event in trace:
            if event["type"] != "activity":
                continue
            name = event["name"]
            expected = activities_config[name].get("service_time", 0.0)
            actual = event["service_time_mean"]
            assert actual == pytest.approx(expected), (
                f"Activity '{name}': service_time_mean={actual} != config={expected}"
            )

    def test_visit_cache_service_time(self, tserver_config):
        trace = []
        gmt_app.execute_activity_graph("visit", tserver_config, trace, dry_run=True)
        cache_event = next(
            e for e in trace if e["type"] == "activity" and e["name"] == "cache"
        )
        assert cache_event["service_time_mean"] == pytest.approx(0.001)


# --- Gap 4: AND-fork parallelism verification via timestamps ---


class TestAndForkParallelism:
    """Test AND-fork parallelism using timestamps from REAL execution.

    Uses a custom config with large service times (0.15s per branch)
    to make parallelism clearly observable above thread overhead.
    """

    PARALLEL_CONFIG = {
        "task_name": "TParallel",
        "entries": {"run": {"start_activity": "start"}},
        "activities": {
            "start": {"service_time": 0.0},
            "branch_a": {"service_time": 0.15},
            "branch_b": {"service_time": 0.15},
            "finish": {"service_time": 0.0},
        },
        "graph": {
            "sequences": [],
            "or_forks": [],
            "and_forks": [{"from": "start", "branches": ["branch_a", "branch_b"]}],
            "and_joins": [{"branches": ["branch_a", "branch_b"], "to": "finish"}],
            "replies": {"finish": "run"},
        },
    }

    @patch.object(gmt_app.np.random, "exponential", side_effect=[0.15, 0.15])
    def test_and_fork_parallel_real_execution(self, mock_exp):
        """Run AND-fork with REAL execution, verify branches overlap in time."""
        trace = []
        gmt_app.execute_activity_graph(
            "run", self.PARALLEL_CONFIG, trace, dry_run=False
        )

        valid, reason = validate_and_fork_parallelism(trace)
        assert valid, f"AND-fork not parallel: {reason}"

    @patch.object(gmt_app.np.random, "exponential", side_effect=[0.15, 0.15])
    def test_and_fork_wall_clock_less_than_sum(self, mock_exp):
        """Wall-clock ~0.15s (max), not ~0.30s (sum)."""
        trace = []
        gmt_app.execute_activity_graph(
            "run", self.PARALLEL_CONFIG, trace, dry_run=False
        )

        and_fork = next(e for e in trace if e["type"] == "and_fork")
        and_join = next(e for e in trace if e["type"] == "and_join")
        fork_idx = trace.index(and_fork)
        join_idx = trace.index(and_join)

        between = trace[fork_idx + 1 : join_idx]
        branch_acts = [e for e in between if e["type"] == "activity"]

        starts = [a["timestamp_start"] for a in branch_acts]
        ends = [a["timestamp_end"] for a in branch_acts]
        wall_clock = max(ends) - min(starts)
        sum_durations = sum(e - s for s, e in zip(starts, ends))

        ratio = wall_clock / sum_durations
        assert ratio < 0.75, (
            f"AND-fork appears sequential: wall={wall_clock:.4f}s, "
            f"sum={sum_durations:.4f}s, ratio={ratio:.2f}"
        )

    def test_timestamps_present_on_activities(self, tserver_config):
        """All activity events must have timestamp_start and timestamp_end."""
        trace = []
        gmt_app.execute_activity_graph("buy", tserver_config, trace, dry_run=True)
        for event in trace:
            if event["type"] == "activity":
                assert "timestamp_start" in event, (
                    f"Activity '{event['name']}' missing timestamp_start"
                )
                assert "timestamp_end" in event, (
                    f"Activity '{event['name']}' missing timestamp_end"
                )


# --- Step 2: Independent LQN model anchors (break circular reasoning) ---


class TestLqnModelFidelity:
    """Verify compiled config matches LQN source directly.

    These tests hardcode values from the .lqn file to break the
    circular dependency between compiler, engine, and validator.
    """

    @pytest.fixture()
    def model(self, groundtruth_dir=None):
        if not GROUNDTRUTH.exists():
            pytest.skip("Ground truth not found")
        return parse_lqn_file(str(GROUNDTRUTH))

    def test_tserver_visit_start_activity(self, model):
        tserver = next(t for t in model.tasks if t.name == "TServer")
        visit = next(e for e in tserver.entries if e.name == "visit")
        assert visit.start_activity == "cache"

    def test_tserver_buy_start_activity(self, model):
        tserver = next(t for t in model.tasks if t.name == "TServer")
        buy = next(e for e in tserver.entries if e.name == "buy")
        assert buy.start_activity == "prepare"

    def test_activity_service_times_from_lqn(self, model):
        """Verify service times match LQN source exactly."""
        tserver = next(t for t in model.tasks if t.name == "TServer")
        expected = {
            "prepare": 0.01,
            "pack": 0.03,
            "ship": 0.01,
            "display": 0.001,
            "cache": 0.001,
            "internal": 0.001,
            "external": 0.003,
        }
        for name, expected_st in expected.items():
            assert name in tserver.activities, f"Activity '{name}' not in parser output"
            assert tserver.activities[name].service_time == pytest.approx(
                expected_st
            ), (
                f"Activity '{name}': parsed={tserver.activities[name].service_time}, "
                f"expected={expected_st} from LQN source"
            )

    def test_external_has_sync_call_to_read(self, model):
        tserver = next(t for t in model.tasks if t.name == "TServer")
        ext = tserver.activities["external"]
        assert len(ext.sync_calls) == 1
        assert ext.sync_calls[0] == ("read", 1.0)

    def test_or_fork_probabilities_from_lqn(self, model):
        tserver = next(t for t in model.tasks if t.name == "TServer")
        graph = tserver.activity_graph
        assert len(graph.or_forks) == 1
        source, branches = graph.or_forks[0]
        assert source == "cache"
        probs = {name: prob for prob, name in branches}
        assert probs["internal"] == pytest.approx(0.95)
        assert probs["external"] == pytest.approx(0.05)

    def test_and_fork_branches_from_lqn(self, model):
        tserver = next(t for t in model.tasks if t.name == "TServer")
        graph = tserver.activity_graph
        assert len(graph.and_forks) == 1
        source, branches = graph.and_forks[0]
        assert source == "prepare"
        assert set(branches) == {"pack", "ship"}

    def test_notify_service_time_from_lqn(self, model):
        tserver = next(t for t in model.tasks if t.name == "TServer")
        notify = next(e for e in tserver.entries if e.name == "notify")
        assert notify.phase_service_times == [0.08]

    def test_save_service_time_and_call_from_lqn(self, model):
        tserver = next(t for t in model.tasks if t.name == "TServer")
        save = next(e for e in tserver.entries if e.name == "save")
        assert save.phase_service_times == [0.02]
        assert "write" in save.phase_sync_calls
        assert save.phase_sync_calls["write"] == [1.0]

    def test_compiler_preserves_lqn_values(self, model, tserver_config):
        """Verify compiler output matches parser output for key values."""
        config = tserver_config
        # Activity service times
        assert config["activities"]["pack"]["service_time"] == pytest.approx(0.03)
        assert config["activities"]["cache"]["service_time"] == pytest.approx(0.001)
        # OR-fork probabilities
        or_fork = config["graph"]["or_forks"][0]
        probs = {b["to"]: b["prob"] for b in or_fork["branches"]}
        assert probs["internal"] == pytest.approx(0.95)
        # AND-fork structure
        and_fork = config["graph"]["and_forks"][0]
        assert set(and_fork["branches"]) == {"pack", "ship"}
        # Replies
        assert config["graph"]["replies"]["display"] == "buy"
        assert config["graph"]["replies"]["internal"] == "visit"
