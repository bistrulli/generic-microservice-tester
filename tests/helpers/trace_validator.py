"""Trace validator for LQN activity engine execution traces.

Validates that a trace produced by the engine is a valid execution path
through the activity graph defined in LQN_TASK_CONFIG. Uses simplified
token-based replay inspired by Petri net conformance checking.

This is a test utility, not production code.
"""

from __future__ import annotations


def validate_trace(
    trace: list[dict], config: dict, entry_name: str
) -> tuple[bool, str]:
    """Validate that trace is a valid execution of the activity graph for entry_name.

    Returns (True, "") if valid, (False, "reason") if invalid.

    Rules:
    1. Every 'activity' event must reference a valid activity name
    2. For 'and_fork': all branch names must appear as activities before 'and_join'
    3. For 'or_fork': exactly one 'chosen' branch must appear as activity after fork
    4. 'reply' must be last event and reference the correct entry
    5. Sequence ordering: if A->B in sequences, A must appear before B in trace
    6. Activity service_time_mean must match config
    7. Activity outbound calls must match config (sync_calls, async_calls)
    """
    if not trace:
        return False, "Empty trace"

    entries = config.get("entries", {})
    entry_def = entries.get(entry_name)
    if entry_def is None:
        return False, f"Entry '{entry_name}' not found in config"

    # Phase-based entry: different validation
    if not entry_def.get("start_activity"):
        return _validate_phase_trace(trace, entry_name, entry_def)

    # Activity-based entry: full graph validation
    return _validate_activity_trace(trace, entry_name, config)


def _validate_phase_trace(
    trace: list[dict], entry_name: str, entry_def: dict
) -> tuple[bool, str]:
    """Validate trace for a phase-based entry (no activity diagram)."""
    phase_events = [e for e in trace if e["type"] == "phase_entry"]
    if not phase_events:
        return False, "No phase_entry event in trace"

    pe = phase_events[0]
    if pe["name"] != entry_name:
        return False, f"Phase entry name '{pe['name']}' != expected '{entry_name}'"

    expected_st = entry_def.get("service_time", 0.0)
    if abs(pe.get("service_time_mean", 0.0) - expected_st) > 1e-9:
        return (
            False,
            f"Service time mean {pe.get('service_time_mean')} != expected {expected_st}",
        )

    # Verify sync calls present if configured
    if entry_def.get("sync_calls"):
        sync_events = [e for e in trace if e["type"] == "sync_call"]
        for target in entry_def["sync_calls"]:
            if not any(e["target"] == target for e in sync_events):
                return False, f"Expected sync_call to '{target}' not found in trace"

    # Verify async calls present if configured
    if entry_def.get("async_calls"):
        async_events = [e for e in trace if e["type"] == "async_call"]
        for target in entry_def["async_calls"]:
            if not any(e["target"] == target for e in async_events):
                return False, f"Expected async_call to '{target}' not found in trace"

    # Reply must be last event
    last = trace[-1]
    if last["type"] != "reply":
        return False, f"Phase trace: last event is '{last['type']}', expected 'reply'"
    if last.get("entry") != entry_name:
        return (
            False,
            f"Phase trace: reply entry '{last.get('entry')}' != '{entry_name}'",
        )

    return True, ""


