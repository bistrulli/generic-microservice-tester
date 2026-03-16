# Agente Autonomo — GMT

Pipeline completo in una sessione per task semplici (1-3 file). Esegue PLAN -> IMPLEMENT -> REVIEW -> TEST inline, con report tra le fasi.

## Input

$ARGUMENTS

## Pre-check

1. Verifica ambiente: `python3 --version`
2. Analizza la richiesta e stima il numero di file coinvolti
3. Se **>3 file**: suggerisci `/plan` + `/orchestrate` e fermati
4. Se **<=3 file**: procedi con il pipeline

## Fase 1: PLAN (inline)

- Esplora il codebase per capire dove intervenire
- Identifica i file da modificare/creare
- Definisci i criteri di accettazione
- Stampa un mini-piano:

```
Piano:
  1. <azione> — <file>
  2. <azione> — <file>
  Verifica: <comando>
```

## Fase 2: IMPLEMENT

- Leggi i file PRIMA di modificarli
- Implementa il cambiamento minimale
- Segui le convenzioni del codebase:
  - Flask route decorators per endpoint
  - snake_case per funzioni/variabili
  - Type hints per le signature
  - Import: stdlib first, third-party second, local third
- Dopo ogni file modificato, verifica lint: `ruff check <file>` (se disponibile)

## Fase 3: REVIEW (self-review)

Verifica le tue modifiche leggendo i file modificati:
- [ ] Correttezza logica
- [ ] No credenziali esposte
- [ ] Naming coerente con il codebase
- [ ] Import corretti (stdlib, third-party, local)
- [ ] Type hints presenti
- [ ] Configurazioni Flask/Gunicorn corrette

Se trovi problemi: **fixa subito** prima di procedere.

Report:
```
Review:
  File modificati: N
  Problemi trovati: N (fixati inline)
  Status: CLEAN
```

## Fase 4: TEST

Esegui i test:

```bash
pytest tests/ -q 2>/dev/null || echo "No tests directory"
```

Se mancano test per le funzioni nuove: **scrivili** (se tests/ esiste).

Report:
```
Test:
  Eseguiti: <comandi>
  Risultato: PASS / FAIL / N/A (no tests)
```

## Fase 5: DOCKER BUILD CHECK

```bash
docker build -t gmt:test -f docker/Dockerfile . 2>&1 | tail -10
```

Se il build fallisce e le modifiche toccano `src/` o `docker/`: fixa prima di procedere.
Se le modifiche non toccano Docker/src: skip con `Docker: N/A`.

## Report finale

```
Auto-complete:
  Task: <descrizione>
  File: <lista file modificati>
  Review: CLEAN
  Test: PASS (N tests) / N/A
  Docker: PASS / N/A

  Per verificare: pytest tests/ -v
  Per Docker: docker build -t gmt:test -f docker/Dockerfile .
```

## Regole

- **STOP immediato** se una fase fallisce — non procedere alla successiva
- Se la fase REVIEW trova un MUST FIX, torna a IMPLEMENT
- Se la fase TEST fallisce, diagnostica e fixa, poi ri-testa
- Se il task si rivela piu' complesso del previsto (>3 file), fermati e suggerisci `/plan`
- Usa `pytest` e `ruff` direttamente (non prefissi .venv/bin/)
- Verifica sempre il Docker build quando modifichi src/ o docker/
