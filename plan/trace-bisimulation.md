# Piano: Verifica formale Activity Engine via Trace Matching

> Aggiungere tracing strutturato, dry-run mode, e validazione trace
> per verificare formalmente che il motore LQN esegua il flusso
> corretto rispetto all'activity diagram del modello.

## Contesto

L'activity engine (app.py) e' stato implementato ma non e' mai stato verificato
formalmente che il flusso di esecuzione corrisponda all'activity diagram LQN.
I test attuali verificano timing e routing ma NON l'ordine delle attivita'.

La ricerca indica che **trace membership** (verificare che una trace osservata
sia un cammino valido nel CFG) e' il formalismo corretto — piu' semplice
della bisimulazione e sufficiente per il nostro caso.

### Decisioni dal brainstorming

- **Approccio**: trace matching (opzione A) — non bisimulazione forte
- **lqn_cfg.py**: ELIMINATO — la LQN_TASK_CONFIG JSON e' gia' il grafo
- **trace_matcher.py**: ELIMINATO come modulo di produzione — la validazione
  vive nei test, non nel codice di produzione
- **Thread safety**: AND-fork usa sub-liste per branch, merge al join
- **Dry-run deterministico**: seed fissato per OR-fork in dry-run

---

## Step 1: Execution Trace + Dry-run in app.py

**File modificato:** `src/app.py`

### 1.1 Trace format

Ogni evento e' un dict con `type` e campi specifici. Per AND-fork, i branch
producono sub-trace separate che vengono taggati e mergiati al join.

```python
# Tipi di evento trace:
{"type": "activity", "name": "cache", "service_time_mean": 0.001, "service_time_sampled": 0.0008}
{"type": "and_fork", "branches": ["pack", "ship"]}
{"type": "activity", "name": "pack", "branch": "pack", ...}   # taggato con branch
{"type": "activity", "name": "ship", "branch": "ship", ...}
{"type": "and_join", "branches": ["pack", "ship"], "to": "display"}
{"type": "or_fork", "from": "cache", "chosen": "internal", "branches": ["internal", "external"]}
{"type": "activity", "name": "internal", ...}
{"type": "reply", "activity": "internal", "entry": "visit"}
{"type": "sync_call", "target": "tfileserver-svc/read"}
{"type": "async_call", "target": "logger-svc/log"}
{"type": "phase_entry", "name": "notify", "service_time_mean": 0.08, ...}
```

### 1.2 Signature changes

Aggiungere `trace: list[dict] | None = None` e `dry_run: bool = False` come
parametri opzionali con default a TUTTE queste funzioni:

- `do_busy_wait(service_time_mean, dry_run=False)` — dry_run: skip CPU, return sampled
- `execute_mean_calls(url, mean_calls, call_type, trace=None, dry_run=False)` — dry_run: skip HTTP
- `execute_activity(name, config, trace=None, dry_run=False)` — appende evento activity
- `execute_and_fork(branches, config, trace=None, dry_run=False)` — thread safety: sub-liste per branch, merge con tag
- `execute_or_fork(source, branches, config, trace=None, dry_run=False)` — appende evento or_fork
- `execute_activity_graph(entry_name, config, trace=None, dry_run=False)` — orchestra tutto
- `execute_phase_entry(entry_name, entry_def, trace=None, dry_run=False)` — appende evento phase_entry

### 1.3 Dry-run semantics

- `LQN_DRY_RUN=1` env var attiva dry-run globalmente
- `do_busy_wait`: ritorna tempo campionato senza consumare CPU
- `execute_mean_calls`: non chiama `make_call`/`make_async_call_pooled`, ritorna risultati sintetici
- `execute_and_fork`: esegue branch sequenzialmente (no threading, trace deterministica)
- `execute_or_fork` in dry-run: usa `random.seed(42)` per determinismo, o accetta seed param

### 1.4 AND-fork thread safety

