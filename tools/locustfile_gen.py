#!/usr/bin/env python3
"""Generate a Locust locustfile from the reference task of an LQN model.

The reference task (load generator) defines the closed-loop workload.
The generated locustfile faithfully reproduces the reference task's activity
graph: service times become deterministic time.sleep(), sync/async calls
become HTTP requests with relative URLs.

Usage:
    python tools/locustfile_gen.py model.lqn
    python tools/locustfile_gen.py model.lqn -o locustfile.py
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

try:
    from gmt.lqn_parser import LqnModel, LqnTask, parse_lqn_file
    from gmt.tools.lqn_compiler import resolve_call_target
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
    sys.path.insert(0, str(Path(__file__).parent))
    from lqn_parser import LqnModel, LqnTask, parse_lqn_file
    from lqn_compiler import resolve_call_target


def _resolve_entry_path(model: LqnModel, entry_name: str) -> str | None:
    """Resolve an LQN entry name to a relative URL path (e.g., '/Entr1')."""
    result = resolve_call_target(model, entry_name)
    if result is None:
        return None
    _svc_name, path = result
    return f"/{path}"


def _walk_activity_graph(
    task: LqnTask,
    model: LqnModel,
    indent: str = "        ",
) -> list[str]:
    """Walk the activity graph of a task and generate Python code lines.

    For each activity visited (in graph order via DFS):
    - service_time > 0 → time.sleep(service_time)
    - sync_calls → self.client.get("/<entry>") with relative URL
    - async_calls → self.client.get("/<entry>") (fire-and-forget from Locust side)

    Follows: sequences, or_forks, and_forks, and_joins.
    """
    lines: list[str] = []
    visited: set[str] = set()

    def _emit_activity(activity_name: str) -> None:
        if activity_name in visited or activity_name not in task.activities:
            return
        visited.add(activity_name)

        act = task.activities[activity_name]

        # Service time → deterministic sleep
        if act.service_time > 0:
            lines.append(f"{indent}# {activity_name}: service_time={act.service_time}s")
            lines.append(f"{indent}time.sleep({act.service_time})")

        # Sync calls → HTTP GET with relative URL
        for target_entry, mean_calls in act.sync_calls:
            path = _resolve_entry_path(model, target_entry)
            if not path:
                continue
            n_guaranteed = math.floor(mean_calls)
            frac = round(mean_calls - n_guaranteed, 6)

            lines.append(
                f"{indent}# {mean_calls} sync call(s) to {target_entry}"
            )
            if n_guaranteed == 1 and frac == 0:
                lines.append(f'{indent}self.client.get("{path}")')
            elif n_guaranteed > 0:
                lines.append(f"{indent}for _ in range({n_guaranteed}):")
                lines.append(f'{indent}    self.client.get("{path}")')
            if frac > 0:
                lines.append(f"{indent}if random.random() < {frac}:")
                lines.append(f'{indent}    self.client.get("{path}")')

        # Async calls → same HTTP GET (Locust doesn't differentiate)
        for target_entry, mean_calls in act.async_calls:
            path = _resolve_entry_path(model, target_entry)
            if not path:
                continue
            n_guaranteed = math.floor(mean_calls)
            frac = round(mean_calls - n_guaranteed, 6)

            lines.append(
                f"{indent}# {mean_calls} async call(s) to {target_entry}"
            )
            if n_guaranteed == 1 and frac == 0:
                lines.append(f'{indent}self.client.get("{path}")')
            elif n_guaranteed > 0:
                lines.append(f"{indent}for _ in range({n_guaranteed}):")
                lines.append(f'{indent}    self.client.get("{path}")')
            if frac > 0:
                lines.append(f"{indent}if random.random() < {frac}:")
                lines.append(f'{indent}    self.client.get("{path}")')

        # Follow graph edges
        graph = task.activity_graph
        if not graph:
            return
        for src, dst in graph.sequences:
            if src == activity_name:
                _emit_activity(dst)
        for src, branches in graph.and_forks:
            if src == activity_name:
                for b in branches:
                    _emit_activity(b)
        for branches, dst in graph.and_joins:
            if activity_name in branches:
                _emit_activity(dst)
        for src, branch_list in graph.or_forks:
            if src == activity_name:
                for _, name in branch_list:
                    _emit_activity(name)

    for entry in task.entries:
        if entry.start_activity:
            _emit_activity(entry.start_activity)

    return lines


def _build_phase_call_block(
    ref: LqnTask,
    model: LqnModel,
    indent: str = "        ",
) -> list[str]:
    """Generate call block for phase-based entries (no activity graph)."""
    lines: list[str] = []

    for entry in ref.entries:
        for call_dict, call_type in [
            (entry.phase_sync_calls, "sync"),
            (entry.phase_async_calls, "async"),
        ]:
            if not call_dict:
                continue
            for target_entry, phases in call_dict.items():
                mean_calls = phases[0] if phases else 0.0
                if mean_calls <= 0:
                    continue
                path = _resolve_entry_path(model, target_entry)
                if not path:
                    continue

                n_guaranteed = math.floor(mean_calls)
                frac = round(mean_calls - n_guaranteed, 6)

                lines.append(
                    f"{indent}# {mean_calls} {call_type} call(s) to {target_entry}"
                )
                if n_guaranteed == 1 and frac == 0:
                    lines.append(f'{indent}self.client.get("{path}")')
                elif n_guaranteed > 0:
                    lines.append(f"{indent}for _ in range({n_guaranteed}):")
                    lines.append(f'{indent}    self.client.get("{path}")')
                if frac > 0:
                    lines.append(f"{indent}if random.random() < {frac}:")
                    lines.append(f'{indent}    self.client.get("{path}")')

    return lines


def generate_locustfile(model: LqnModel) -> str:
    """Generate a Locust locustfile that faithfully reproduces the reference task.

    Activity service times become deterministic time.sleep().
    Sync/async calls become self.client.get("/<entry>") with relative URLs.
    Locust wait_time is 0 — all timing is modeled inside the cycle method.

    Raises:
        ValueError: If no reference task found in the model.
    """
    ref_tasks = [t for t in model.tasks if t.is_reference]
    if not ref_tasks:
        raise ValueError(f"No reference task found in model '{model.name}'")

    ref = ref_tasks[0]
    multiplicity = ref.multiplicity

    # Try activity-based generation first (faithful activity graph walk)
    cycle_lines = _walk_activity_graph(ref, model)

    # Fallback to phase-based if no activity graph
    if not cycle_lines:
        cycle_lines = _build_phase_call_block(ref, model)

    if not cycle_lines:
        cycle_lines = ["        self.client.get(\"/\")"]

    call_block = "\n".join(cycle_lines)
    needs_random = "random.random()" in call_block
    needs_time = "time.sleep(" in call_block

    imports = []
    if needs_time:
        imports.append("import time")
    if needs_random:
        imports.append("import random")
    import_block = "\n".join(imports)
    if import_block:
        import_block += "\n"

    source = f'''"""Auto-generated locustfile from LQN model: {model.name}

Reference task: {ref.name} (m={multiplicity})
Generated by: lqn-locustfile (GMT)
"""
{import_block}from locust import HttpUser, task


class LqnClient(HttpUser):
    """Closed-loop client reproducing {ref.name} behavior."""

    def wait_time(self):
        """No Locust wait — all timing is modeled as time.sleep in cycle()."""
        return 0

    @task
    def cycle(self):
        """One activation of {ref.name}: activities and calls in graph order."""
{call_block}
'''
    return source.strip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate Locust locustfile from LQN model reference task"
    )
    parser.add_argument("lqn_file", help="Path to .lqn model file")
    parser.add_argument("-o", "--output", help="Output file (default: stdout)")

    args = parser.parse_args()

    model = parse_lqn_file(args.lqn_file)

    try:
        source = generate_locustfile(model)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.output:
        Path(args.output).write_text(source)
        print(f"Written to {args.output}", file=sys.stderr)
    else:
        print(source)


if __name__ == "__main__":
    main()
