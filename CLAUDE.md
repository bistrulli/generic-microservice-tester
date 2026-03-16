# CLAUDE.md — Generic Microservice Tester

> Istruzioni operative per lo sviluppo assistito da Claude Code.
> Questo file viene letto automaticamente all'apertura del progetto.

---

## Panoramica

**Generic Microservice Tester** e' un microservizio configurabile a immagine singola, progettato per simulare topologie applicative complesse su Kubernetes. Ogni istanza del container viene configurata interamente tramite variabili d'ambiente, eliminando la necessita' di scrivere codice applicativo custom per ogni servizio.

**Visione**: il progetto e' pensato come *compilation target* per modelli LQN (Layered Queueing Network). Ogni Task LQN viene mappato su un Deployment K8s con variabili d'ambiente che ne definiscono il comportamento (tempo di servizio, chiamate uscenti, concorrenza). Basato sul paper muP (Garbi, Incerto, Tribastone — IEEE CLOUD 2023).

**Stack tecnologico**: Python 3.12, Flask, Gunicorn, psutil, numpy, requests, Docker, Kubernetes.

---

## Python Environment

```bash
# Creare il virtual environment
python3.12 -m venv .venv
source .venv/bin/activate

# Installare le dipendenze
pip install -r src/requirements.txt

# Linting e formatting
ruff check src/
ruff format src/
```

> **Nota**: i hook di Claude Code eseguono `ruff format` e `ruff check --fix` automaticamente su ogni file `.py` modificato.

---

## Struttura Progetto

```
generic-microservice-tester/
├── src/
│   ├── app.py              # App Flask principale (tempi di servizio stocastici, CPU psutil, chiamate async)
│   └── requirements.txt     # Dipendenze Python
├── docker/
│   ├── Dockerfile          # Basato su python:3.12-slim
│   └── entrypoint.sh       # Launcher Gunicorn
├── kubernetes/
│   ├── base/
│   │   ├── deployment.yaml # Template generico di deployment
│   │   └── service.yaml    # Template generico di service
│   └── examples/
│       ├── 2-tier-app.yaml  # Topologia a 2 livelli
│       ├── 2-tier-hpa.yaml  # 2 livelli con HPA
│       ├── chain-app.yaml   # Catena di servizi
│       └── choice-app.yaml  # Routing probabilistico
├── plan/                    # Piani di implementazione (per /orchestrate)
├── .claude/
│   ├── settings.json        # Permessi e hook
│   ├── settings.local.json  # Override locali
│   ├── commands/            # Slash commands
│   └── skills/              # Knowledge base per lo sviluppo
├── CLAUDE.md                # Questo file
└── README.md                # Documentazione pubblica
```

---

## Componenti Chiave

| Componente | File | Descrizione |
|---|---|---|
| **Tempo di servizio stocastico** | `src/app.py` → `do_work()` | Distribuzione esponenziale con media configurabile via `SERVICE_TIME_SECONDS`. Ogni richiesta campiona un tempo di servizio diverso. |
| **CPU delta tracking (psutil)** | `src/app.py` → `do_work()` | Tracciamento del tempo CPU user-space per processo. Usa delta tracking per isolare il consumo CPU di ogni singola richiesta nel worker Gunicorn persistente. |
| **Busy-wait preciso** | `src/app.py` → `do_work()` | Consumo CPU effettivo tramite `time.process_time()`. Calcola il lavoro residuo sottraendo il tempo CPU ereditato dalle richieste precedenti. |
| **Chiamate sincrone (SYNC)** | `src/app.py` → `make_call()` | Chiamate HTTP bloccanti via `requests.Session` condivisa con connection pooling (100 connessioni). |
| **Chiamate asincrone (ASYNC)** | `src/app.py` → `make_async_call_pooled()` | Fire-and-forget tramite `ThreadPoolExecutor` isolato per worker. Sessione HTTP dedicata, semantica LQN "send-no-reply". |
| **Routing probabilistico** | `src/app.py` → `handle_request()` | Chiamate con probabilita' < 1.0 vengono scelte con `random.choices` (weighted). Chiamate con probabilita' >= 1.0 vengono sempre eseguite. |
| **Parsing configurazione** | `src/app.py` → `parse_outbound_calls()` | Parsing di `OUTBOUND_CALLS` nel formato `TYPE:service_name:probability`. Separa chiamate fisse da probabilistiche. |
| **Gunicorn launcher** | `docker/entrypoint.sh` | Configura workers, threads e worker-class sync per timing CPU accurato. |

