"""Parser for LQN (Layered Queueing Network) text format (.lqn files).

Supports the standard LQN V5 text format as used by lqns/lqsim solvers.
Parses: processors, tasks, entries (phase-based and activity-based),
activities with service times/calls, and activity graphs (sequence,
AND-fork/join, OR-fork, reply semantics).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


# --- Data model ---


@dataclass
class LqnActivity:
    """A single activity within a task's activity graph."""

    name: str
    service_time: float = 0.0
    sync_calls: list[tuple[str, float]] = field(default_factory=list)
    async_calls: list[tuple[str, float]] = field(default_factory=list)


@dataclass
class LqnActivityGraph:
    """Activity diagram for an entry that uses activity-based definition."""

    sequences: list[tuple[str, str]] = field(default_factory=list)
    and_forks: list[tuple[str, list[str]]] = field(default_factory=list)
    and_joins: list[tuple[list[str], str]] = field(default_factory=list)
    or_forks: list[tuple[str, list[tuple[float, str]]]] = field(default_factory=list)
    replies: dict[str, str] = field(default_factory=dict)


@dataclass
class LqnEntry:
    """An entry point on a task (maps to an HTTP endpoint)."""

    name: str
    phase_service_times: list[float] | None = None
    phase_sync_calls: dict[str, list[float]] | None = None
    phase_async_calls: dict[str, list[float]] | None = None
    start_activity: str | None = None


@dataclass
class LqnTask:
    """An LQN task (maps to a K8s Deployment)."""

    name: str
    is_reference: bool = False
    entries: list[LqnEntry] = field(default_factory=list)
    processor: str = ""
    multiplicity: int = 1
    think_time: float = 0.0
    activities: dict[str, LqnActivity] = field(default_factory=dict)
    activity_graph: LqnActivityGraph | None = None


@dataclass
class LqnProcessor:
    """An LQN processor (maps to K8s resource limits)."""

    name: str
    scheduling: str = "f"
    multiplicity: int | None = None


@dataclass
class LqnModel:
    """Complete LQN model parsed from a .lqn file."""

    name: str = ""
    processors: list[LqnProcessor] = field(default_factory=list)
    tasks: list[LqnTask] = field(default_factory=list)


# --- Parser ---


def _strip_comment(line: str) -> str:
    """Remove inline comments (# ...) from a line, preserving quoted strings."""
    in_quote = False
    for i, ch in enumerate(line):
        if ch == '"':
            in_quote = not in_quote
        elif ch == "#" and not in_quote:
            return line[:i].rstrip()
    return line.rstrip()


def _clean_lines(text: str) -> list[str]:
    """Split text into lines, strip comments and whitespace, remove blanks."""
    result = []
    for raw_line in text.split("\n"):
        line = _strip_comment(raw_line).strip()
        if line:
            result.append(line)
    return result


def parse_lqn(text: str) -> LqnModel:
    """Parse an LQN text-format model into an LqnModel dataclass.

    Args:
        text: Full content of a .lqn file.

    Returns:
        LqnModel with processors, tasks, entries, activities, and graphs.
    """
    model = LqnModel()
    lines = _clean_lines(text)

    i = 0
    while i < len(lines):
        line = lines[i]

        if line == "G":
            i, model.name = _parse_header(lines, i)
        elif line.startswith("P "):
            i = _parse_processors(lines, i, model)
        elif line.startswith("T "):
            i = _parse_tasks(lines, i, model)
        elif line.startswith("E "):
            i = _parse_entries(lines, i, model)
        elif line.startswith("A "):
            i = _parse_activities(lines, i, model)
        else:
            i += 1

    return model


def _parse_header(lines: list[str], start: int) -> tuple[int, str]:
    """Parse the G (global) header section."""
    i = start + 1
    name = ""
    if i < len(lines) and lines[i].startswith('"'):
        name = lines[i].strip('"')
        i += 1
    # Skip remaining header fields until -1
    while i < len(lines) and lines[i] != "-1":
        i += 1
    return i + 1, name


