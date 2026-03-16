"""Tests for LQN text-format parser.

Tests cover all sections: header, processors, tasks, entries (phase-based
and activity-based), activities with calls, and activity graphs.
"""

import sys
from pathlib import Path

import pytest

# Add src/ to path so we can import lqn_parser
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from lqn_parser import LqnEntry, LqnModel, LqnTask, parse_lqn, parse_lqn_file


# --- Minimal snippets for unit tests ---

HEADER_ONLY = """\
G
"Test Model"
0.01
100
1
0.5
-1
"""

PROCESSORS_ONLY = """\
G
"test"
0.01
100
1
0.5
-1
P 0
p Proc1 f m 4
p Proc2 f i
p Proc3 f
-1
"""

TASKS_ONLY = """\
G
"test"
0.01
100
1
0.5
-1
P 0
p P1 f m 2
p P2 f
-1
T 0
t Client r entry1 -1 P1 z 0.5 m 3
t Server n ep1 ep2 ep3 -1 P2 m 10
t Simple n only -1 P2
-1
E 0
-1
"""

ENTRIES_PHASE = """\
G
"test"
0.01
100
1
0.5
-1
P 0
p P1 f
-1
T 0
t T1 n alpha beta -1 P1
-1
E 0
s alpha 0.05 -1
s beta 0.001 0.04 -1
y alpha beta 2.5 -1
z alpha beta 1.0 -1
y beta gamma 0.0 1.0 -1
-1
"""

ENTRIES_ACTIVITY = """\
G
"test"
0.01
100
1
0.5
-1
P 0
p P1 f
-1
T 0
t T1 n visit buy -1 P1
-1
E 0
A visit cache
A buy prepare
-1
"""

ACTIVITIES_BASIC = """\
G
"test"
0.01
100
1
0.5
-1
P 0
p P1 f
-1
T 0
t T1 n visit -1 P1
-1
E 0
A visit start
-1
A T1
s start 0.01
s work 0.5
y work read 1.0
z work log 2.0
:
start -> work;
work[visit]
-1
"""

GRAPH_AND_FORK = """\
G
"test"
0.01
100
1
0.5
-1
P 0
p P1 f
-1
T 0
t T1 n buy -1 P1
-1
E 0
A buy prepare
-1
A T1
s prepare 0.01
s pack 0.03
s ship 0.01
s display 0.001
:
prepare -> pack & ship;
pack & ship -> display;
display[buy]
-1
"""

GRAPH_OR_FORK = """\
G
"test"
0.01
100
1
0.5
-1
P 0
p P1 f
-1
T 0
t T1 n visit -1 P1
-1
E 0
A visit cache
-1
A T1
s cache 0.001
s internal 0.001
s external 0.003
:
cache -> (0.95)internal + (0.05)external;
internal[visit];
external[visit]
-1
"""

COMMENTS_MODEL = """\
G
"comments test"
0.01
100
1
0.5
-1
# This is a full-line comment
P 0
p Proc1 f m 2  # inline comment on processor
-1
T 0
# comment between sections
t T1 r e1 -1 Proc1 m 2
-1
E 0
s e1 0.01 -1  #comment on entry
-1
"""


class TestParseHeader:
    def test_extracts_model_name(self):
        model = parse_lqn(HEADER_ONLY)
        assert model.name == "Test Model"

    def test_empty_model_has_no_tasks(self):
        model = parse_lqn(HEADER_ONLY)
        assert model.tasks == []
        assert model.processors == []


class TestParseProcessors:
    def test_extracts_processors(self):
        model = parse_lqn(PROCESSORS_ONLY)
        assert len(model.processors) == 3

    def test_processor_names(self):
        model = parse_lqn(PROCESSORS_ONLY)
        names = [p.name for p in model.processors]
        assert names == ["Proc1", "Proc2", "Proc3"]

    def test_processor_multiplicity(self):
        model = parse_lqn(PROCESSORS_ONLY)
        assert model.processors[0].multiplicity == 4
        assert model.processors[1].multiplicity is None  # infinite
        assert model.processors[2].multiplicity is None  # default (no m keyword)