---

## LQN <-> K8s Mapping

Mappatura critica tra entita' LQN e costrutti Kubernetes/microservizio:

| Entita' LQN | Mapping K8s/Microservizio | Variabile d'Ambiente |
|---|---|---|
| **Processor** | Pod (resource limits `cpu`/`memory`) | — |
| **Task** | Deployment (`replicas` = livello di concorrenza) | `GUNICORN_WORKERS` |
| **Entry** | Endpoint HTTP (`/`) | `SERVICE_NAME` |
| **Activity** | CPU busy-wait (distribuzione esponenziale) | `SERVICE_TIME_SECONDS` |
| **Sync Call (y)** | Chiamata SYNC uscente (bloccante) | `OUTBOUND_CALLS` |
| **Async Call (z)** | Chiamata ASYNC uscente (fire-and-forget) | `OUTBOUND_CALLS` |
| **Open Workload** | Generatore di carico esterno (e.g., k6, hey) | — |

### Esempio di traduzione LQN -> YAML

Un Task LQN con service time medio 0.2s, 3 worker, che chiama sincronamente un altro Task:

```yaml
env:
- name: SERVICE_NAME
  value: "task-a"
- name: SERVICE_TIME_SECONDS
  value: "0.2"
- name: GUNICORN_WORKERS
  value: "3"
- name: OUTBOUND_CALLS
  value: "SYNC:task-b-svc:1.0"
```

---

## Convenzioni Codice

### Python
- **Naming**: `snake_case` per funzioni e variabili, `PascalCase` per classi, `UPPER_CASE` per costanti
- **Type hints**: sempre sulle firme delle funzioni
- **Stringhe**: f-strings per formattazione, mai `%` o `.format()`
- **Import**: stdlib prima, third-party dopo, locali per ultimi. Import assoluti
- **Eccezioni**: catturare eccezioni specifiche, mai `except:` generico
- **Docstring**: ogni funzione pubblica deve avere una docstring che spiega il *perche'*, non solo il *cosa*
- **Variabili globali worker-level**: prefisso `_` per stato interno al worker (e.g., `_last_user_time`)

### YAML (Kubernetes)
- Indentazione a 2 spazi
- Sempre specificare `resources.requests` e `resources.limits`
- Label standard: `app.kubernetes.io/name`, `app.kubernetes.io/component`
- Mai hardcodare credenziali nei manifest

### Docker
- Immagine base: `python:3.12-slim`
- `PYTHONUNBUFFERED=1` sempre attivo
- Usare `exec` nell'entrypoint per signal forwarding corretto

---

## Comandi Rapidi

```bash
# Build Docker image
docker build -f docker/Dockerfile -t generic-microservice-tester:latest .

# Run locale (senza K8s)
docker run -e SERVICE_NAME=test -e SERVICE_TIME_SECONDS=0.1 -p 8080:8080 generic-microservice-tester:latest

# Deploy su Kubernetes
kubectl apply -f kubernetes/examples/2-tier-app.yaml

# Eliminare un deployment
kubectl delete -f kubernetes/examples/2-tier-app.yaml

# Test locale con curl
curl http://localhost:8080/

# Linting
ruff check src/
ruff format --check src/

# Installare dipendenze
pip install -r src/requirements.txt
```

---

## Slash Commands