def _parse_processors(lines: list[str], start: int, model: LqnModel) -> int:
    """Parse P (processor) section."""
    i = start + 1
    while i < len(lines) and lines[i] != "-1":
        line = lines[i]
        if line.startswith("p "):
            tokens = line.split()
            name = tokens[1]
            scheduling = tokens[2] if len(tokens) > 2 else "f"
            multiplicity = None
            for j, tok in enumerate(tokens):
                if tok == "m" and j + 1 < len(tokens):
                    multiplicity = int(tokens[j + 1])
                elif tok == "i":
                    multiplicity = None  # infinite
            model.processors.append(
                LqnProcessor(
                    name=name, scheduling=scheduling, multiplicity=multiplicity
                )
            )
        i += 1
    return i + 1


def _parse_tasks(lines: list[str], start: int, model: LqnModel) -> int:
    """Parse T (task) section."""
    i = start + 1
    while i < len(lines) and lines[i] != "-1":
        line = lines[i]
        if line.startswith("t "):
            task = _parse_task_line(line)
            model.tasks.append(task)
        i += 1
    return i + 1


def _parse_task_line(line: str) -> LqnTask:
    """Parse a single task definition line.

    Format: t TaskName RefFlag EntryList -1 Processor [z thinktime] [m multiplicity]
    """
    tokens = line.split()
    name = tokens[1]
    is_reference = tokens[2] == "r"

    # Find entry list (between flag and -1)
    entry_names: list[str] = []
    idx = 3
    while idx < len(tokens) and tokens[idx] != "-1":
        entry_names.append(tokens[idx])
        idx += 1
    idx += 1  # skip -1

    processor = tokens[idx] if idx < len(tokens) else ""
    idx += 1

    think_time = 0.0
    multiplicity = 1

    while idx < len(tokens):
        if tokens[idx] == "z" and idx + 1 < len(tokens):
            think_time = float(tokens[idx + 1])
            idx += 2
        elif tokens[idx] == "m" and idx + 1 < len(tokens):
            multiplicity = int(tokens[idx + 1])
            idx += 2
        else:
            idx += 1

    entries = [LqnEntry(name=en) for en in entry_names]

    return LqnTask(
        name=name,
        is_reference=is_reference,
        entries=entries,
        processor=processor,
        multiplicity=multiplicity,
        think_time=think_time,
    )


def _parse_entries(lines: list[str], start: int, model: LqnModel) -> int:
    """Parse E (entry) section with phase-based and activity-based definitions."""
    i = start + 1
    while i < len(lines) and lines[i] != "-1":
        line = lines[i]
        tokens = line.split()

        if not tokens:
            i += 1
            continue

        cmd = tokens[0]

        if cmd == "s" and len(tokens) >= 3:
            # Phase-based service time: s EntryName Phase1 [Phase2 ...] -1
            entry_name = tokens[1]
            phases = []
            for t in tokens[2:]:
                if t == "-1":
                    break
                phases.append(float(t))
            entry = _find_entry(model, entry_name)
            if entry:
                entry.phase_service_times = phases

        elif cmd == "y" and len(tokens) >= 4:
            # Sync call: y FromEntry ToEntry Phase1Calls [Phase2Calls ...] -1
            from_entry_name = tokens[1]
            to_entry_name = tokens[2]
            calls = []
            for t in tokens[3:]:
                if t == "-1":
                    break
                calls.append(float(t))
            entry = _find_entry(model, from_entry_name)
            if entry:
                if entry.phase_sync_calls is None:
                    entry.phase_sync_calls = {}
                entry.phase_sync_calls[to_entry_name] = calls

        elif cmd == "z" and len(tokens) >= 4:
            # Async call: z FromEntry ToEntry Phase1Calls [Phase2Calls ...] -1
            from_entry_name = tokens[1]
            to_entry_name = tokens[2]
            calls = []
            for t in tokens[3:]:
                if t == "-1":
                    break
                calls.append(float(t))
            entry = _find_entry(model, from_entry_name)
            if entry:
                if entry.phase_async_calls is None:
                    entry.phase_async_calls = {}
                entry.phase_async_calls[to_entry_name] = calls

        elif cmd == "A" and len(tokens) >= 3:
            # Activity-based entry: A EntryName FirstActivity
            entry_name = tokens[1]
            start_activity = tokens[2]
            entry = _find_entry(model, entry_name)
            if entry:
                entry.start_activity = start_activity

        i += 1
    return i + 1