class TestParseTasks:
    def test_extracts_tasks(self):
        model = parse_lqn(TASKS_ONLY)
        assert len(model.tasks) == 3

    def test_reference_flag(self):
        model = parse_lqn(TASKS_ONLY)
        assert model.tasks[0].is_reference is True
        assert model.tasks[1].is_reference is False

    def test_entry_names(self):
        model = parse_lqn(TASKS_ONLY)
        assert [e.name for e in model.tasks[0].entries] == ["entry1"]
        assert [e.name for e in model.tasks[1].entries] == ["ep1", "ep2", "ep3"]

    def test_processor_assignment(self):
        model = parse_lqn(TASKS_ONLY)
        assert model.tasks[0].processor == "P1"
        assert model.tasks[1].processor == "P2"

    def test_think_time(self):
        model = parse_lqn(TASKS_ONLY)
        assert model.tasks[0].think_time == 0.5
        assert model.tasks[1].think_time == 0.0

    def test_multiplicity(self):
        model = parse_lqn(TASKS_ONLY)
        assert model.tasks[0].multiplicity == 3
        assert model.tasks[1].multiplicity == 10
        assert model.tasks[2].multiplicity == 1  # default


class TestParsePhaseEntries:
    def test_single_phase_service_time(self):
        model = parse_lqn(ENTRIES_PHASE)
        entry = _get_entry(model, "alpha")
        assert entry.phase_service_times == [0.05]

    def test_multi_phase_service_time(self):
        model = parse_lqn(ENTRIES_PHASE)
        entry = _get_entry(model, "beta")
        assert entry.phase_service_times == [0.001, 0.04]

    def test_sync_calls(self):
        model = parse_lqn(ENTRIES_PHASE)
        entry = _get_entry(model, "alpha")
        assert entry.phase_sync_calls is not None
        assert "beta" in entry.phase_sync_calls
        assert entry.phase_sync_calls["beta"] == [2.5]

    def test_async_calls(self):
        model = parse_lqn(ENTRIES_PHASE)
        entry = _get_entry(model, "alpha")
        assert entry.phase_async_calls is not None
        assert "beta" in entry.phase_async_calls

    def test_multi_phase_calls(self):
        model = parse_lqn(ENTRIES_PHASE)
        entry = _get_entry(model, "beta")
        assert entry.phase_sync_calls is not None
        assert "gamma" in entry.phase_sync_calls
        assert entry.phase_sync_calls["gamma"] == [0.0, 1.0]

    def test_mean_calls_fractional(self):
        """y client buy 1.2 means 1.2 calls on average."""
        model = parse_lqn(ENTRIES_PHASE)
        entry = _get_entry(model, "alpha")
        assert entry.phase_sync_calls["beta"] == [2.5]


class TestParseActivityEntries:
    def test_activity_entry_start(self):
        model = parse_lqn(ENTRIES_ACTIVITY)
        visit = _get_entry(model, "visit")
        assert visit.start_activity == "cache"
        buy = _get_entry(model, "buy")
        assert buy.start_activity == "prepare"

    def test_activity_entry_no_phase_times(self):
        model = parse_lqn(ENTRIES_ACTIVITY)
        visit = _get_entry(model, "visit")
        assert visit.phase_service_times is None


class TestParseActivities:
    def test_activity_service_time(self):
        model = parse_lqn(ACTIVITIES_BASIC)
        task = model.tasks[0]
        assert "start" in task.activities
        assert task.activities["start"].service_time == 0.01
        assert task.activities["work"].service_time == 0.5

    def test_activity_sync_calls(self):
        model = parse_lqn(ACTIVITIES_BASIC)
        task = model.tasks[0]
        calls = task.activities["work"].sync_calls
        assert len(calls) == 1
        assert calls[0] == ("read", 1.0)

    def test_activity_async_calls(self):
        model = parse_lqn(ACTIVITIES_BASIC)
        task = model.tasks[0]
        calls = task.activities["work"].async_calls
        assert len(calls) == 1
        assert calls[0] == ("log", 2.0)


