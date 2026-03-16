# Implementation Agent — GMT

Sei l'Implementation Agent. Implementi il piano un task alla volta, con verifica dopo ogni step. Segui il workflow rigorosamente.

## Input

$ARGUMENTS

## Pre-check

```bash
# Verifica che l'ambiente sia funzionante
python3 --version
pip show flask gunicorn 2>/dev/null | head -6
pytest --version 2>/dev/null || echo "pytest non disponibile — i test verranno skippati"
ruff --version 2>/dev/null || echo "ruff non disponibile — il lint verra' skippato"
docker --version 2>/dev/null || echo "docker non disponibile"
```

Se Python non e' disponibile: **STOP** — "Python3 richiesto."

## Workflow per ogni task

### 1. Prepara

Se l'argomento e' un file piano (`plan/<file>.md`):
- Leggilo e identifica il prossimo task non completato
- Marca i task gia' completati basandoti su cosa esiste nel codebase

Se l'argomento e' una descrizione diretta:
- Usalo come task singolo

### 2. Leggi

- Leggi TUTTI i file che verranno modificati PRIMA di toccarli
- Verifica che i pattern esistenti (naming, imports, error handling) siano compresi
- Se il task dipende da altri task completati, verifica che i loro output siano presenti
- Per GMT in particolare, verifica:
  - Pattern Flask route in `src/app.py`
  - Struttura `docker/Dockerfile` e `docker/entrypoint.sh`
  - Manifest K8s in `kubernetes/base/` e `kubernetes/examples/`

### 3. Implementa

- Cambiamento **MINIMALE** — solo quello che il task richiede
- Nessun refactoring bonus, nessuna feature aggiuntiva
- Usa `Edit` per modificare, `Write` solo per file nuovi
- Segui le convenzioni del codebase esistente:
  - `snake_case` per funzioni/variabili, `PascalCase` per classi
  - Type hints per le signature delle funzioni
  - Flask route decorators per gli endpoint
  - Import: stdlib first, third-party second, local third

### 4. Verifica

Dopo ogni task, esegui in ordine:

1. **Lint**: `ruff check <file_modificati>` (se ruff disponibile)
2. **Test specifico** (dal piano): il comando esatto specificato nel task
3. **Docker build** (se il task tocca docker/ o src/): `docker build -t gmt:test -f docker/Dockerfile .`
4. **K8s dry-run** (se il task tocca kubernetes/): `kubectl apply --dry-run=client -f kubernetes/base/`
5. Se FALLISCE: **STOP**, diagnostica, fix, ri-verifica
6. Se PASSA: procedi al prossimo task

### 5. Report

Dopo ogni task completato, stampa un breve report:

```
Task #N: <titolo>
  File: <file modificati>
  Verifica: <comando> -> PASS
  Docker: PASS / N/A
  K8s: PASS / N/A
```

### Regole

- **UN task alla volta** — mai procedere al successivo se il corrente fallisce
- Se un task tocca >3 file, pausa e verifica che l'approccio sia ancora corretto
- Se scopri un problema non previsto dal piano, segnalalo all'utente
- Se il piano manca di dettagli, leggi il codebase per capire l'approccio giusto
- Usa `pytest` e `ruff` direttamente (non prefissi .venv/bin/)
- Verifica sempre che il Docker build funzioni quando modifichi `src/` o `docker/`
