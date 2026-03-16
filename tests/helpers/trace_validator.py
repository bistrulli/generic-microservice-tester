"""Trace validator for LQN activity engine execution traces.

Model-driven validation: walks the activity graph from start_activity
and verifies the trace matches, rather than reacting to trace events.

This is a test utility, not production code.
"""

from __future__ import annotations


def validate_trace(
    trace: list[dict], config: dict, entry_name: str
) -> tuple[bool, str]:
    """Validate that trace is a valid execution of the activity graph for entry_name.

    Returns (True, "") if valid, (False, "reason") if invalid.
    """
    if not trace:
        return False, "Empty trace"

    entries = config.get("entries", {})
    entry_def = entries.get(entry_name)
    if entry_def is None:
        return False, f"Entry '{entry_name}' not found in config"

    if not entry_def.get("start_activity"):
        return _validate_phase_trace(trace, entry_name, entry_def)

    return _validate_activity_trace(trace, entry_name, config)


def _validate_phase_trace(
    trace: list[dict], entry_name: str, entry_def: dict
) -> tuple[bool, str]:
    """Validate trace for a phase-based entry."""
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

    if entry_def.get("sync_calls"):
        sync_events = [e for e in trace if e["type"] == "sync_call"]
        for target in entry_def["sync_calls"]:
            if not any(e["target"] == target for e in sync_events):
                return False, f"Expected sync_call to '{target}' not found in trace"

    if entry_def.get("async_calls"):
        async_events = [e for e in trace if e["type"] == "async_call"]
        for target in entry_def["async_calls"]:
            if not any(e["target"] == target for e in async_events):
                return False, f"Expected async_call to '{target}' not found in trace"

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
    """Model-driven validation: walk the graph and verify trace matches."""
    activities = config.get("activities", {})
    entries = config.get("entries", {})
    entry_def = entries[entry_name]
    graph = config.get("graph", {})

    start_activity = entry_def["start_activity"]

    # Build graph lookups
    and_forks = {f["from"]: f["branches"] for f in graph.get("and_forks", [])}
    and_joins = {
        tuple(sorted(j["branches"])): j["to"] for j in graph.get("and_joins", [])
    }
    or_forks = {f["from"]: f["branches"] for f in graph.get("or_forks", [])}
    sequences = {}
    for a, b in graph.get("sequences", []):
        sequences[a] = b
    replies = graph.get("replies", {})

    # --- Rule 0: All activity events reference valid names ---
    valid_names = set(activities.keys())
    for event in trace:
        if event["type"] == "activity":
            if event["name"] not in valid_names:
                return False, f"Unknown activity '{event['name']}' in trace"

    # --- Rule 1: First activity must be start_activity ---
    first_activity = _first_activity_event(trace)
    if first_activity is None:
        return False, "No activity event in trace"
    if first_activity["name"] != start_activity:
        return (
            False,
            f"First activity is '{first_activity['name']}', "
            f"expected start_activity '{start_activity}'",
        )

    # --- Rule 2: Reply must be last, only one, correct entry ---
    reply_events = [e for e in trace if e["type"] == "reply"]
    if not reply_events:
        return False, "No reply event in trace"
    if len(reply_events) > 1:
        return False, f"Multiple reply events ({len(reply_events)}), expected 1"
    if trace[-1]["type"] != "reply":
        return False, f"Last event is '{trace[-1]['type']}', expected 'reply'"
    if trace[-1].get("entry") != entry_name:
        return False, f"Reply entry '{trace[-1].get('entry')}' != '{entry_name}'"

    # --- Rule 3: AND-fork completeness ---
    ok, msg = _validate_and_forks(trace)
    if not ok:
        return False, msg

    # --- Rule 4: OR-fork exclusivity (model-driven) ---
    ok, msg = _validate_or_forks_model_driven(trace, or_forks)
    if not ok:
        return False, msg

    # --- Rule 5: Sequence ordering ---
    ok, msg = _validate_sequence_order(trace, graph.get("sequences", []))
    if not ok:
        return False, msg

    # --- Rule 6: Service times match config ---
    ok, msg = _validate_service_times(trace, activities)
    if not ok:
        return False, msg

    # --- Rule 7: Activity completeness (model-driven walk) ---
    ok, msg = _validate_completeness(
        trace,
        entry_name,
        start_activity,
        and_forks,
        and_joins,
        or_forks,
        sequences,
        replies,
    )
    if not ok:
        return False, msg

    # --- Rule 8: Activity calls match config ---
    ok, msg = _validate_activity_calls(trace, activities)
    if not ok:
        return False, msg

    return True, ""