In modalita' non-dry-run (esecuzione reale con tracing):
```python
def execute_and_fork(branches, config, trace=None, dry_run=False):
    if trace is not None:
        trace.append({"type": "and_fork", "branches": list(branches)})

    if dry_run:
        # Sequenziale, deterministico
        for branch in branches:
            execute_activity(branch, config, trace, dry_run)
        return results

    # Reale: sub-trace per branch (thread-safe)
    branch_traces = [[] for _ in branches]
    futures = [FORK_EXECUTOR.submit(execute_activity, b, config, branch_traces[i], dry_run)
               for i, b in enumerate(branches)]
    futures_wait(futures)

    # Merge con tag branch
    if trace is not None:
        for i, bt in enumerate(branch_traces):
            for event in bt:
                event["branch"] = branches[i]
                trace.append(event)
```

### 1.5 Response JSON con trace

```python
def handle_lqn_request(entry_name, config):
    dry_run = _is_dry_run()
    trace = [] if dry_run or os.environ.get("LQN_TRACE", "0") == "1" else None

    results = execute_activity_graph(entry_name, config, trace, dry_run)

    response = {
        "message": f"Response from {my_name}",
        "entry": entry_name,
        "outbound_results": results,
    }
    if trace is not None:
        response["trace"] = trace
    return jsonify(response)
```

### Verifica Step 1

```bash
pytest tests/unit/test_activity_engine.py -v  # test regressione (non rotti)
pytest tests/unit/test_trace.py -v             # nuovi test trace
```

### Test Step 1

- `test_trace_activity_recorded` — trace contiene evento activity con nome corretto
- `test_trace_and_fork_recorded` — trace contiene and_fork + attivita' branch + and_join
- `test_trace_and_fork_branch_tagged` — eventi branch hanno campo "branch" per disambiguazione
- `test_trace_or_fork_recorded` — trace contiene or_fork con campo "chosen"
- `test_trace_reply_recorded` — trace termina con evento reply
- `test_trace_phase_entry_recorded` — trace contiene phase_entry per entry senza diagram
- `test_trace_sync_call_recorded` — trace contiene sync_call con target
- `test_trace_async_call_recorded` — trace contiene async_call con target
- `test_dry_run_no_cpu` — dry-run non consuma CPU (time.process_time delta ~0)
- `test_dry_run_no_http` — dry-run non chiama make_call (mock non invocato)
- `test_dry_run_deterministic` — 2 esecuzioni dry-run producono stessa trace (eccetto sampled times)
- `test_existing_tests_not_broken` — i 21 test esistenti passano senza trace/dry_run

---

## Step 2: Trace validation utilities (in tests/)

**File nuovo:** `tests/helpers/trace_validator.py`

NON e' codice di produzione. E' una utility di test che valida una trace
contro la struttura del grafo in LQN_TASK_CONFIG.

### Algoritmo di validazione (token-based replay semplificato)

```python
def validate_trace(trace: list[dict], config: dict, entry_name: str) -> tuple[bool, str]:
    """Validate that trace is a valid execution path for entry_name.

    Returns (True, "") if valid, (False, "reason") if invalid.

    Rules:
    1. Every 'activity' event must reference a valid activity name
    2. For 'and_fork': all branch names must appear as activities before 'and_join'
    3. For 'or_fork': exactly one 'chosen' branch must appear as activity after fork
    4. 'reply' must be last event and reference the correct entry
    5. Sequence ordering: if A->B in sequences, A must appear before B
    6. Phase entries: service_time_mean must match config
    """
```

### Regole specifiche

Per **AND-fork**:
- Dopo evento `and_fork` con `branches: [B1, B2]`, devono apparire
  attivita' `B1` e `B2` (in qualsiasi ordine) prima di `and_join`
- Ogni evento tra fork e join deve avere `branch` tag valido

Per **OR-fork**:
- Dopo evento `or_fork` con `chosen: X`, deve apparire attivita' `X`
- Le altre branch NON devono apparire

Per **sequenze**:
- Se il grafo ha `[A, B]` come sequenza, l'indice di A nella trace
  deve essere < indice di B

Per **reply**:
- L'ultimo evento deve essere `{"type": "reply", "entry": entry_name}`

### Verifica Step 2

```bash
pytest tests/unit/test_trace_validation.py -v
```

### Test Step 2

- `test_validate_simple_sequence` — trace A→B→reply valida
- `test_validate_and_fork` — trace con fork+2 branch+join valida
- `test_validate_and_fork_missing_branch` — trace con 1 branch mancante → invalida
- `test_validate_or_fork` — trace con 1 branch scelto valida
- `test_validate_or_fork_both_branches` — trace con entrambi i branch → invalida
- `test_validate_reply_last` — reply non ultimo → invalida
- `test_validate_unknown_activity` — attivita' non nel config → invalida
- `test_validate_sequence_order` — ordine sbagliato → invalida

