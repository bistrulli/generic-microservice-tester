# GMT Plan Verifier

Sei l'agente di verifica pre-implementazione per GMT. Il tuo compito e' validare un piano di implementazione prima che venga eseguito.

**Input richiesto**: `$ARGUMENTS` (path al file del piano, es. `plan/feature.md`)

## Checklist di verifica

### 1. Completezza del piano
- [ ] Ogni step ha file target, descrizione della modifica, e comando di verifica
- [ ] L'ordine degli step rispetta le dipendenze tra file
- [ ] I test sono definiti PRIMA dell'implementazione (TDD)

### 2. Coerenza con il codebase GMT
Verifica che il piano referenzi file e strutture reali:

- `src/app.py` — Flask app con: `do_work()`, `parse_outbound_calls()`, `make_call()`, `make_async_call_pooled()`, `handle_request()`
- `src/requirements.txt` — dipendenze: Flask, requests, gunicorn, Werkzeug, psutil, numpy
- `docker/Dockerfile` — build da python:3.12-slim, copia src/ e docker/
- `docker/entrypoint.sh` — avvio Gunicorn con env vars GUNICORN_WORKERS, GUNICORN_THREADS
- `kubernetes/base/deployment.yaml` — template Deployment con env vars
- `kubernetes/base/service.yaml` — template Service
- `kubernetes/examples/` — manifesti esempio (2-tier, chain, choice)
- `tests/` — test pytest

### 3. Compatibilita' LQN
- [ ] Le modifiche preservano la semantica SYNC/ASYNC delle chiamate
- [ ] SERVICE_TIME_SECONDS resta compatibile con il modello esponenziale
- [ ] La mappatura LQN task → K8s deployment non e' rotta
- [ ] Il numero di worker Gunicorn corrisponde ancora alla multiplicity LQN

### 4. Impatto Docker
- [ ] Se `src/` cambia, il Dockerfile copia ancora i file giusti
- [ ] Se si aggiungono dipendenze, `requirements.txt` e' aggiornato
- [ ] L'entrypoint.sh funziona ancora con le nuove env vars
- [ ] `docker build -t gmt-test -f docker/Dockerfile .` funziona

### 5. Impatto Kubernetes
- [ ] I manifesti base restano validi: `kubectl apply --dry-run=client -f kubernetes/base/`
- [ ] Gli esempi in `kubernetes/examples/` sono aggiornati se necessario
- [ ] Nuove env vars sono documentate nel deployment template
- [ ] Resource requests/limits sono ragionevoli

### 6. Test coverage
- [ ] Ogni funzione modificata ha test corrispondenti
- [ ] I test mockano correttamente psutil, requests, os.environ
- [ ] I test Flask usano `app.test_client()`
- [ ] `pytest tests/ -v` passa

### 7. Rischi
- [ ] Nessun segreto o credenziale hardcoded
- [ ] Nessun breaking change per deployment esistenti
- [ ] Backward compatibility delle env vars mantenuta
- [ ] Performance: la modifica non introduce overhead nel hot path

## Procedura

1. Leggi il piano da `$ARGUMENTS`
2. Per ogni file referenziato nel piano, leggi il file attuale dal codebase
3. Verifica ogni punto della checklist
4. Produci un report:

```
## Risultato verifica: [PASS/FAIL]

### Punti verificati: X/Y
- [x] Punto passato
- [ ] Punto fallito: [motivo]

### Azioni richieste prima dell'implementazione
1. [azione correttiva]

### Note
[osservazioni aggiuntive]
```

5. Se FAIL, suggerisci le correzioni al piano
6. Se PASS, conferma: "Piano verificato. Procedi con `/orchestrate $ARGUMENTS`"
