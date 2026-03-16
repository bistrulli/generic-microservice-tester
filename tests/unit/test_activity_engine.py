"""Tests for the LQN Activity Engine in app.py.

Tests cover: LQN_TASK_CONFIG loading, activity execution, AND-fork/join,
OR-fork, sequences, reply semantics, mean-calls, and legacy compatibility.
"""

import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

# Add src/ to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

# Must set env before importing app to avoid side effects
os.environ.setdefault("SERVICE_NAME", "test-service")

import app as gmt_app


@pytest.fixture(autouse=True)
def _reset_config_cache():
    """Reset the cached LQN config between tests."""
    gmt_app._LQN_TASK_CONFIG = None
    gmt_app._LQN_CONFIG_LOADED = False
    yield
    gmt_app._LQN_TASK_CONFIG = None
    gmt_app._LQN_CONFIG_LOADED = False


@pytest.fixture()
def client():
    """Flask test client."""
    gmt_app.app.config["TESTING"] = True
    with gmt_app.app.test_client() as c:
        yield c


SIMPLE_CONFIG = {
    "task_name": "TSimple",
    "entries": {
        "hello": {"service_time": 0.001},
    },
    "activities": {},
    "graph": {},
}

MULTI_ENTRY_CONFIG = {
    "task_name": "TServer",
    "entries": {
        "visit": {"start_activity": "cache"},
        "buy": {"start_activity": "prepare"},
        "notify": {"service_time": 0.001},
    },
    "activities": {
        "cache": {"service_time": 0.001},
        "internal": {"service_time": 0.001},
        "external": {"service_time": 0.001},
        "prepare": {"service_time": 0.001},
        "pack": {"service_time": 0.001},
        "ship": {"service_time": 0.001},
        "display": {"service_time": 0.001},
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
        "and_forks": [{"from": "prepare", "branches": ["pack", "ship"]}],
        "and_joins": [{"branches": ["pack", "ship"], "to": "display"}],
        "replies": {
            "internal": "visit",
            "external": "visit",
            "display": "buy",
        },
    },
}