def _validate_activity_trace(
    trace: list[dict], entry_name: str, config: dict
) -> tuple[bool, str]:
    """Validate trace for an activity-based entry with graph traversal."""
    activities = config.get("activities", {})
    graph = config.get("graph", {})

    # --- Rule 1: All activity events reference valid names ---
    valid_names = set(activities.keys())
    for event in trace:
        if event["type"] == "activity":
            name = event["name"]
            if name not in valid_names:
                return False, f"Unknown activity '{name}' in trace"

    # --- Rule 2: AND-fork completeness ---
    ok, msg = _validate_and_forks(trace)
    if not ok:
        return False, msg

    # --- Rule 3: OR-fork exclusivity ---
    ok, msg = _validate_or_forks(trace)
    if not ok:
        return False, msg

    # --- Rule 4: Reply is last event ---
    last = trace[-1]
    if last["type"] != "reply":
        return False, f"Last event is '{last['type']}', expected 'reply'"
    if last.get("entry") != entry_name:
        return (
            False,
            f"Reply entry '{last.get('entry')}' != expected '{entry_name}'",
        )

    # --- Rule 5: Sequence ordering ---
    sequences = graph.get("sequences", [])
    ok, msg = _validate_sequence_order(trace, sequences)
    if not ok:
        return False, msg

    # --- Rule 6: Activity service_time_mean matches config ---
    ok, msg = _validate_service_times(trace, activities)
    if not ok:
        return False, msg

    # --- Rule 7: Activity outbound calls match config ---
    ok, msg = _validate_activity_calls(trace, activities)
    if not ok:
        return False, msg

    return True, ""


def _validate_and_forks(trace: list[dict]) -> tuple[bool, str]:
    """Validate AND-fork: all branches must appear as activities between fork and join."""
    i = 0
    while i < len(trace):
        event = trace[i]
        if event["type"] == "and_fork":
            expected_branches = set(event["branches"])

            # Find the corresponding and_join
            join_idx = None
            for j in range(i + 1, len(trace)):
                if trace[j]["type"] == "and_join":
                    join_branches = set(trace[j]["branches"])
                    if join_branches == expected_branches:
                        join_idx = j
                        break

            if join_idx is None:
                return False, f"AND-fork {expected_branches} has no matching join"

            # Check that all branches appear as activities between fork and join
            between = trace[i + 1 : join_idx]
            executed_branches = {e["name"] for e in between if e["type"] == "activity"}

            missing = expected_branches - executed_branches
            if missing:
                return (
                    False,
                    f"AND-fork missing branches: {missing}. "
                    f"Expected {expected_branches}, got {executed_branches}",
                )
        i += 1

    return True, ""


def _validate_or_forks(trace: list[dict]) -> tuple[bool, str]:
    """Validate OR-fork: exactly one chosen branch must appear after fork."""
    for event in trace:
        if event["type"] != "or_fork":
            continue

        chosen = event["chosen"]
        all_branches = set(event["branches"])
        not_chosen = all_branches - {chosen}

        fork_idx = trace.index(event)
        after_fork = trace[fork_idx + 1 :]

        activity_names_after = {
            e["name"] for e in after_fork if e["type"] == "activity"
        }

        if chosen not in activity_names_after:
            return False, f"OR-fork chose '{chosen}' but it's not in trace after fork"

        for nc in not_chosen:
            for e in after_fork:
                if e["type"] == "activity" and e["name"] == nc and "branch" not in e:
                    return (
                        False,
                        f"OR-fork: non-chosen branch '{nc}' appeared in trace",
                    )

    return True, ""


def _validate_sequence_order(trace: list[dict], sequences: list) -> tuple[bool, str]:
    """Validate that sequence ordering is respected in the trace."""
    activity_positions: dict[str, int] = {}
    for i, event in enumerate(trace):
        if event["type"] == "activity":
            name = event["name"]
            if name not in activity_positions:
                activity_positions[name] = i

    for seq in sequences:
        if isinstance(seq, (list, tuple)) and len(seq) == 2:
            a, b = seq
            if a in activity_positions and b in activity_positions:
                if activity_positions[a] >= activity_positions[b]:
                    return (
                        False,
                        f"Sequence violation: '{a}' (pos {activity_positions[a]}) "
                        f"should come before '{b}' (pos {activity_positions[b]})",
                    )

    return True, ""


def _validate_service_times(trace: list[dict], activities: dict) -> tuple[bool, str]:
    """Validate that activity service_time_mean in trace matches config."""
    for event in trace:
        if event["type"] != "activity":
            continue
        name = event["name"]
        if name not in activities:
            continue
        expected_st = activities[name].get("service_time", 0.0)
        actual_st = event.get("service_time_mean", 0.0)
        if abs(actual_st - expected_st) > 1e-9:
            return (
                False,
                f"Activity '{name}': service_time_mean={actual_st} "
                f"!= config={expected_st}",
            )
    return True, ""


