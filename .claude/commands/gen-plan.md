# GMT Planning Agent — 2-Wave Parallel Research Pipeline

Sei l'agente di pianificazione per Generic Microservice Tester (GMT). Genera piani di implementazione attraverso ricerca parallela in 2 ondate.

**Input richiesto**: `$ARGUMENTS` (descrizione della feature/modifica da pianificare)

## Contesto progetto

GMT e' un microservizio Flask/Gunicorn single-image, target di compilazione LQN. Struttura:

```
src/app.py              # Flask app principale (do_work, parse_outbound_calls, make_call, handle_request)
src/requirements.txt    # Dipendenze Python
docker/Dockerfile       # Build container
docker/entrypoint.sh    # Avvio Gunicorn
kubernetes/base/        # Template deployment + service
kubernetes/examples/    # Topologie esempio (2-tier, chain, choice)
tests/                  # Test pytest
```

Env vars chiave: SERVICE_NAME, SERVICE_TIME_SECONDS, OUTBOUND_CALLS, GUNICORN_WORKERS, GUNICORN_THREADS

## Wave 1: Ricerca parallela (max 7 agenti)

Lancia fino a 7 agenti di ricerca in parallelo. Ogni agente ha un focus specifico.

### Agente `impact`
- Mappa TUTTI i file che saranno impattati dalla modifica
- Per `src/app.py`: identifica funzioni coinvolte (do_work, parse_outbound_calls, make_call, make_async_call_pooled, handle_request)
- Per `docker/`: impatto su Dockerfile, entrypoint.sh
- Per `kubernetes/`: impatto su deployment.yaml, service.yaml, esempi
- Produci grafo delle dipendenze tra componenti

### Agente `patterns`
- Analizza i pattern esistenti nel codebase:
  - Flask app patterns (routes, jsonify, env var config)
  - Gunicorn worker model (sync workers, process isolation)
  - K8s manifest patterns (Deployment, Service, env vars)
  - LQN-semantic patterns (SYNC/ASYNC calls, probabilistic routing)
  - Busy-wait CPU simulation con psutil
- Documenta le convenzioni da rispettare

### Agente `tests`
- Inventario completo dei test esistenti in `tests/`
- Identifica coverage gaps per la feature richiesta
- Proponi nuovi test necessari
- Pattern da usare: pytest, Flask test_client, mock per psutil/requests

### Agente `web-research`
- Cerca informazioni su:
  - Microservice test harnesses e topology generators
  - K8s performance testing frameworks
  - LQN tools e solvers (lqns, lqsim)
  - Flask/Gunicorn best practices per il caso d'uso specifico
- Usa WebSearch per trovare risorse rilevanti

### Agente `academic`
- Cerca pubblicazioni su:
  - Layered Queueing Networks (LQN) — teoria e applicazioni
  - Performance modeling di microservizi
  - Model-driven deployment di architetture distribuite
  - Calibrazione e validazione di modelli di performance
- Usa WebSearch con query accademiche

### Agente `lqn-domain`
- Analizza vincoli del dominio LQN:
  - Mapping task LQN → deployment K8s
  - Mapping entry LQN → endpoint Flask
  - Mapping activity LQN → do_work() + outbound calls
  - Vincoli: multiplicity → replicas, service time → SERVICE_TIME_SECONDS
  - Semantica chiamate: sync (y) → SYNC, async (z) → ASYNC

### Agente `k8s`
- Analizza configurazione K8s e Docker:
  - Manifesti esistenti in `kubernetes/`
  - Dockerfile e entrypoint.sh
  - Resource requests/limits, probes
  - Pattern di deployment multi-servizio
  - HPA configuration

## Wave 2: Challenge (2 agenti)

Dopo Wave 1, lancia 2 agenti che sfidano i risultati.

### Agente `devil`
- Cerca falle nel piano proposto
- Verifica: la modifica rompe la compatibilita' LQN?
- Verifica: la modifica funziona con N worker Gunicorn?
- Verifica: i K8s manifesti restano validi?
- Verifica: la Docker image si builda ancora?

### Agente `simplifier`
- Cerca la soluzione piu' semplice possibile
- Elimina complessita' non necessaria
- Proponi alternative con meno file modificati
- Verifica che non si stia over-engineering

## Sintesi del piano

Dopo entrambe le wave, sintetizza in un documento strutturato:

```markdown
# Piano: [titolo feature]

## Contesto
[Sintesi della ricerca Wave 1]

## Modifiche pianificate

### Step 1: [descrizione]
- File: `path/to/file`
- Modifica: [cosa cambia e perche']
- Verifica: [comando di test]

### Step 2: ...

## Test plan
- [ ] Unit test: [descrizione]
- [ ] Integration test: [descrizione]
- [ ] Docker build: `docker build -t gmt-test -f docker/Dockerfile .`
- [ ] K8s validation: `kubectl apply --dry-run=client -f kubernetes/base/`
- [ ] Lint: `ruff check src/`

## Rischi e mitigazioni
[Dal devil's advocate]

## Alternative considerate
[Dal simplifier]
```

## Output

Salva il piano in `plan/$ARGUMENTS.md` (sanitizza il nome file).

Al termine, rispondi:

> Piano salvato in `plan/<feature>.md`. Lancia `/orchestrate plan/<feature>.md` per eseguirlo.

## Comandi di verifica

```bash
# Test
pytest tests/ -v --tb=short

# Lint
ruff check src/

# Docker build
docker build -t gmt-test:latest -f docker/Dockerfile .

# K8s validation
kubectl apply --dry-run=client -f kubernetes/base/deployment.yaml
kubectl apply --dry-run=client -f kubernetes/base/service.yaml
```
