# Piano: Fix bug critici motore + test mutazioni mancanti

<!-- cross-reviewed -->
<!-- Wave 2 simplifier: ridotto da 10+ fix a 5 cambiamenti minimali -->

## Step 1: Fix cycle detection bypass (Bug critico #1)

**File:** `src/app.py`
**Modifica:** Rimuovere l'esenzione per fork/or_fork dalla cycle detection (line 501).
Cambiare `if current in visited and current not in and_forks and current not in or_forks:`
in `if current in visited:`. Un ciclo attraverso un fork point DEVE essere rilevato.

**Aggiungere:** test `test_cycle_with_fork_raises_error` in `test_activity_engine.py` con grafo
ciclico che passa per un and_fork source.

**Verifica:** `pytest tests/unit/test_activity_engine.py -v`

## Step 2: Fix validator walk dopo AND-join (Bug #5)

**File:** `tests/helpers/trace_validator.py`
**Modifica:** In `_validate_completeness`, la funzione `walk()` fa `return` dopo aver
processato un AND-fork. Questo impedisce di continuare a camminare il grafo dopo il join target.
Rimuovere il `return` prematuro e lasciare che il walk continui tramite il join target.

**Verifica:** `pytest tests/unit/test_trace_validation.py -v`

## Step 3: Warning per AND-join mancante (Bug #3)

**File:** `src/app.py`
**Modifica:** Nel `else: break` dopo il check `if join_key in and_joins`, aggiungere
un `print(f"[LQN] WARNING: no matching AND-join for branches {fork_branches}")`.

**Verifica:** `pytest tests/unit/test_activity_engine.py -v`

## Step 4: Test per mutazioni non catturate (M2, M4)

**File:** `tests/unit/test_trace.py`
**Aggiungere:**
- `test_and_fork_dry_run_branch_tags`: verifica che eventi branch hanno campo `"branch"`
- `test_activity_service_time_sampled_nonzero`: verifica `service_time_sampled > 0`

**Verifica:** `pytest tests/unit/test_trace.py -v`

## Ordine: Step 1 → Step 2 → Step 3 → Step 4 (tutti indipendenti)

## Decisioni dal simplifier
- Bug #2 (AND-fork branch chain): DEFER — nessun modello corrente lo usa
- Bug #4 (np.random threads): SKIP — GIL lo rende safe sotto CPython
- M3 (test ciclo fork): coperto dal fix Bug #1 + test esistente
- M5 (fork order): SKIP — AND e OR fork mutuamente esclusivi in LQN

## Comandi di verifica
```bash
pytest tests/unit/ -v --tb=short
ruff check src/ tests/
```
