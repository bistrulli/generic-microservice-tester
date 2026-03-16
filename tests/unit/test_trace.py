"""Tests for execution tracing and dry-run mode in the LQN activity engine.

Verifies that trace events are recorded correctly for each construct
(activity, AND-fork/join, OR-fork, reply, calls, phase entries) and
that dry-run mode skips CPU work and HTTP calls.
"""

import os
import random
import sys
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

os.environ.setdefault("SERVICE_NAME", "test-service")

import app as gmt_app


# --- Fixtures ---

import pytest


@pytest.fixture(autouse=True)
def _reset_config():
    gmt_app._LQN_TASK_CONFIG = None
    gmt_app._LQN_CONFIG_LOADED = False
    yield
    gmt_app._LQN_TASK_CONFIG = None
    gmt_app._LQN_CONFIG_LOADED = False


# --- Configs for test ---

SIMPLE_ACTIVITY_CONFIG = {
    "task_name": "T1",
    "entries": {"e1": {"start_activity": "work"}},
    "activities": {"work": {"service_time": 0.001}},
    "graph": {
        "sequences": [],
        "or_forks": [],
        "and_forks": [],
        "and_joins": [],
        "replies": {"work": "e1"},
    },
}

OR_FORK_CONFIG = {
    "task_name": "T1",
    "entries": {"visit": {"start_activity": "cache"}},
    "activities": {
        "cache": {"service_time": 0.001},
        "internal": {"service_time": 0.001},
        "external": {"service_time": 0.001},
    },
    "graph": {
        "sequences": [],
        "or_forks": [
            {
                "from": "cache",
                "branches": [
                    {"prob": 0.95, "to": "internal"},
                    {"prob": 0.05, "to": "external"},
                ],
            }
        ],
        "and_forks": [],
        "and_joins": [],
        "replies": {"internal": "visit", "external": "visit"},
    },
}

AND_FORK_CONFIG = {
    "task_name": "T1",
    "entries": {"buy": {"start_activity": "prepare"}},
    "activities": {
        "prepare": {"service_time": 0.0},
        "pack": {"service_time": 0.001},
        "ship": {"service_time": 0.001},
        "display": {"service_time": 0.0},
    },
    "graph": {
        "sequences": [],
        "or_forks": [],
        "and_forks": [{"from": "prepare", "branches": ["pack", "ship"]}],
        "and_joins": [{"branches": ["pack", "ship"], "to": "display"}],
        "replies": {"display": "buy"},
    },
}

PHASE_ENTRY_CONFIG = {
    "task_name": "T1",
    "entries": {
        "notify": {"service_time": 0.001},
    },
    "activities": {},
    "graph": {},
}

CALL_CONFIG = {
    "task_name": "T1",
    "entries": {"save": {"start_activity": "do_save"}},
    "activities": {
        "do_save": {
            "service_time": 0.0,
            "sync_calls": {"backend-svc/write": 1.0},
            "async_calls": {"logger-svc/log": 1.0},
        },
    },
    "graph": {
        "sequences": [],
        "or_forks": [],
        "and_forks": [],
        "and_joins": [],
        "replies": {"do_save": "save"},
    },
}


# --- Trace recording tests ---


class TestTraceActivityRecorded:
    def test_activity_in_trace(self):
        trace = []
        gmt_app.execute_activity_graph(
            "e1", SIMPLE_ACTIVITY_CONFIG, trace, dry_run=True
        )
        activity_events = [e for e in trace if e["type"] == "activity"]
        assert len(activity_events) >= 1
        assert activity_events[0]["name"] == "work"

    def test_activity_has_service_time_fields(self):
        trace = []
        gmt_app.execute_activity_graph(
            "e1", SIMPLE_ACTIVITY_CONFIG, trace, dry_run=True
        )
        act = next(e for e in trace if e["type"] == "activity")
        assert "service_time_mean" in act
        assert "service_time_sampled" in act


class TestTraceAndForkRecorded:
    def test_and_fork_events(self):
        trace = []
        gmt_app.execute_activity_graph("buy", AND_FORK_CONFIG, trace, dry_run=True)
        types = [e["type"] for e in trace]
        assert "and_fork" in types
        assert "and_join" in types

    def test_and_fork_branches_in_trace(self):
        trace = []
        gmt_app.execute_activity_graph("buy", AND_FORK_CONFIG, trace, dry_run=True)
        fork_event = next(e for e in trace if e["type"] == "and_fork")
        assert set(fork_event["branches"]) == {"pack", "ship"}

    def test_and_fork_branch_activities_present(self):
        trace = []
        gmt_app.execute_activity_graph("buy", AND_FORK_CONFIG, trace, dry_run=True)
        activity_names = {e["name"] for e in trace if e["type"] == "activity"}
        assert "pack" in activity_names
        assert "ship" in activity_names

    def test_and_join_to_field(self):
        trace = []
        gmt_app.execute_activity_graph("buy", AND_FORK_CONFIG, trace, dry_run=True)
        join_event = next(e for e in trace if e["type"] == "and_join")
        assert join_event["to"] == "display"