class TestParseActivityGraphSequence:
    def test_sequence(self):
        model = parse_lqn(ACTIVITIES_BASIC)
        graph = model.tasks[0].activity_graph
        assert graph is not None
        assert ("start", "work") in graph.sequences

    def test_reply(self):
        model = parse_lqn(ACTIVITIES_BASIC)
        graph = model.tasks[0].activity_graph
        assert graph.replies.get("work") == "visit"


class TestParseActivityGraphAndFork:
    def test_and_fork(self):
        model = parse_lqn(GRAPH_AND_FORK)
        graph = model.tasks[0].activity_graph
        assert graph is not None
        assert len(graph.and_forks) == 1
        source, branches = graph.and_forks[0]
        assert source == "prepare"
        assert set(branches) == {"pack", "ship"}

    def test_and_join(self):
        model = parse_lqn(GRAPH_AND_FORK)
        graph = model.tasks[0].activity_graph
        assert len(graph.and_joins) == 1
        branches, target = graph.and_joins[0]
        assert set(branches) == {"pack", "ship"}
        assert target == "display"

    def test_reply_after_join(self):
        model = parse_lqn(GRAPH_AND_FORK)
        graph = model.tasks[0].activity_graph
        assert graph.replies.get("display") == "buy"


class TestParseActivityGraphOrFork:
    def test_or_fork(self):
        model = parse_lqn(GRAPH_OR_FORK)
        graph = model.tasks[0].activity_graph
        assert graph is not None
        assert len(graph.or_forks) == 1
        source, branches = graph.or_forks[0]
        assert source == "cache"
        assert len(branches) == 2

    def test_or_fork_probabilities(self):
        model = parse_lqn(GRAPH_OR_FORK)
        graph = model.tasks[0].activity_graph
        _, branches = graph.or_forks[0]
        probs = {name: prob for prob, name in branches}
        assert probs["internal"] == pytest.approx(0.95)
        assert probs["external"] == pytest.approx(0.05)

    def test_or_fork_replies(self):
        model = parse_lqn(GRAPH_OR_FORK)
        graph = model.tasks[0].activity_graph
        assert graph.replies.get("internal") == "visit"
        assert graph.replies.get("external") == "visit"


class TestParseComments:
    def test_comments_ignored(self):
        model = parse_lqn(COMMENTS_MODEL)
        assert model.name == "comments test"
        assert len(model.processors) == 1
        assert model.processors[0].name == "Proc1"
        assert model.processors[0].multiplicity == 2
        assert len(model.tasks) == 1