| Comando | Descrizione |
|---|---|
| `/orchestrate` | Analizza una richiesta complessa, crea piano dettagliato con task tracciabili |
| `/plan` | Genera un piano di implementazione strutturato senza eseguire codice |
| `/implement` | Esegue l'implementazione seguendo un piano esistente, un task alla volta |
| `/auto` | Modalita' autonoma: pianifica, implementa e verifica in sequenza |
| `/cross-review` | Review incrociata del codice con prospettive multiple (sicurezza, performance, manutenibilita') |
| `/lqn-expert` | Consulenza specialistica su modelli LQN e mapping verso K8s |
| `/challenge-perf` | Analisi critica delle performance: identifica bottleneck e propone ottimizzazioni |
| `/audit` | Audit completo del progetto: struttura, sicurezza, best practice |
| `/detect-bs` | Verifica affermazioni tecniche nel codice o nella documentazione |
| `/review` | Code review standard con focus su correttezza e stile |
| `/test` | Genera o esegue test per il componente specificato |
| `/gen-plan` | Genera un piano di implementazione e lo salva in `plan/` |
| `/refine` | Raffina una singola componente con miglioramenti incrementali |
| `/refine-full` | Raffinamento completo del progetto con analisi approfondita |
| `/refine-model` | Raffina il mapping LQN-K8s e la fedelta' del modello |
| `/benchmark` | Crea o esegue benchmark di performance per il microservizio |
| `/ci-check` | Verifica che il progetto passi tutti i controlli CI (lint, test, build) |
| `/prepare` | Prepara il progetto per un rilascio: changelog, versioning, check finali |
| `/sync-docs` | Sincronizza documentazione con lo stato attuale del codice |
| `/cleanup-plans` | Rimuove piani completati o obsoleti dalla directory `plan/` |
| `/cleanup-branches` | Pulisce branch Git locali e remoti non piu' necessari |
| `/verify-plan` | Verifica lo stato di completamento di un piano esistente |

---

## Configuration (Variabili d'Ambiente)

| Variabile | Default | Descrizione | Esempio |
|---|---|---|---|
| `SERVICE_NAME` | `generic-service` | Nome identificativo dell'istanza del servizio | `frontend` |
| `SERVICE_TIME_SECONDS` | `0` | Media della distribuzione esponenziale per il tempo di servizio CPU (secondi) | `0.2` |
| `OUTBOUND_CALLS` | `""` | Chiamate HTTP uscenti. Formato: `TYPE:service:prob,...` | `SYNC:backend:0.6,ASYNC:logger:1.0` |
| `GUNICORN_WORKERS` | `2` | Numero di worker processes Gunicorn | `4` |
| `GUNICORN_THREADS` | `1` | Numero di thread per worker (1 = process-based per timing CPU accurato) | `1` |

### Formato OUTBOUND_CALLS

```
TYPE:SERVICE_NAME:PROBABILITY[,TYPE:SERVICE_NAME:PROBABILITY,...]
```

- **TYPE**: `SYNC` (bloccante, attende risposta) o `ASYNC` (fire-and-forget)
- **SERVICE_NAME**: nome del Service K8s da chiamare
- **PROBABILITY**: `1.0` = sempre eseguita; `< 1.0` = scelta probabilistica (solo una tra le probabilistiche viene eseguita per richiesta, scelta con weighted random)

---

## Note per lo Sviluppo

- Il busy-wait usa `time.process_time()` per misurare tempo CPU effettivo, non wall-clock time
- Ogni worker Gunicorn ha stato isolato (`_last_user_time`, `SESSION`, `ASYNC_SESSION`, `ASYNC_EXECUTOR`)
- Il delta tracking gestisce automaticamente il restart dei worker
- Le chiamate ASYNC usano un `ThreadPoolExecutor` separato per non interferire con il timing CPU del processo principale
- I manifest K8s in `kubernetes/examples/` sono pronti all'uso e autocontenuti (deployment + service)