def _first_activity_event(trace: list[dict]) -> dict | None:
    """Return the first event with type 'activity'."""
    for e in trace:
        if e["type"] == "activity":
            return e
    return None


def _validate_and_forks(trace: list[dict]) -> tuple[bool, str]:
    """Validate AND-fork: all branches present between fork and join."""
    i = 0
    while i < len(trace):
        event = trace[i]
        if event["type"] == "and_fork":
            expected_branches = set(event["branches"])

            join_idx = None
            for j in range(i + 1, len(trace)):
                if trace[j]["type"] == "and_join":
                    if set(trace[j]["branches"]) == expected_branches:
                        join_idx = j
                        break

            if join_idx is None:
                return False, f"AND-fork {expected_branches} has no matching join"

            between = trace[i + 1 : join_idx]
            executed = {e["name"] for e in between if e["type"] == "activity"}
            missing = expected_branches - executed
            if missing:
                return (
                    False,
                    f"AND-fork missing branches: {missing}. "
                    f"Expected {expected_branches}, got {executed}",
                )
        i += 1
    return True, ""


def _validate_or_forks_model_driven(
    trace: list[dict], or_forks_config: dict
) -> tuple[bool, str]:
    """Model-driven OR-fork validation.

    For each OR-fork in the CONFIG (not just in the trace), verify that
    exactly one branch was executed. Works even if the engine omits
    the or_fork event.
    """
    trace_activities = {e["name"] for e in trace if e["type"] == "activity"}

    for source, branches in or_forks_config.items():
        branch_names = [b["to"] for b in branches]

        # If the source activity was executed, exactly one branch must be present
        if source not in trace_activities:
            continue

        executed_branches = [b for b in branch_names if b in trace_activities]

        if len(executed_branches) == 0:
            return (
                False,
                f"OR-fork from '{source}': no branch executed. "
                f"Expected one of {branch_names}",
            )
        if len(executed_branches) > 1:
            return (
                False,
                f"OR-fork from '{source}': multiple branches executed: "
                f"{executed_branches}. Expected exactly one of {branch_names}",
            )

        # If or_fork event exists, verify chosen matches
        for evt in trace:
            if evt["type"] == "or_fork" and evt.get("from") == source:
                if evt["chosen"] != executed_branches[0]:
                    return (
                        False,
                        f"OR-fork from '{source}': event says chosen='{evt['chosen']}' "
                        f"but trace has activity '{executed_branches[0]}'",
                    )

    return True, ""


def _validate_sequence_order(trace: list[dict], sequences: list) -> tuple[bool, str]:
    """Validate sequence ordering in trace."""
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
    """Validate activity service_time_mean matches config."""
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
                f"Activity '{name}': service_time_mean={actual_st} != config={expected_st}",
            )
    return True, ""