def _parse_activities(lines: list[str], start: int, model: LqnModel) -> int:
    """Parse A TaskName section (activity definitions + graph)."""
    tokens = lines[start].split()
    task_name = tokens[1]
    task = _find_task(model, task_name)
    if not task:
        # Skip to -1
        i = start + 1
        while i < len(lines) and lines[i] != "-1":
            i += 1
        return i + 1

    i = start + 1
    in_graph = False

    while i < len(lines) and lines[i] != "-1":
        line = lines[i]

        if line == ":":
            in_graph = True
            task.activity_graph = LqnActivityGraph()
            i += 1
            continue

        if in_graph:
            _parse_graph_line(line, task.activity_graph)
        else:
            _parse_activity_line(line, task)

        i += 1

    return i + 1


def _parse_activity_line(line: str, task: LqnTask) -> None:
    """Parse a single activity attribute line (s, y, or z)."""
    tokens = line.split()
    if not tokens:
        return

    cmd = tokens[0]

    if cmd == "s" and len(tokens) >= 3:
        name = tokens[1]
        service_time = float(tokens[2])
        if name not in task.activities:
            task.activities[name] = LqnActivity(name=name)
        task.activities[name].service_time = service_time

    elif cmd == "y" and len(tokens) >= 4:
        activity_name = tokens[1]
        target_entry = tokens[2]
        mean_calls = float(tokens[3])
        if activity_name not in task.activities:
            task.activities[activity_name] = LqnActivity(name=activity_name)
        task.activities[activity_name].sync_calls.append((target_entry, mean_calls))

    elif cmd == "z" and len(tokens) >= 4:
        activity_name = tokens[1]
        target_entry = tokens[2]
        mean_calls = float(tokens[3])
        if activity_name not in task.activities:
            task.activities[activity_name] = LqnActivity(name=activity_name)
        task.activities[activity_name].async_calls.append((target_entry, mean_calls))


def _parse_graph_line(line: str, graph: LqnActivityGraph) -> None:
    """Parse a single line from the activity graph (after ':').

    Supports:
    - Sequence: A -> B
    - AND-fork: A -> B & C
    - AND-join: B & C -> D
    - OR-fork: A -> (0.95)B + (0.05)C
    - Reply: activity[entry]
    """
    # Strip trailing semicolons
    line = line.rstrip(";").strip()

    if not line:
        return

    # Check for reply: activity[entry]
    reply_match = re.match(r"^(\w+)\[(\w+)\]$", line)
    if reply_match:
        activity_name = reply_match.group(1)
        entry_name = reply_match.group(2)
        graph.replies[activity_name] = entry_name
        return

    # Check for arrow (sequence, fork, join)
    if "->" not in line:
        return

    left, right = line.split("->", 1)
    left = left.strip()
    right = right.strip()

    # Check for OR-fork: right contains (prob)activity + (prob)activity
    or_match = re.findall(r"\(([0-9.]+)\)(\w+)", right)
    if or_match and "+" in right:
        branches = [(float(prob), name) for prob, name in or_match]
        graph.or_forks.append((left, branches))
        return

    # Check for AND-fork/join: contains &
    left_parts = [p.strip() for p in left.split("&")]
    right_parts = [p.strip() for p in right.split("&")]

    if len(left_parts) > 1 and len(right_parts) == 1:
        # AND-join: B & C -> D
        graph.and_joins.append((left_parts, right_parts[0]))
    elif len(left_parts) == 1 and len(right_parts) > 1:
        # AND-fork: A -> B & C
        graph.and_forks.append((left_parts[0], right_parts))
    elif len(left_parts) == 1 and len(right_parts) == 1:
        # Simple sequence: A -> B
        graph.sequences.append((left_parts[0], right_parts[0]))
    else:
        # Multi-to-multi: treat as join then fork (unusual)
        pass


# --- Helpers ---


def _find_entry(model: LqnModel, entry_name: str) -> LqnEntry | None:
    """Find an entry by name across all tasks."""
    for task in model.tasks:
        for entry in task.entries:
            if entry.name == entry_name:
                return entry
    return None


def _find_task(model: LqnModel, task_name: str) -> LqnTask | None:
    """Find a task by name."""
    for task in model.tasks:
        if task.name == task_name:
            return task
    return None


def parse_lqn_file(filepath: str) -> LqnModel:
    """Parse an LQN model from a file path."""
    with open(filepath) as f:
        return parse_lqn(f.read())