class TestTraceOrForkRecorded:
    def test_or_fork_event(self):
        trace = []
        gmt_app.execute_activity_graph("visit", OR_FORK_CONFIG, trace, dry_run=True)
        or_events = [e for e in trace if e["type"] == "or_fork"]
        assert len(or_events) == 1
        assert or_events[0]["from"] == "cache"
        assert or_events[0]["chosen"] in ("internal", "external")
        assert set(or_events[0]["branches"]) == {"internal", "external"}


class TestTraceReplyRecorded:
    def test_reply_is_last_event(self):
        trace = []
        gmt_app.execute_activity_graph(
            "e1", SIMPLE_ACTIVITY_CONFIG, trace, dry_run=True
        )
        assert trace[-1]["type"] == "reply"
        assert trace[-1]["entry"] == "e1"

    def test_reply_for_or_fork(self):
        trace = []
        gmt_app.execute_activity_graph("visit", OR_FORK_CONFIG, trace, dry_run=True)
        assert trace[-1]["type"] == "reply"
        assert trace[-1]["entry"] == "visit"

    def test_reply_for_and_fork(self):
        trace = []
        gmt_app.execute_activity_graph("buy", AND_FORK_CONFIG, trace, dry_run=True)
        assert trace[-1]["type"] == "reply"
        assert trace[-1]["entry"] == "buy"


class TestTracePhaseEntryRecorded:
    def test_phase_entry_event(self):
        trace = []
        gmt_app.execute_activity_graph(
            "notify", PHASE_ENTRY_CONFIG, trace, dry_run=True
        )
        phase_events = [e for e in trace if e["type"] == "phase_entry"]
        assert len(phase_events) == 1
        assert phase_events[0]["name"] == "notify"


class TestTraceCallsRecorded:
    def test_sync_call_in_trace(self):
        trace = []
        gmt_app.execute_activity_graph("save", CALL_CONFIG, trace, dry_run=True)
        sync_events = [e for e in trace if e["type"] == "sync_call"]
        assert len(sync_events) >= 1
        assert sync_events[0]["target"] == "backend-svc/write"

    def test_async_call_in_trace(self):
        trace = []
        gmt_app.execute_activity_graph("save", CALL_CONFIG, trace, dry_run=True)
        async_events = [e for e in trace if e["type"] == "async_call"]
        assert len(async_events) >= 1
        assert async_events[0]["target"] == "logger-svc/log"


# --- Dry-run tests ---


class TestDryRunNoCpu:
    def test_dry_run_instant(self):
        """Dry-run should complete almost instantly (no CPU busy-wait)."""
        config = {
            "task_name": "T1",
            "entries": {"e1": {"start_activity": "heavy"}},
            "activities": {"heavy": {"service_time": 10.0}},
            "graph": {
                "sequences": [],
                "or_forks": [],
                "and_forks": [],
                "and_joins": [],
                "replies": {"heavy": "e1"},
            },
        }
        trace = []
        start = time.monotonic()
        gmt_app.execute_activity_graph("e1", config, trace, dry_run=True)
        elapsed = time.monotonic() - start
        assert elapsed < 0.5, f"Dry-run took {elapsed:.3f}s — should be instant"


class TestDryRunNoHttp:
    @patch.object(gmt_app, "make_call")
    @patch.object(gmt_app, "make_async_call_pooled")
    def test_no_http_calls_in_dry_run(self, mock_async, mock_sync):
        trace = []
        gmt_app.execute_activity_graph("save", CALL_CONFIG, trace, dry_run=True)
        mock_sync.assert_not_called()
        mock_async.assert_not_called()


class TestDryRunDeterministic:
    def test_two_runs_same_structure(self):
        """Two dry-runs produce traces with same event types and activity names."""
        random.seed(42)
        trace1 = []
        gmt_app.execute_activity_graph("buy", AND_FORK_CONFIG, trace1, dry_run=True)

        random.seed(42)
        trace2 = []
        gmt_app.execute_activity_graph("buy", AND_FORK_CONFIG, trace2, dry_run=True)

        types1 = [(e["type"], e.get("name", e.get("from", ""))) for e in trace1]
        types2 = [(e["type"], e.get("name", e.get("from", ""))) for e in trace2]
        assert types1 == types2


# --- Regression: existing functionality not broken ---


class TestNoTraceBackwardCompat:
    def test_execute_activity_no_trace(self):
        """Calling without trace/dry_run still works (backward compat)."""
        config = {"activities": {"w": {"service_time": 0.0}}}
        results = gmt_app.execute_activity("w", config)
        assert isinstance(results, list)

    def test_execute_activity_graph_no_trace(self):
        config = {
            "entries": {"e": {"service_time": 0.0}},
            "activities": {},
            "graph": {},
        }
        results = gmt_app.execute_activity_graph("e", config)
        assert isinstance(results, list)