def _validate_activity_calls(trace: list[dict], activities: dict) -> tuple[bool, str]:
    """Validate that outbound calls following each activity match its config.

    For each activity event in the trace, checks that any sync_call/async_call
    events immediately following it (before the next activity/fork/join/reply)
    match the sync_calls/async_calls defined in the activity config.
    """
    for i, event in enumerate(trace):
        if event["type"] != "activity":
            continue

        name = event["name"]
        if name not in activities:
            continue

        act_config = activities[name]
        expected_sync = set(act_config.get("sync_calls", {}).keys())
        expected_async = set(act_config.get("async_calls", {}).keys())

        # Collect call events immediately after this activity
        actual_sync = set()
        actual_async = set()
        for j in range(i + 1, len(trace)):
            next_evt = trace[j]
            if next_evt["type"] == "sync_call":
                actual_sync.add(next_evt["target"])
            elif next_evt["type"] == "async_call":
                actual_async.add(next_evt["target"])
            else:
                # Stop at next non-call event
                break

        # Check expected calls are present
        missing_sync = expected_sync - actual_sync
        if missing_sync:
            return (
                False,
                f"Activity '{name}': missing sync_calls {missing_sync}",
            )

        missing_async = expected_async - actual_async
        if missing_async:
            return (
                False,
                f"Activity '{name}': missing async_calls {missing_async}",
            )

    return True, ""


def validate_and_fork_parallelism(
    trace: list[dict], max_sequential_ratio: float = 0.85
) -> tuple[bool, str]:
    """Validate that AND-fork branches actually executed in parallel using timestamps.

    For each AND-fork in the trace, checks that the branch activity timestamps
    overlap (i.e., branches started concurrently, not sequentially).

    Args:
        trace: Execution trace with timestamp_start/timestamp_end on activities.
        max_sequential_ratio: If wall-clock / sum-of-branches > this, likely sequential.

    Returns (True, "") if parallel, (False, "reason") if sequential.
    """
    for i, event in enumerate(trace):
        if event["type"] != "and_fork":
            continue

        expected_branches = set(event["branches"])

        # Find corresponding join
        join_idx = None
        for j in range(i + 1, len(trace)):
            if trace[j]["type"] == "and_join":
                if set(trace[j]["branches"]) == expected_branches:
                    join_idx = j
                    break

        if join_idx is None:
            return False, f"AND-fork {expected_branches}: no matching join"

        # Collect branch activity timestamps
        between = trace[i + 1 : join_idx]
        branch_activities = [
            e
            for e in between
            if e["type"] == "activity" and e["name"] in expected_branches
        ]

        if len(branch_activities) < 2:
            continue  # Single branch, nothing to check

        # Check timestamp overlap
        starts = [
            a["timestamp_start"] for a in branch_activities if "timestamp_start" in a
        ]
        ends = [a["timestamp_end"] for a in branch_activities if "timestamp_end" in a]

        if not starts or not ends:
            return (
                False,
                f"AND-fork {expected_branches}: missing timestamps on branch activities",
            )

        # Wall-clock for the fork region: from earliest start to latest end
        wall_clock = max(ends) - min(starts)
        # Sum of individual branch durations
        sum_durations = sum(e - s for s, e in zip(starts, ends))

        if sum_durations <= 0:
            continue  # Zero-duration activities, skip

        # If truly parallel: wall_clock ≈ max(durations), much less than sum
        # If sequential: wall_clock ≈ sum(durations)
        ratio = wall_clock / sum_durations
        if ratio > max_sequential_ratio:
            return (
                False,
                f"AND-fork {expected_branches}: appears SEQUENTIAL. "
                f"wall_clock={wall_clock:.4f}s, sum_branches={sum_durations:.4f}s, "
                f"ratio={ratio:.2f} (threshold={max_sequential_ratio})",
            )

    return True, ""
