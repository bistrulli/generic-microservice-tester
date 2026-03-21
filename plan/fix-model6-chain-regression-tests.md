# Piano: Test di regressione per chain 3+ activity nel compiler LQN

<!-- cross-reviewed -->

- **File:** `tests/unit/test_lqn_compiler.py`
- **Stima:** 2 task, 1 file
- **Data:** 2026-03-21

## Contesto

Il bug documentato in `plan/fix-model6-missing-calls.md` — dove `deploy_gen.py` troncava
chain di 3+ activity (es. `gw_timeline → gw_call_tl → gw_call_ht → reply`) — è **già
stato fixato** nei commit `daf3f9b` e `5a16b05` (16 marzo 2026).

Tuttavia, non esistono test che coprano chain di 3+ activity. La test suite attuale
verifica solo:
- Sequenze di 2 activity (`prepare → pack`)
- AND-fork/join (2 branch)
- OR-fork (2 branch con probabilità)

Questo significa che il bug potrebbe tornare con un refactor futuro senza che nessun
test lo catturi.

## Strategia

**Opzione D**: modello sintetico inline per unit test + test opzionale su model6 reale.

1. **Task 1**: Test con modello LQN sintetico inline che ha una chain di 4 activity
   con call intermedie — verifica `build_task_config()` direttamente
2. **Task 2**: Test opzionale su `model6_social_network_gt.lqn` (skip se file non
   disponibile) — verifica il modello reale che ha esposto il bug

---

## Task 1: Test inline con modello sintetico (chain 4 activity)

### File

`tests/unit/test_lqn_compiler.py`

### Modifica

Aggiungere una classe `TestLongActivityChain` che costruisce un `LqnTask` sintetico
con una chain di 4 activity: `start → call_a → call_b → call_c`, dove:
- `start` ha service_time 0.1 (CPU work)
- `call_a` ha sync_call verso un entry "read" su un altro task
- `call_b` ha sync_call verso un entry "write" su un altro task
- `call_c` ha sync_call verso un entry "log" su un altro task
- reply su `call_c` (ultima activity della chain)

Il modello include 4 task: TClient (reference), TMain (con la chain), TStore, TLogger.

Test da aggiungere:

1. `test_all_activities_present` — tutte e 4 le activity sono nel config
2. `test_sequences_cover_full_chain` — le sequences coprono `start→call_a`, `call_a→call_b`, `call_b→call_c`
3. `test_reply_on_last_activity` — reply su `call_c`, NON su `call_a` o `call_b`
4. `test_sync_calls_resolved` — ogni call_X ha il suo sync_call risolto al servizio corretto

Struttura del modello sintetico (costruito con dataclass, no file .lqn):

```python
@pytest.fixture()
def chain_model():
    """Synthetic LQN model with a 4-activity chain for regression testing."""
    return LqnModel(
        name="chain-test",
        processors=[
            LqnProcessor(name="PClient", multiplicity=None),
            LqnProcessor(name="PMain", multiplicity=1),
            LqnProcessor(name="PStore", multiplicity=1),
            LqnProcessor(name="PLogger", multiplicity=1),
        ],
        tasks=[
            LqnTask(
                name="TClient", is_reference=True, processor="PClient",
                entries=[LqnEntry(name="client_entry")],
            ),
            LqnTask(
                name="TMain", processor="PMain", multiplicity=2,
                entries=[LqnEntry(name="process", start_activity="start")],
                activities={
                    "start": LqnActivity(name="start", service_time=0.1),
                    "call_a": LqnActivity(name="call_a", service_time=0.001,
                        sync_calls=[("read", 1.0)]),
                    "call_b": LqnActivity(name="call_b", service_time=0.001,
                        sync_calls=[("write", 1.0)]),
                    "call_c": LqnActivity(name="call_c", service_time=0.001,
                        sync_calls=[("log", 1.0)]),
                },
                activity_graph=LqnActivityGraph(
                    sequences=[("start", "call_a"), ("call_a", "call_b"), ("call_b", "call_c")],
                    replies={"call_c": "process"},
                ),
            ),
            LqnTask(
                name="TStore", processor="PStore",
                entries=[
                    LqnEntry(name="read", phase_service_times=[0.05]),
                    LqnEntry(name="write", phase_service_times=[0.1]),
                ],
            ),
            LqnTask(
                name="TLogger", processor="PLogger",
                entries=[LqnEntry(name="log", phase_service_times=[0.02])],
            ),
        ],
    )
```

### Perche'

Il bug originale troncava la chain a 2 activity mettendo il reply sulla prima activity
con sync_call. Questo test verifica che `build_task_config()` preservi correttamente
l'intera chain.

### Verifica

```bash
pytest tests/unit/test_lqn_compiler.py::TestLongActivityChain -v
```

---

## Task 2: Test opzionale su model6_social_network (realistico)

### File

`tests/unit/test_lqn_compiler.py`

### Modifica

Aggiungere una classe `TestModel6SocialNetwork` con un fixture che carica
`model6_social_network_gt.lqn` dal repo TLG. Skip se non disponibile.

```python
MODEL6_PATH = Path.home() / "git/TLG/tests/lqn_structure_test/model6_social_network/model6_social_network_gt.lqn"

@pytest.fixture()
def model6():
    if not MODEL6_PATH.exists():
        pytest.skip(f"model6 not found: {MODEL6_PATH}")
    return parse_lqn_file(str(MODEL6_PATH))
```

Test da aggiungere:

1. `test_nginx_gateway_has_gw_call_ht` — l'activity `gw_call_ht` è presente nel config
2. `test_nginx_gateway_timeline_chain` — la sequenza `gw_call_tl → gw_call_ht` è nelle sequences
3. `test_nginx_gateway_reply_on_gw_call_ht` — reply `GET_timeline` su `gw_call_ht` (non `gw_call_tl`)
4. `test_compose_post_full_chain` — compose_post ha chain di 5 activity completa
5. `test_all_12_non_reference_tasks_compiled` — compile_model genera 11 Deployment (12 task - 1 reference)

### Perche'

Testa il modello reale che ha esposto il bug. Skip se il file non è disponibile (CI senza TLG).

### Verifica

```bash
pytest tests/unit/test_lqn_compiler.py::TestModel6SocialNetwork -v
```

---

## Ordine: Task 1 → Task 2 (sequenziali, Task 2 dipende da import aggiunti in Task 1)

## File coinvolti

| File | Azione | Task |
|---|---|---|
| `tests/unit/test_lqn_compiler.py` | MODIFICA | 1, 2 |

## Comandi di verifica

```bash
# Unit test completi
pytest tests/unit/test_lqn_compiler.py -v

# Solo chain test
pytest tests/unit/test_lqn_compiler.py::TestLongActivityChain -v

# Solo model6 (skip se non disponibile)
pytest tests/unit/test_lqn_compiler.py::TestModel6SocialNetwork -v

# Lint
ruff check tests/unit/test_lqn_compiler.py

# Full suite
pytest tests/unit/ -q
```

## Rischi

| Rischio | Probabilità | Mitigazione |
|---------|-------------|-------------|
| Model6 non disponibile in CI | ALTA | Test con `pytest.skip()` — non blocca |
| Modello sintetico non copre tutti gli edge case | MEDIA | Il modello reale (Task 2) copre i casi complessi |
| Import dataclass cambia | BASSA | Dataclass sono API pubblica stabile del parser |