def _validate_completeness(
    trace: list[dict],
    entry_name: str,
    start_activity: str,
    and_forks: dict,
    and_joins: dict,
    or_forks: dict,
    sequences: dict,
    replies: dict,
) -> tuple[bool, str]:
    """Model-driven completeness: walk the graph and verify all required
    activities appear in the trace.

    For AND-fork: all branches required.
    For OR-fork: exactly one branch (already validated).
    For sequences: both endpoints required.
    """
    trace_activities = {e["name"] for e in trace if e["type"] == "activity"}

    # Walk the graph from start_activity, collecting required activities
    required = set()
    visited = set()

    def walk(current: str) -> None:
        if current in visited:
            return
        visited.add(current)
        required.add(current)

        if current in and_forks:
            for branch in and_forks[current]:
                walk(branch)
            join_key = tuple(sorted(and_forks[current]))
            if join_key in and_joins:
                walk(and_joins[join_key])
            return

        if current in or_forks:
            # OR-fork: walk whichever branch was actually taken
            branches = [b["to"] for b in or_forks[current]]
            taken = [b for b in branches if b in trace_activities]
            for b in taken:
                walk(b)
            return

        if current in replies and replies[current] == entry_name:
            return  # terminal

        if current in sequences:
            walk(sequences[current])

    walk(start_activity)

    missing = required - trace_activities
    if missing:
        return (
            False,
            f"Completeness: activities {missing} required by graph but not in trace",
        )

    return True, ""


def _validate_activity_calls(trace: list[dict], activities: dict) -> tuple[bool, str]:
    """Validate outbound calls for each activity match config.

    Scans all call events following an activity (up to the next activity,
    fork, join, or reply event) and checks against config.
    """
    stop_types = {"activity", "and_fork", "and_join", "or_fork", "reply", "phase_entry"}

    for i, event in enumerate(trace):
        if event["type"] != "activity":
            continue

        name = event["name"]
        if name not in activities:
            continue

        act_config = activities[name]
        expected_sync = set(act_config.get("sync_calls", {}).keys())
        expected_async = set(act_config.get("async_calls", {}).keys())

        if not expected_sync and not expected_async:
            continue

        actual_sync = set()
        actual_async = set()
        for j in range(i + 1, len(trace)):
            t = trace[j]["type"]
            if t == "sync_call":
                actual_sync.add(trace[j]["target"])
            elif t == "async_call":
                actual_async.add(trace[j]["target"])
            elif t in stop_types:
                break

        missing_sync = expected_sync - actual_sync
        if missing_sync:
            return False, f"Activity '{name}': missing sync_calls {missing_sync}"

        missing_async = expected_async - actual_async
        if missing_async:
            return False, f"Activity '{name}': missing async_calls {missing_async}"

    return True, ""


def validate_and_fork_parallelism(
    trace: list[dict], max_sequential_ratio: float = 0.85
) -> tuple[bool, str]:
    """Validate AND-fork branches executed in parallel using timestamps."""
    for i, event in enumerate(trace):
        if event["type"] != "and_fork":
            continue

        expected_branches = set(event["branches"])

        join_idx = None
        for j in range(i + 1, len(trace)):
            if trace[j]["type"] == "and_join":
                if set(trace[j]["branches"]) == expected_branches:
                    join_idx = j
                    break

        if join_idx is None:
            return False, f"AND-fork {expected_branches}: no matching join"

        between = trace[i + 1 : join_idx]
        branch_acts = [
            e
            for e in between
            if e["type"] == "activity" and e["name"] in expected_branches
        ]

        if len(branch_acts) < 2:
            continue

        starts = [a["timestamp_start"] for a in branch_acts if "timestamp_start" in a]
        ends = [a["timestamp_end"] for a in branch_acts if "timestamp_end" in a]

        if not starts or not ends:
            return False, f"AND-fork {expected_branches}: missing timestamps"

        wall_clock = max(ends) - min(starts)
        sum_durations = sum(e - s for s, e in zip(starts, ends))

        if sum_durations <= 0:
            continue

        ratio = wall_clock / sum_durations
        if ratio > max_sequential_ratio:
            return (
                False,
                f"AND-fork {expected_branches}: appears SEQUENTIAL. "
                f"wall_clock={wall_clock:.4f}s, sum_branches={sum_durations:.4f}s, "
                f"ratio={ratio:.2f} (threshold={max_sequential_ratio})",
            )

    return True, ""