class TestLoadTaskConfig:
    def test_returns_none_when_not_set(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LQN_TASK_CONFIG", None)
            result = gmt_app.load_task_config()
            assert result is None

    def test_loads_valid_json(self):
        config = {"task_name": "Test", "entries": {}}
        with patch.dict(os.environ, {"LQN_TASK_CONFIG": json.dumps(config)}):
            result = gmt_app.load_task_config()
            assert result is not None
            assert result["task_name"] == "Test"

    def test_returns_none_on_invalid_json(self):
        with patch.dict(os.environ, {"LQN_TASK_CONFIG": "not json"}):
            result = gmt_app.load_task_config()
            assert result is None


class TestDoBusyWait:
    def test_zero_returns_zero(self):
        result = gmt_app.do_busy_wait(0.0)
        assert result == 0.0

    def test_negative_returns_zero(self):
        result = gmt_app.do_busy_wait(-1.0)
        assert result == 0.0

    def test_exponential_distribution(self):
        """10k samples in dry-run: mean and variance must match Exp(0.05)."""
        mean_param = 0.05
        samples = [gmt_app.do_busy_wait(mean_param, dry_run=True) for _ in range(10000)]
        mean = sum(samples) / len(samples)
        variance = sum((s - mean) ** 2 for s in samples) / len(samples)
        # Exponential: E[X] = lambda, Var[X] = lambda^2
        assert 0.045 < mean < 0.055, f"Mean {mean:.4f} not close to {mean_param}"
        assert 0.0015 < variance < 0.004, (
            f"Variance {variance:.5f} not close to {mean_param**2} = 0.0025"
        )
        assert all(s > 0 for s in samples), "All samples must be positive"


class TestExecuteMeanCalls:
    @patch.object(gmt_app, "make_call")
    def test_integer_calls(self, mock_call):
        mock_call.return_value = {"service": "svc", "status": 200}
        results = gmt_app.execute_mean_calls("svc", 3.0, "SYNC")
        assert mock_call.call_count == 3
        assert len(results) == 3

    @patch.object(gmt_app, "make_call")
    def test_fractional_calls_statistical(self, mock_call):
        """1.2 mean calls → always 1, sometimes 2. Over 1000 runs, avg ≈ 1.2."""
        mock_call.return_value = {"service": "svc", "status": 200}
        total_calls = 0
        n_trials = 1000
        for _ in range(n_trials):
            mock_call.reset_mock()
            gmt_app.execute_mean_calls("svc", 1.2, "SYNC")
            total_calls += mock_call.call_count

        avg = total_calls / n_trials
        assert 1.13 < avg < 1.27, f"Average calls {avg} not close to 1.2"

    @patch.object(gmt_app, "make_async_call_pooled")
    def test_async_calls(self, mock_async):
        results = gmt_app.execute_mean_calls("svc", 2.0, "ASYNC")
        assert mock_async.call_count == 2
        assert all(r["status"] == "async_pooled" for r in results)


class TestExecuteActivity:
    @patch.object(gmt_app.np.random, "exponential", return_value=0.05)
    def test_activity_with_service_time(self, mock_exp):
        config = {
            "activities": {"work": {"service_time": 0.05}},
        }
        start = time.monotonic()
        results = gmt_app.execute_activity("work", config)
        elapsed = time.monotonic() - start
        assert elapsed >= 0.03
        assert isinstance(results, list)

    @patch.object(gmt_app, "make_call")
    def test_activity_with_sync_call(self, mock_call):
        mock_call.return_value = {"service": "backend", "status": 200}
        config = {
            "activities": {
                "work": {
                    "service_time": 0.0,
                    "sync_calls": {"backend-svc": 1.0},
                }
            },
        }
        results = gmt_app.execute_activity("work", config)
        assert mock_call.call_count == 1
        assert len(results) == 1

    @patch.object(gmt_app, "make_async_call_pooled")
    def test_activity_with_async_call(self, mock_async):
        config = {
            "activities": {
                "log_it": {
                    "service_time": 0.0,
                    "async_calls": {"logger-svc": 1.0},
                }
            },
        }
        gmt_app.execute_activity("log_it", config)
        assert mock_async.call_count == 1


class TestExecuteAndFork:
    @patch.object(gmt_app.np.random, "exponential", side_effect=[0.15, 0.30])
    def test_and_fork_parallel_timing(self, mock_exp):
        """AND-fork with two branches should take ~max(times), not sum.

        Uses mocked exponential to get deterministic service times:
        fast=0.15s, slow=0.30s. Parallel → ~0.30s, serial → ~0.45s.
        """
        config = {
            "activities": {
                "fast": {"service_time": 0.15},
                "slow": {"service_time": 0.30},
            },
        }
        start = time.monotonic()
        results = gmt_app.execute_and_fork(["fast", "slow"], config)
        elapsed = time.monotonic() - start

        # If parallel: ~0.30s. If serial: ~0.45s
        assert elapsed < 0.40, (
            f"AND-fork took {elapsed:.3f}s, expected < 0.40s (parallel)"
        )
        assert elapsed >= 0.12, f"AND-fork too fast: {elapsed:.3f}s"
        assert isinstance(results, list)


class TestExecuteOrFork:
    def test_or_fork_chooses_one(self):
        config = {
            "activities": {
                "a": {"service_time": 0.0},
                "b": {"service_time": 0.0},
            },
        }
        branches = [{"prob": 0.5, "to": "a"}, {"prob": 0.5, "to": "b"}]
        chosen, results = gmt_app.execute_or_fork("src", branches, config)
        assert chosen in ("a", "b")

    def test_or_fork_probability_distribution(self):
        """Over many runs, 95/5 split should be approximately correct."""
        config = {
            "activities": {
                "common": {"service_time": 0.0},
                "rare": {"service_time": 0.0},
            },
        }
        branches = [{"prob": 0.95, "to": "common"}, {"prob": 0.05, "to": "rare"}]
        counts = {"common": 0, "rare": 0}

        for _ in range(500):
            chosen, _ = gmt_app.execute_or_fork("src", branches, config)
            counts[chosen] += 1

        ratio = counts["common"] / 500
        assert 0.90 < ratio < 0.99, f"Common ratio {ratio} not close to 0.95"


class TestExecuteActivityGraph:
    @patch.object(gmt_app.np.random, "exponential", return_value=0.05)
    def test_phase_entry(self, mock_exp):
        """Phase-based entry (no activity diagram) executes service time."""
        config = {
            "entries": {"notify": {"service_time": 0.05}},
            "activities": {},
            "graph": {},
        }
        start = time.monotonic()
        gmt_app.execute_activity_graph("notify", config)
        elapsed = time.monotonic() - start
        assert elapsed >= 0.03

    def test_or_fork_graph(self):
        """Activity graph with OR-fork follows one branch."""
        config = {
            "entries": {"visit": {"start_activity": "cache"}},
            "activities": {
                "cache": {"service_time": 0.0},
                "internal": {"service_time": 0.0},
                "external": {"service_time": 0.0},
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
        results = gmt_app.execute_activity_graph("visit", config)
        assert isinstance(results, list)

    @patch.object(gmt_app.np.random, "exponential", side_effect=[0.0, 0.15, 0.15, 0.0])
    def test_and_fork_join_graph(self, mock_exp):
        """Activity graph with AND-fork/join executes branches in parallel.

        Mocked: prepare=0, pack=0.15, ship=0.15, display=0.
        Parallel → ~0.15s, serial → ~0.30s.
        """
        config = {
            "entries": {"buy": {"start_activity": "prepare"}},
            "activities": {
                "prepare": {"service_time": 0.0},
                "pack": {"service_time": 0.15},
                "ship": {"service_time": 0.15},
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
        start = time.monotonic()
        gmt_app.execute_activity_graph("buy", config)
        elapsed = time.monotonic() - start
        # Two 150ms branches in parallel → ~0.15s, serial → ~0.30s
        assert elapsed < 0.25, f"AND-fork/join took {elapsed:.3f}s (should be ~0.15)"


class TestHandleRequestLegacyCompat:
    def test_legacy_without_lqn_config(self, client):
        """Without LQN_TASK_CONFIG, should use legacy handler."""
        with patch.dict(os.environ, {"SERVICE_NAME": "legacy-test"}, clear=False):
            os.environ.pop("LQN_TASK_CONFIG", None)
            resp = client.get("/")
            assert resp.status_code == 200
            data = resp.get_json()
            assert "Response from legacy-test" in data["message"]


class TestHandleRequestEntryRouting:
    def test_entry_routing(self, client):
        """GET /<entry_name> routes to correct entry."""
        with patch.dict(
            os.environ,
            {"LQN_TASK_CONFIG": json.dumps(SIMPLE_CONFIG)},
            clear=False,
        ):
            resp = client.get("/hello")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["entry"] == "hello"

    def test_unknown_entry_returns_404(self, client):
        with patch.dict(
            os.environ,
            {"LQN_TASK_CONFIG": json.dumps(SIMPLE_CONFIG)},
            clear=False,
        ):
            resp = client.get("/nonexistent")
            assert resp.status_code == 404

    def test_default_entry(self, client):
        """GET / with LQN config uses first entry."""
        with patch.dict(
            os.environ,
            {"LQN_TASK_CONFIG": json.dumps(SIMPLE_CONFIG)},
            clear=False,
        ):
            resp = client.get("/")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["entry"] == "hello"


class TestCycleDetection:
    def test_cycle_raises_error(self):
        """Graph with cycle must raise RuntimeError, not hang."""
        config = {
            "entries": {"e": {"start_activity": "a"}},
            "activities": {"a": {"service_time": 0.0}, "b": {"service_time": 0.0}},
            "graph": {
                "sequences": [["a", "b"], ["b", "a"]],
                "or_forks": [],
                "and_forks": [],
                "and_joins": [],
                "replies": {},
            },
        }
        with pytest.raises(RuntimeError, match="[Cc]ycle"):
            gmt_app.execute_activity_graph("e", config, dry_run=True)

    def test_cycle_through_fork_point_raises_error(self):
        """Cycle through an AND-fork source must also be detected."""
        config = {
            "entries": {"e": {"start_activity": "a"}},
            "activities": {
                "a": {"service_time": 0.0},
                "b": {"service_time": 0.0},
                "c": {"service_time": 0.0},
            },
            "graph": {
                "sequences": [],
                "or_forks": [],
                "and_forks": [{"from": "a", "branches": ["b", "c"]}],
                "and_joins": [{"branches": ["b", "c"], "to": "a"}],  # joins back to a!
                "replies": {},
            },
        }
        with pytest.raises(RuntimeError, match="[Cc]ycle|max iterations"):
            gmt_app.execute_activity_graph("e", config, dry_run=True)
