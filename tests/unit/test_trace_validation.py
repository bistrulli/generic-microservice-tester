"""Tests for the trace validator utility.

Verifies that validate_trace correctly accepts valid traces and
rejects invalid ones for each LQN construct.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "helpers"))

from trace_validator import validate_trace

# --- Simple configs for testing ---

SEQUENCE_CONFIG = {
    "entries": {"e1": {"start_activity": "a"}},
    "activities": {"a": {"service_time": 0.01}, "b": {"service_time": 0.02}},
    "graph": {
        "sequences": [["a", "b"]],
        "or_forks": [],
        "and_forks": [],
        "and_joins": [],
        "replies": {"b": "e1"},
    },
}

AND_FORK_CONFIG = {
    "entries": {"buy": {"start_activity": "prepare"}},
    "activities": {
        "prepare": {},
        "pack": {},
        "ship": {},
        "display": {},
    },
    "graph": {
        "sequences": [],
        "or_forks": [],
        "and_forks": [{"from": "prepare", "branches": ["pack", "ship"]}],
        "and_joins": [{"branches": ["pack", "ship"], "to": "display"}],
        "replies": {"display": "buy"},
    },
}

OR_FORK_CONFIG = {
    "entries": {"visit": {"start_activity": "cache"}},
    "activities": {
        "cache": {},
        "internal": {},
        "external": {},
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

PHASE_CONFIG = {
    "entries": {"notify": {"service_time": 0.08}},
    "activities": {},
    "graph": {},
}

PHASE_CALL_CONFIG = {
    "entries": {
        "save": {
            "service_time": 0.02,
            "sync_calls": {"backend-svc/write": 1.0},
        }
    },
    "activities": {},
    "graph": {},
}


# --- Valid trace tests ---


class TestValidateSimpleSequence:
    def test_valid_sequence(self):
        trace = [
            {
                "type": "activity",
                "name": "a",
                "service_time_mean": 0.01,
                "service_time_sampled": 0.01,
            },
            {
                "type": "activity",
                "name": "b",
                "service_time_mean": 0.02,
                "service_time_sampled": 0.02,
            },
            {"type": "reply", "activity": "b", "entry": "e1"},
        ]
        valid, reason = validate_trace(trace, SEQUENCE_CONFIG, "e1")
        assert valid, reason


class TestValidateAndFork:
    def test_valid_and_fork(self):
        trace = [
            {"type": "activity", "name": "prepare"},
            {"type": "and_fork", "branches": ["pack", "ship"]},
            {"type": "activity", "name": "pack"},
            {"type": "activity", "name": "ship"},
            {"type": "and_join", "branches": ["pack", "ship"], "to": "display"},
            {"type": "activity", "name": "display"},
            {"type": "reply", "activity": "display", "entry": "buy"},
        ]
        valid, reason = validate_trace(trace, AND_FORK_CONFIG, "buy")
        assert valid, reason

    def test_valid_and_fork_reversed_order(self):
        """Branches can appear in any order."""
        trace = [
            {"type": "activity", "name": "prepare"},
            {"type": "and_fork", "branches": ["pack", "ship"]},
            {"type": "activity", "name": "ship"},
            {"type": "activity", "name": "pack"},
            {"type": "and_join", "branches": ["pack", "ship"], "to": "display"},
            {"type": "activity", "name": "display"},
            {"type": "reply", "activity": "display", "entry": "buy"},
        ]
        valid, reason = validate_trace(trace, AND_FORK_CONFIG, "buy")
        assert valid, reason


class TestValidateAndForkMissingBranch:
    def test_missing_branch_invalid(self):
        trace = [
            {"type": "activity", "name": "prepare"},
            {"type": "and_fork", "branches": ["pack", "ship"]},
            {"type": "activity", "name": "pack"},
            # ship missing!
            {"type": "and_join", "branches": ["pack", "ship"], "to": "display"},
            {"type": "activity", "name": "display"},
            {"type": "reply", "activity": "display", "entry": "buy"},
        ]
        valid, reason = validate_trace(trace, AND_FORK_CONFIG, "buy")
        assert not valid
        assert "missing" in reason.lower()


class TestValidateOrFork:
    def test_valid_or_fork_internal(self):
        trace = [
            {"type": "activity", "name": "cache"},
            {
                "type": "or_fork",
                "from": "cache",
                "chosen": "internal",
                "branches": ["internal", "external"],
            },
            {"type": "activity", "name": "internal"},
            {"type": "reply", "activity": "internal", "entry": "visit"},
        ]
        valid, reason = validate_trace(trace, OR_FORK_CONFIG, "visit")
        assert valid, reason

    def test_valid_or_fork_external(self):
        trace = [
            {"type": "activity", "name": "cache"},
            {
                "type": "or_fork",
                "from": "cache",
                "chosen": "external",
                "branches": ["internal", "external"],
            },
            {"type": "activity", "name": "external"},
            {"type": "reply", "activity": "external", "entry": "visit"},
        ]
        valid, reason = validate_trace(trace, OR_FORK_CONFIG, "visit")
        assert valid, reason


class TestValidateOrForkBothBranches:
    def test_both_branches_invalid(self):
        trace = [
            {"type": "activity", "name": "cache"},
            {
                "type": "or_fork",
                "from": "cache",
                "chosen": "internal",
                "branches": ["internal", "external"],
            },
            {"type": "activity", "name": "internal"},
            {"type": "activity", "name": "external"},  # should NOT be here
            {"type": "reply", "activity": "internal", "entry": "visit"},
        ]
        valid, reason = validate_trace(trace, OR_FORK_CONFIG, "visit")
        assert not valid
        assert "multiple" in reason.lower() or "non-chosen" in reason.lower()


class TestValidateReplyLast:
    def test_reply_not_last_invalid(self):
        trace = [
            {"type": "activity", "name": "a"},
            {"type": "reply", "activity": "a", "entry": "e1"},
            {"type": "activity", "name": "b"},  # after reply!
        ]
        valid, reason = validate_trace(trace, SEQUENCE_CONFIG, "e1")
        assert not valid
        assert "last" in reason.lower() or "reply" in reason.lower()

    def test_wrong_entry_in_reply(self):
        trace = [
            {"type": "activity", "name": "a"},
            {"type": "activity", "name": "b"},
            {"type": "reply", "activity": "b", "entry": "wrong_entry"},
        ]
        valid, reason = validate_trace(trace, SEQUENCE_CONFIG, "e1")
        assert not valid


class TestValidateUnknownActivity:
    def test_unknown_activity_invalid(self):
        trace = [
            {"type": "activity", "name": "unknown_xyz"},
            {"type": "reply", "activity": "unknown_xyz", "entry": "e1"},
        ]
        valid, reason = validate_trace(trace, SEQUENCE_CONFIG, "e1")
        assert not valid
        assert "unknown" in reason.lower()


class TestValidateSequenceOrder:
    def test_wrong_order_invalid(self):
        trace = [
            {"type": "activity", "name": "b"},  # b before a!
            {"type": "activity", "name": "a"},
            {"type": "reply", "activity": "b", "entry": "e1"},
        ]
        valid, reason = validate_trace(trace, SEQUENCE_CONFIG, "e1")
        assert not valid
        assert "sequence" in reason.lower() or "start" in reason.lower()


class TestValidatePhaseEntry:
    def test_valid_phase_entry(self):
        trace = [
            {
                "type": "phase_entry",
                "name": "notify",
                "service_time_mean": 0.08,
                "service_time_sampled": 0.07,
            },
            {"type": "reply", "activity": "notify", "entry": "notify"},
        ]
        valid, reason = validate_trace(trace, PHASE_CONFIG, "notify")
        assert valid, reason

    def test_phase_with_calls(self):
        trace = [
            {
                "type": "phase_entry",
                "name": "save",
                "service_time_mean": 0.02,
                "service_time_sampled": 0.02,
            },
            {"type": "sync_call", "target": "backend-svc/write"},
            {"type": "reply", "activity": "save", "entry": "save"},
        ]
        valid, reason = validate_trace(trace, PHASE_CALL_CONFIG, "save")
        assert valid, reason

    def test_phase_missing_call_invalid(self):
        trace = [
            {
                "type": "phase_entry",
                "name": "save",
                "service_time_mean": 0.02,
                "service_time_sampled": 0.02,
            },
            {"type": "reply", "activity": "save", "entry": "save"},
            # Missing sync_call to backend-svc/write
        ]
        valid, reason = validate_trace(trace, PHASE_CALL_CONFIG, "save")
        assert not valid
        assert "sync_call" in reason.lower() or "backend" in reason.lower()

    def test_phase_missing_reply_invalid(self):
        trace = [
            {
                "type": "phase_entry",
                "name": "notify",
                "service_time_mean": 0.08,
                "service_time_sampled": 0.07,
            },
            # Missing reply!
        ]
        valid, reason = validate_trace(trace, PHASE_CONFIG, "notify")
        assert not valid
        assert "reply" in reason.lower()


class TestValidateStartActivity:
    def test_wrong_start_activity_invalid(self):
        """First activity must be start_activity from config."""
        trace = [
            {"type": "activity", "name": "b", "service_time_mean": 0.02},
            {"type": "activity", "name": "a", "service_time_mean": 0.01},
            {"type": "reply", "activity": "b", "entry": "e1"},
        ]
        valid, reason = validate_trace(trace, SEQUENCE_CONFIG, "e1")
        assert not valid
        assert "first" in reason.lower() or "start" in reason.lower()


class TestValidateCompleteness:
    def test_skipped_activity_invalid(self):
        """Skipping a required activity must be detected."""
        trace = [
            {"type": "activity", "name": "a", "service_time_mean": 0.01},
            # 'b' is required by sequence a->b but is missing
            {"type": "reply", "activity": "b", "entry": "e1"},
        ]
        valid, reason = validate_trace(trace, SEQUENCE_CONFIG, "e1")
        assert not valid
        assert (
            "completeness" in reason.lower()
            or "missing" in reason.lower()
            or "b" in reason.lower()
        )


class TestValidateOrForkModelDriven:
    def test_or_fork_without_event_both_branches_invalid(self):
        """Even without or_fork event, having both branches is invalid."""
        trace = [
            {"type": "activity", "name": "cache"},
            # No or_fork event! But both branches executed
            {"type": "activity", "name": "internal"},
            {"type": "activity", "name": "external"},
            {"type": "reply", "activity": "internal", "entry": "visit"},
        ]
        valid, reason = validate_trace(trace, OR_FORK_CONFIG, "visit")
        assert not valid
        assert "multiple" in reason.lower() or "or-fork" in reason.lower()


class TestValidateMultipleReplies:
    def test_multiple_replies_invalid(self):
        trace = [
            {"type": "activity", "name": "a", "service_time_mean": 0.01},
            {"type": "reply", "activity": "a", "entry": "e1"},
            {"type": "activity", "name": "b", "service_time_mean": 0.02},
            {"type": "reply", "activity": "b", "entry": "e1"},
        ]
        valid, reason = validate_trace(trace, SEQUENCE_CONFIG, "e1")
        assert not valid
        assert "multiple" in reason.lower() or "reply" in reason.lower()


class TestValidateEmptyTrace:
    def test_empty_trace_invalid(self):
        valid, reason = validate_trace([], SEQUENCE_CONFIG, "e1")
        assert not valid
        assert "empty" in reason.lower()