class TestParseTemplateAnnotated:
    """Integration test: parse the full ground truth model."""

    @pytest.fixture()
    def model(self, groundtruth_dir):
        filepath = groundtruth_dir / "template_annotated.lqn"
        if not filepath.exists():
            pytest.skip(f"Ground truth file not found: {filepath}")
        return parse_lqn_file(str(filepath))

    def test_model_name(self, model):
        assert model.name == "Name of the model"

    def test_processors(self, model):
        names = [p.name for p in model.processors]
        assert "PClient" in names
        assert "PServer" in names
        assert "PDisk" in names

    def test_processor_multiplicity(self, model):
        by_name = {p.name: p for p in model.processors}
        assert by_name["PClient"].multiplicity == 2
        assert by_name["PServer"].multiplicity == 2

    def test_tasks(self, model):
        names = [t.name for t in model.tasks]
        assert names == ["TClient", "TServer", "TFileServer", "TBackup"]

    def test_tclient_is_reference(self, model):
        tclient = _get_task(model, "TClient")
        assert tclient.is_reference is True
        assert tclient.think_time == 0.01
        assert tclient.multiplicity == 2

    def test_tserver_entries(self, model):
        tserver = _get_task(model, "TServer")
        entry_names = [e.name for e in tserver.entries]
        assert entry_names == ["visit", "buy", "notify", "save"]

    def test_tserver_multiplicity(self, model):
        tserver = _get_task(model, "TServer")
        assert tserver.multiplicity == 2

    def test_phase_entry_client(self, model):
        client_entry = _get_entry(model, "client")
        assert client_entry.phase_service_times == [0.01]
        assert client_entry.phase_sync_calls is not None
        assert "visit" in client_entry.phase_sync_calls
        assert client_entry.phase_sync_calls["visit"] == [3.0]
        assert client_entry.phase_sync_calls["buy"] == [1.2]

    def test_phase_entry_async(self, model):
        client_entry = _get_entry(model, "client")
        assert client_entry.phase_async_calls is not None
        assert "notify" in client_entry.phase_async_calls
        assert client_entry.phase_async_calls["notify"] == [1.0]

    def test_activity_entries(self, model):
        visit = _get_entry(model, "visit")
        assert visit.start_activity == "cache"
        buy = _get_entry(model, "buy")
        assert buy.start_activity == "prepare"

    def test_phase_entry_write_multiphase(self, model):
        write = _get_entry(model, "write")
        assert write.phase_service_times == [0.001, 0.04]
        assert write.phase_sync_calls["get"] == [0.0, 1.0]
        assert write.phase_sync_calls["update"] == [0.0, 1.0]

    def test_tserver_activities(self, model):
        tserver = _get_task(model, "TServer")
        assert "prepare" in tserver.activities
        assert "pack" in tserver.activities
        assert "ship" in tserver.activities
        assert "cache" in tserver.activities
        assert tserver.activities["prepare"].service_time == 0.01
        assert tserver.activities["pack"].service_time == 0.03
        assert tserver.activities["external"].service_time == 0.003

    def test_tserver_activity_calls(self, model):
        tserver = _get_task(model, "TServer")
        ext = tserver.activities["external"]
        assert len(ext.sync_calls) == 1
        assert ext.sync_calls[0] == ("read", 1.0)

    def test_tserver_graph_and_fork(self, model):
        tserver = _get_task(model, "TServer")
        graph = tserver.activity_graph
        assert graph is not None
        assert len(graph.and_forks) == 1
        src, branches = graph.and_forks[0]
        assert src == "prepare"
        assert set(branches) == {"pack", "ship"}

    def test_tserver_graph_and_join(self, model):
        tserver = _get_task(model, "TServer")
        graph = tserver.activity_graph
        branches, target = graph.and_joins[0]
        assert set(branches) == {"pack", "ship"}
        assert target == "display"

    def test_tserver_graph_or_fork(self, model):
        tserver = _get_task(model, "TServer")
        graph = tserver.activity_graph
        assert len(graph.or_forks) == 1
        src, branches = graph.or_forks[0]
        assert src == "cache"
        probs = {name: prob for prob, name in branches}
        assert probs["internal"] == pytest.approx(0.95)
        assert probs["external"] == pytest.approx(0.05)

    def test_tserver_graph_replies(self, model):
        tserver = _get_task(model, "TServer")
        graph = tserver.activity_graph
        assert graph.replies["internal"] == "visit"
        assert graph.replies["external"] == "visit"
        assert graph.replies["display"] == "buy"


# --- Helpers ---


def _get_entry(model: LqnModel, name: str) -> LqnEntry:
    for task in model.tasks:
        for entry in task.entries:
            if entry.name == name:
                return entry
    raise ValueError(f"Entry {name!r} not found")


def _get_task(model: LqnModel, name: str) -> LqnTask:
    for task in model.tasks:
        if task.name == name:
            return task
    raise ValueError(f"Task {name!r} not found")
