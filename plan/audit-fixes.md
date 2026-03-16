# Piano: Fix audit findings (Opzione B completa)

<!-- cross-reviewed -->
<!-- Audit-driven: 10 agenti paralleli hanno identificato i problemi -->

> Fix tutti i problemi critici e alti trovati dall'audit:
> validatore model-driven, anchor indipendenti LQN, divergenza dry-run,
> protezione cicli, validazione nomi, thread-safety, bounds statistici,
> test FAKE.

## Step 1: Validatore model-driven (C1, C2, C3)

**File:** `tests/helpers/trace_validator.py`

Riscrivere `_validate_activity_trace` come walker del grafo:
1. Partire da `start_activity` del config e camminare il grafo
2. Ad ogni nodo, verificare che la trace contenga l'attivita' corrispondente
3. Per AND-fork: verificare che TUTTI i branch siano presenti tra fork e join
4. Per OR-fork: verificare che ESATTAMENTE uno sia presente (anche senza evento or_fork nella trace)
5. Verificare che la prima attivita' nella trace sia `start_activity`
6. Verificare che non ci siano attivita' extra non raggiungibili dal grafo

**Test:** aggiungere test per trace che salta attivita', trace con start sbagliato, trace senza eventi fork.
**Verifica:** `pytest tests/unit/test_trace_validation.py -v`

## Step 2: Anchor indipendenti al modello LQN (C4)

**File:** `tests/unit/test_trace_matching_e2e.py`

Aggiungere classe `TestLqnModelFidelity` che legge il file .lqn DIRETTAMENTE
e verifica valori hardcoded dal modello sorgente (non dal config compilato):
- TServer.visit start_activity == "cache"
- TServer.buy start_activity == "prepare"
- Activity "pack" service_time == 0.03
- Activity "external" ha sync_call a "read"
- OR-fork cache ha prob 0.95/0.05
- AND-fork prepare ha branch pack,ship
- notify service_time == 0.08
- save service_time == 0.02, sync_call a write

**Verifica:** `pytest tests/unit/test_trace_matching_e2e.py::TestLqnModelFidelity -v`

## Step 3: Fix divergenza dry-run branch tag (C5)

**File:** `src/app.py`

In `execute_and_fork` dry-run path: aggiungere `"branch"` tag agli eventi
come fa il path reale. Cosi' le trace dry-run e reali hanno la stessa struttura.

**Verifica:** `pytest tests/unit/test_trace.py -v`

## Step 4: Protezione cicli nel grafo (H1)

**File:** `src/app.py`

In `execute_activity_graph`: aggiungere `visited` set. Se un'attivita' viene
visitata 2 volte, interrompere con errore. Max 100 iterazioni come safety net.

**Verifica:** `pytest tests/unit/test_activity_engine.py -v` (aggiungere test per ciclo)

## Step 5: Validazione activity names (H2)

**File:** `src/app.py`

In `execute_activity`: se `activity_name` non e' in `activities` dict E non e'
una entry phase-based, loggare warning e appendere evento errore alla trace.

**Verifica:** `pytest tests/unit/test_activity_engine.py -v`

## Step 6: Fix test FAKE e WEAK (H3)

**File:** `tests/unit/test_trace.py`

Riscrivere i 4 test FAKE:
- `test_activity_has_service_time_fields` → verificare valori esatti
- `test_two_runs_same_structure` → testare con config diversi, non solo seed
- `test_execute_activity_no_trace` → verificare risultati, non solo tipo
- `test_execute_activity_graph_no_trace` → idem

Rafforzare i 9 test WEAK:
- `>= 1` → `== 1` dove il conteggio e' deterministico
- Aggiungere check di ordinamento (fork prima di branch prima di join)
- Verificare valori service_time, non solo key existence

**Verifica:** `pytest tests/unit/test_trace.py -v`

## Step 7: Thread-safety Session per fork (H4)

**File:** `src/app.py`

Creare session dedicate per i fork thread, come gia' fatto per ASYNC_SESSION.
In `execute_and_fork` real path: passare una session per-thread o usare
`requests.Session()` locale nel thread.

**Verifica:** `pytest tests/unit/test_activity_engine.py -v`

## Step 8: Tighten bounds statistici (H5)

**File:** `tests/unit/test_trace_matching_e2e.py`, `tests/unit/test_activity_engine.py`

- OR-fork 95/5 con 200 runs: cambiare bounds da [0.85, 1.0) a [0.91, 0.99]
- OR-fork 95/5 con 500 runs: cambiare bounds da [0.85, 1.0) a [0.93, 0.97]
- Mean-calls 1.2 con 1000 runs: cambiare bounds da [1.05, 1.35] a [1.13, 1.27]

**Verifica:** `pytest tests/unit/ -v`

## Ordine: Step 1-2-3 (validatore) → Step 4-5 (engine) → Step 6-7-8 (test+safety)

## Comandi di verifica
```bash
pytest tests/unit/ -v --tb=short
ruff check src/ tests/
```