---

## Step 3: E2E trace matching con template_annotated.lqn

**File nuovo:** `tests/unit/test_trace_matching_e2e.py`

Questo test e' il cuore della verifica formale: compila il modello ground truth,
esegue ogni entry in dry-run, raccoglie la trace, e valida contro il CFG.

### Flow

```python
def test_template_annotated_visit():
    """Trace matching per entry 'visit' di TServer."""
    # 1. Parse modello LQN
    model = parse_lqn_file("test/lqn-groundtruth/template_annotated.lqn")
    # 2. Build task config per TServer (usando il compiler)
    tserver = next(t for t in model.tasks if t.name == "TServer")
    config = build_task_config(tserver, model)
    # 3. Esegui in dry-run con trace
    trace = []
    execute_activity_graph("visit", config, trace=trace, dry_run=True)
    # 4. Valida trace
    valid, reason = validate_trace(trace, config, "visit")
    assert valid, f"Trace invalid for 'visit': {reason}\nTrace: {trace}"
```

### Entry da testare

| Entry | Tipo | Costrutti | Validazione attesa |
|-------|------|-----------|-------------------|
| `visit` | Activity-based | OR-fork (95/5) | cache → (internal OR external) → reply |
| `buy` | Activity-based | AND-fork/join | prepare → pack & ship → display → reply |
| `notify` | Phase-based | Solo service time | phase_entry → reply implicito |
| `save` | Phase-based | Service time + sync call | phase_entry + sync_call → reply implicito |

### Test

- `test_trace_matching_visit` — OR-fork: trace contiene cache, poi UNO tra internal/external, poi reply
- `test_trace_matching_buy` — AND-fork: trace contiene prepare, POI pack E ship (any order), POI display, reply
- `test_trace_matching_notify` — phase entry con service time
- `test_trace_matching_save` — phase entry con sync call a write
- `test_trace_matching_visit_multiple_runs` — 50 runs: verificare che ~95% scelgono internal
- `test_trace_matching_buy_branch_completeness` — verificare che ENTRAMBI pack e ship appaiono

---

## Ordine di implementazione

```
Step 1: trace + dry-run in app.py + test_trace.py
    │
    └── Step 2: trace_validator.py + test_trace_validation.py
            │
            └── Step 3: test_trace_matching_e2e.py (integrazione con ground truth)
```

Tutti sequenziali: ogni step dipende dal precedente.

---

## File coinvolti

| File | Azione | Step |
|---|---|---|
| `src/app.py` | MODIFICATO — trace + dry_run params | 1 |
| `tests/unit/test_trace.py` | NUOVO — test del tracing | 1 |
| `tests/helpers/__init__.py` | NUOVO | 2 |
| `tests/helpers/trace_validator.py` | NUOVO — utility validazione trace | 2 |
| `tests/unit/test_trace_validation.py` | NUOVO — test del validatore | 2 |
| `tests/unit/test_trace_matching_e2e.py` | NUOVO — trace matching con ground truth | 3 |

**NON modificati:** lqn_parser.py, lqn_compiler.py, Dockerfile, entrypoint.sh, K8s manifests.

---

## Rischi e mitigazioni

| Rischio | Severita' | Mitigazione |
|---|---|---|
| Thread safety trace in AND-fork reale | Alta | Sub-liste per branch, merge con tag al join |
| OR-fork non-deterministico in dry-run | Media | Seed fisso (42) in dry-run mode |
| Test esistenti rotti | Bassa | Parametri con default, 0 breaking changes |
| Trace troppo verbosa per modelli grandi | Bassa | Trace opzionale (solo se LQN_TRACE=1 o dry-run) |

## Comandi di verifica

```bash
# Test completi
pytest tests/ -v --tb=short

# Solo trace tests
pytest tests/unit/test_trace.py tests/unit/test_trace_validation.py tests/unit/test_trace_matching_e2e.py -v

# Regressione engine
pytest tests/unit/test_activity_engine.py -v

# Lint
ruff check src/ tests/
```
