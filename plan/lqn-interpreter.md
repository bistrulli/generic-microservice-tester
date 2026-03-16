# Piano: LQN Task Interpreter per K8s

<!-- cross-reviewed -->
<!-- Round 1: Gemini score 9/10. Integrati: CPU resource limits nel compiler, multi-stage Docker build. Rigettati: reference task come traffic generator (design choice: load generator esterno), post-reply activities (scoped out: solo Phase 1). -->

> Trasformare GMT in un interprete completo di modelli LQN: ogni Task LQN diventa
> un microservizio K8s la cui logica (activity diagram, chiamate, routing) e'
> specificata dal frammento LQN corrispondente.

## Decisioni architetturali gia' prese

1. **Concorrenza AND-fork**: ctypes C extension + ThreadPoolExecutor
   - File C (~20 righe) che fa busy-wait rilasciando il GIL
   - `CLOCK_THREAD_CPUTIME_ID` per timing per-thread accurato
   - `time.thread_time()` da Python per verifica
   - Zero processi extra, zero overhead memoria

2. **Multi-phase**: ignorato per ora (solo Phase 1)

3. **Architettura**: compiler esterno (LQN → K8s YAML) + runtime arricchito in app.py
   - Il microservizio riceve il suo task fragment come configurazione
   - NON decomponiamo task in microservizi separati

## Modello di riferimento

File: `test/lqn-groundtruth/template_annotated.lqn`

Costrutti LQN da supportare:
- Processor con multiplicity (`p PClient f m 2`)
- Task reference/non-reference con multiplicity e think time
- Entry phase-based (`s entry phase1 -1`) e activity-based (`A entry activity`)
- Entry multiple per task (TServer ha 4 entry: visit, buy, notify, save)
- Activity con service time (`s activity time`)
- Sync calls (`y activity entry calls`)
- Async calls (`z activity entry calls`)
- Activity diagram: sequenza (`A -> B`), AND-fork/join (`A -> B & C`, `B & C -> D`), OR-fork (`A -> (p)B + (q)C`)
- Reply semantics (`activity[entry]`)
- Mean-calls > 1 e frazionari (`y client visit 3.0`, `y client buy 1.2`)

---

## Step di implementazione

### Step 1: C extension per busy-wait thread-safe

**File nuovi:**
- `src/busy_wait.c` — funzione `busy_wait_cpu(double seconds)` con `CLOCK_THREAD_CPUTIME_ID`
- Aggiornamento `docker/Dockerfile` — compilazione con gcc

**Dettaglio:**
```c
// src/busy_wait.c
#include <time.h>

// Rilascia il GIL automaticamente quando chiamato da ctypes
void busy_wait_cpu(double seconds) {
    struct timespec start, now;
    clock_gettime(CLOCK_THREAD_CPUTIME_ID, &start);
    double elapsed = 0.0;
    while (elapsed < seconds) {
        clock_gettime(CLOCK_THREAD_CPUTIME_ID, &now);
        elapsed = (now.tv_sec - start.tv_sec)
                + (now.tv_nsec - start.tv_nsec) / 1e9;
    }
}
```

**Dockerfile update:**
```dockerfile
# Aggiungere prima del COPY src/
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/*
COPY src/busy_wait.c .
RUN gcc -shared -fPIC -O2 -o busy_wait.so busy_wait.c -lrt
```

**Verifica:**
```bash
# Test compilazione locale
gcc -shared -fPIC -O2 -o src/busy_wait.so src/busy_wait.c
# Su macOS: gcc -shared -fPIC -O2 -o src/busy_wait.so src/busy_wait.c
# (macOS non ha -lrt, clock_gettime e' in libSystem)

# Test unitario
pytest tests/unit/test_busy_wait.py -v
```

**Test:**
- `test_busy_wait_single_thread` — verifica timing accurato ±10%
- `test_busy_wait_parallel_threads` — 2 thread con 0.2s + 0.3s completano in ~0.3s wall-clock
- `test_busy_wait_thread_time_accuracy` — `time.thread_time()` riporta tempo corretto per thread

---

### Step 2: LQN Parser (`src/lqn_parser.py`)

**File nuovo:** `src/lqn_parser.py`

Parser del formato `.lqn` testuale. Output: struttura dati Python che rappresenta il modello.

**Struttura output:**
```python
@dataclass
class LqnActivity:
    name: str
    service_time: float
    sync_calls: list[tuple[str, float]]    # (entry_name, mean_calls)
    async_calls: list[tuple[str, float]]   # (entry_name, mean_calls)

@dataclass
class LqnActivityGraph:
    """Rappresenta il diagramma delle attivita' di un entry"""
    sequences: list[tuple[str, str]]           # A -> B
    and_forks: list[tuple[str, list[str]]]     # A -> B & C
    and_joins: list[tuple[list[str], str]]     # B & C -> D
    or_forks: list[tuple[str, list[tuple[float, str]]]]  # A -> (p)B + (q)C
    replies: dict[str, str]                    # activity -> entry (activity[entry])

@dataclass
class LqnEntry:
    name: str
    # Phase-based entry
    phase_service_times: list[float] | None    # [phase1_time, phase2_time, ...]
    phase_sync_calls: dict[str, list[float]] | None  # entry -> [phase1_calls, ...]
    phase_async_calls: dict[str, list[float]] | None
    # Activity-based entry
    start_activity: str | None

@dataclass
class LqnTask:
    name: str
    is_reference: bool          # r vs n
    entries: list[LqnEntry]
    processor: str
    multiplicity: int
    think_time: float           # z value (solo per reference task)
    activities: dict[str, LqnActivity]
    activity_graph: LqnActivityGraph | None

@dataclass
class LqnProcessor:
    name: str
    multiplicity: int | None    # None = infinite

@dataclass
class LqnModel:
    name: str
    processors: list[LqnProcessor]
    tasks: list[LqnTask]
```

**Sezioni da parsare:**
1. Header `G` — nome modello, parametri solver
2. Processors `P 0` ... `-1` — nome, scheduling, multiplicity
3. Tasks `T 0` ... `-1` — nome, ref flag, entry list, processor, think time, multiplicity
4. Entries `E 0` ... `-1` — definizioni phase-based (`s`, `y`, `z`) e activity-based (`A`)
5. Activities `A TaskName` ... `-1` — service times, calls, activity graph (dopo `:`)

**Verifica:**
```bash
pytest tests/unit/test_lqn_parser.py -v
```

**Test:**
- `test_parse_header` — estrae nome modello
- `test_parse_processors` — estrae processori con multiplicity
- `test_parse_tasks` — estrae task con entry, processor, multiplicity, think time
- `test_parse_phase_entries` — entry con `s entry phase1 -1` e chiamate `y`/`z`
- `test_parse_activity_entries` — entry con `A entry activity`
- `test_parse_activities_service_time` — `s activity time`
- `test_parse_activities_calls` — `y activity entry calls` e `z activity entry calls`
- `test_parse_activity_graph_sequence` — `A -> B`
- `test_parse_activity_graph_and_fork` — `A -> B & C`
- `test_parse_activity_graph_and_join` — `B & C -> D`
- `test_parse_activity_graph_or_fork` — `A -> (0.95)B + (0.05)C`
- `test_parse_activity_graph_reply` — `activity[entry]`
- `test_parse_comments` — `# commenti` ignorati
- `test_parse_template_annotated` — parsing completo del modello ground truth
- `test_parse_mean_calls_fractional` — `y client buy 1.2` → mean_calls=1.2

---

### Step 3: Activity Engine in `app.py`

**File modificato:** `src/app.py`

Nuovo motore di esecuzione che interpreta activity diagram LQN.

**Nuove funzionalita':**
1. **Entry multiple** — routing `GET /<entry_name>` basato su configurazione
2. **Activity execution** — esegue attivita' con service time via ctypes busy-wait
3. **AND-fork/join** — ThreadPoolExecutor per branch paralleli
4. **OR-fork** — random.choices con pesi (gia' esistente, da generalizzare)
5. **Sequenza** — esecuzione seriale di attivita'
6. **Reply semantics** — `activity[entry]` determina quando inviare la response
7. **Mean-calls** — loop di chiamate con supporto frazionario (1.2 = 1 call + 20% 2nd)

**Nuova configurazione (env var):**
```
LQN_TASK_CONFIG=<json>
```

Formato JSON del task fragment:
```json
{
  "task_name": "TServer",
  "entries": {
    "visit": {"start_activity": "cache"},
    "buy": {"start_activity": "prepare"},
    "save": {"service_time": 0.02, "sync_calls": {"write": 1.0}},
    "notify": {"service_time": 0.08}
  },
  "activities": {
    "prepare": {"service_time": 0.01},
    "pack": {"service_time": 0.03},
    "ship": {"service_time": 0.01},
    "display": {"service_time": 0.001},
    "cache": {"service_time": 0.001},
    "internal": {"service_time": 0.001},
    "external": {"service_time": 0.003, "sync_calls": {"read-svc": 1.0}}
  },
  "graph": {
    "sequences": [["prepare", "fork:pack,ship"], ["join:pack,ship", "display"]],
    "or_forks": [{"from": "cache", "branches": [{"prob": 0.95, "to": "internal"}, {"prob": 0.05, "to": "external"}]}],
    "and_forks": [{"from": "prepare", "branches": ["pack", "ship"]}],
    "and_joins": [{"branches": ["pack", "ship"], "to": "display"}],
    "replies": {"internal": "visit", "external": "visit", "display": "buy"}
  }
}
```

**Backward compatibility:**
- Se `LQN_TASK_CONFIG` e' definito → usa il nuovo motore
- Se non definito → usa il comportamento legacy (SERVICE_TIME_SECONDS + OUTBOUND_CALLS)
- I due path sono mutuamente esclusivi

**Nuove funzioni in app.py:**
```python
def load_task_config() -> dict | None:
    """Carica LQN_TASK_CONFIG da env var. Ritorna None se non definito."""

def execute_activity(activity_name: str, config: dict) -> dict:
    """Esegue una singola attivita': service time + eventuali chiamate."""

def execute_activity_graph(entry_name: str, config: dict) -> list[dict]:
    """Esegue l'activity graph di un entry, gestendo fork/join/choice/reply."""

def execute_and_fork(branches: list[str], config: dict) -> list[dict]:
    """Esegue branch AND-fork in parallelo via ThreadPoolExecutor + ctypes.
    AND-join: concurrent.futures.wait(futures) attende tutti i branch."""

def execute_or_fork(branches: list[dict], config: dict) -> list[dict]:
    """Sceglie un branch OR-fork con random.choices."""

def execute_mean_calls(target: str, mean_calls: float) -> list[dict]:
    """Esegue N chiamate dove N e' campionato da mean_calls.
    Se mean_calls=3.0 → 3 chiamate.
    Se mean_calls=1.2 → 1 chiamata + 20% probabilita' di 2a chiamata."""
```

**Route update:**
```python
@app.route('/')
@app.route('/<entry_name>')
def handle_request(entry_name=None):
    config = load_task_config()
    if config and entry_name:
        return execute_entry(entry_name, config)
    elif config and not entry_name:
        # Default: prima entry del task
        return execute_entry(list(config['entries'].keys())[0], config)
    else:
        # Legacy behavior
        return handle_request_legacy()
```

**Verifica:**
```bash
pytest tests/unit/test_activity_engine.py -v
```

**Test:**
- `test_execute_activity_service_time` — attivita' con solo service time
- `test_execute_activity_with_sync_call` — attivita' con chiamata sync (mock)
- `test_execute_activity_with_async_call` — attivita' con chiamata async
- `test_execute_sequence` — A -> B eseguiti in ordine
- `test_execute_and_fork` — pack & ship in parallelo (wall-clock ≈ max)
- `test_execute_and_join` — attende entrambi i branch, poi continua
- `test_execute_or_fork` — scelta probabilistica corretta (test statistico)
- `test_execute_reply` — response inviata al punto giusto del grafo
- `test_execute_mean_calls_integer` — 3.0 → esattamente 3 chiamate
- `test_execute_mean_calls_fractional` — 1.2 → 1 + 20% chance di 2a
- `test_handle_request_legacy_compat` — senza LQN_TASK_CONFIG, comportamento invariato
- `test_handle_request_entry_routing` — GET /visit vs GET /buy
- `test_execute_template_annotated_visit` — activity graph completo per entry visit
- `test_execute_template_annotated_buy` — AND-fork/join completo per entry buy

---

### Step 4: LQN-to-K8s Compiler (`tools/lqn_compiler.py`)

**File nuovo:** `tools/lqn_compiler.py`

CLI che legge un file `.lqn` e genera manifesti K8s completi.

**Mapping LQN → K8s:**

| LQN | K8s | Dettaglio |
|---|---|---|
| Processor (m=N) | Pod resource limits | Multiplicity → CPU requests/limits |
| Task (non-ref, m=N) | Deployment + Service | multiplicity → GUNICORN_WORKERS=N |
| Task (ref) | SKIP (load generator esterno) | Reference task = workload driver |
| Entry | HTTP endpoint `/<entry_name>` | Parte di LQN_TASK_CONFIG |
| Activity graph | JSON in LQN_TASK_CONFIG | Serializzato come env var |
| Service time | Dentro LQN_TASK_CONFIG | Per-activity, non globale |
| y (sync call) | Dentro LQN_TASK_CONFIG | Target → `<task>-svc` K8s DNS |
| z (async call) | Dentro LQN_TASK_CONFIG | Target → `<task>-svc` K8s DNS |

**Risoluzione nomi:**
Il compiler deve risolvere i nomi LQN (entry) → nomi K8s (service DNS):
- Entry `read` di Task `TFileServer` → URL `http://tfileserver-svc/read`
- L'entry name diventa il path HTTP, il task name diventa il service DNS

**Output YAML generato:**
Per ogni Task non-reference:
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: <task-name>-deployment
  labels:
    app.kubernetes.io/name: <task-name>
    app.kubernetes.io/component: lqn-task
    lqn.gmt/model: <model-name>
spec:
  replicas: 1
  selector:
    matchLabels:
      app: <task-name>
  template:
    metadata:
      labels:
        app: <task-name>
    spec:
      containers:
      - name: app
        image: generic-microservice-tester:latest
        ports:
        - containerPort: 8080
        resources:
          requests:
            cpu: "<processor-multiplicity>00m"
          limits:
            cpu: "<processor-multiplicity>00m"
        env:
        - name: SERVICE_NAME
          value: "<task-name>"
        - name: GUNICORN_WORKERS
          value: "<task-multiplicity>"
        - name: LQN_TASK_CONFIG
          value: '<json-task-fragment>'
---
apiVersion: v1
kind: Service
metadata:
  name: <task-name>-svc
spec:
  selector:
    app: <task-name>
  ports:
  - port: 80
    targetPort: 8080
```

**CLI:**
```bash
# Genera YAML e stampa su stdout
python tools/lqn_compiler.py test/lqn-groundtruth/template_annotated.lqn

# Genera e applica direttamente
python tools/lqn_compiler.py template_annotated.lqn | kubectl apply -f -

# Genera con image custom
python tools/lqn_compiler.py --image myregistry/gmt:v1.0 template_annotated.lqn

# Genera e salva su file
python tools/lqn_compiler.py template_annotated.lqn -o kubernetes/generated/template.yaml

# Dry-run: mostra cosa verrebbe generato senza scrivere
python tools/lqn_compiler.py --dry-run template_annotated.lqn
```

**Verifica:**
```bash
pytest tests/unit/test_lqn_compiler.py -v
# Validazione K8s
python tools/lqn_compiler.py test/lqn-groundtruth/template_annotated.lqn | kubectl apply --dry-run=client -f -
```

**Test:**
- `test_compile_generates_deployment_per_task` — 1 Deployment per Task non-reference
- `test_compile_generates_service_per_task` — 1 Service per Task non-reference
- `test_compile_skips_reference_task` — TClient (ref) non genera Deployment
- `test_compile_task_multiplicity` — GUNICORN_WORKERS = task multiplicity
- `test_compile_entry_to_config` — entry mappate in LQN_TASK_CONFIG JSON
- `test_compile_activity_graph_serialized` — activity graph serializzato correttamente
- `test_compile_call_target_resolution` — `y external read 1.0` → target `tfileserver-svc`
- `test_compile_service_naming` — service name = `<task-lower>-svc`
- `test_compile_valid_k8s_yaml` — output e' YAML valido per K8s API
- `test_compile_template_annotated_full` — compilazione completa del ground truth model
- `test_compile_labels` — label standard app.kubernetes.io/*

---

### Step 5: Docker build update

**File modificato:** `docker/Dockerfile`

**Modifiche:**
1. Installare `gcc` per compilare `busy_wait.c`
2. Copiare e compilare `busy_wait.c` → `busy_wait.so`
3. Copiare nuovi file Python (`lqn_parser.py`, ecc.)

**Nuovo Dockerfile (multi-stage build):**
<!-- Round 1: multi-stage build suggerito da Gemini per ridurre footprint image -->
```dockerfile
# Stage 1: Build C extension
FROM python:3.12-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY src/busy_wait.c .
RUN gcc -shared -fPIC -O2 -o busy_wait.so busy_wait.c

# Stage 2: Runtime image (no gcc)
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

COPY src/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiare C extension compilata dallo stage builder
COPY --from=builder /build/busy_wait.so .

# Copiare codice applicativo
COPY src/app.py .
COPY src/lqn_parser.py .
COPY docker/entrypoint.sh .
RUN chmod +x entrypoint.sh

EXPOSE 8080
CMD ["./entrypoint.sh"]
```

**Verifica:**
```bash
docker build -f docker/Dockerfile -t gmt-test:latest .
docker run -e SERVICE_NAME=test -e SERVICE_TIME_SECONDS=0.1 -p 8080:8080 gmt-test:latest
curl http://localhost:8080/
```

---

### Step 6: Test E2E su K8s (Rancher Desktop)

**File nuovi:** `tests/e2e/test_template_topology.py`

**Pre-requisiti:**
- Rancher Desktop attivo con K8s
- Docker image buildata e disponibile nel cluster
- `kubectl` configurato

**Scenario E2E per `template_annotated.lqn`:**

Il modello ha 4 task → 3 microservizi (TClient e' reference, skip):
- `tserver-svc` (entry: visit, buy, notify, save)
- `tfileserver-svc` (entry: read, write)
- `tbackup-svc` (entry: get, update)

**Test flow:**
1. Compilare LQN → YAML: `python tools/lqn_compiler.py template_annotated.lqn`
2. Deploy su K8s: `kubectl apply -f <generated.yaml>`
3. Wait for pods ready
4. Port-forward al servizio entry
5. Simulare il workload di TClient:
   - `GET /visit` su tserver-svc → verifica OR-fork (95% internal, 5% external)
   - `GET /buy` su tserver-svc → verifica AND-fork (pack & ship paralleli)
   - `GET /save` su tserver-svc → verifica chain save → write → get/update
   - `GET /notify` su tserver-svc → verifica fire-and-forget
6. Cleanup: `kubectl delete -f <generated.yaml>`

**Test:**
- `test_e2e_deploy_topology` — tutti i pod Running
- `test_e2e_visit_entry` — GET /visit ritorna response, verifica OR-fork
- `test_e2e_buy_entry` — GET /buy ritorna response, verifica AND-fork timing
- `test_e2e_save_entry` — GET /save chiama write che chiama get+update
- `test_e2e_notify_entry` — GET /notify ritorna subito (async)
- `test_e2e_buy_parallel_timing` — wall-clock di /buy ≈ max(pack, ship) non sum
- `test_e2e_visit_probability_distribution` — 100 requests, ~95% internal ~5% external

---

## Ordine di implementazione e dipendenze

```
Step 1: busy_wait.c + test
    │
    ├── Step 2: lqn_parser.py + test (indipendente da Step 1)
    │
    └──── Step 3: activity engine in app.py + test
              │   (dipende da Step 1 per AND-fork, Step 2 per config format)
              │
              ├── Step 4: lqn_compiler.py + test (dipende da Step 2 e Step 3)
              │
              ├── Step 5: Dockerfile update (dipende da Step 1 e Step 3)
              │
              └── Step 6: E2E test (dipende da tutti)
```

**Step 1 e Step 2 possono essere implementati in parallelo.**

---

## Test plan completo

### Unit test
- [ ] `tests/unit/test_busy_wait.py` — C extension timing e parallelismo
- [ ] `tests/unit/test_lqn_parser.py` — parsing di tutte le sezioni LQN
- [ ] `tests/unit/test_activity_engine.py` — esecuzione activity graph
- [ ] `tests/unit/test_lqn_compiler.py` — generazione YAML K8s
- [ ] `tests/unit/test_app_legacy.py` — regressione: comportamento legacy invariato

### Integration test
- [ ] `tests/integration/test_docker_build.py` — Docker image si builda e risponde

### E2E test (K8s)
- [ ] `tests/e2e/test_template_topology.py` — deploy e verifica topologia completa

### Comandi di verifica
```bash
# Unit test
pytest tests/unit/ -v --tb=short

# Lint
ruff check src/ tools/

# Docker build
docker build -f docker/Dockerfile -t gmt-test:latest .

# K8s dry-run
python tools/lqn_compiler.py test/lqn-groundtruth/template_annotated.lqn \
  | kubectl apply --dry-run=client -f -

# E2E (richiede cluster K8s attivo)
pytest tests/e2e/ -v --tb=short -s
```

---

## Rischi e mitigazioni

| Rischio | Probabilita' | Impatto | Mitigazione |
|---|---|---|---|
| `CLOCK_THREAD_CPUTIME_ID` non disponibile su macOS | Media | Alto | Fallback a `time.thread_time()` Python che funziona su entrambi |
| GCC non installabile in Docker slim | Bassa | Alto | Multi-stage build: compilare in stage con gcc, copiare .so in slim |
| LQN_TASK_CONFIG troppo grande per env var | Bassa | Medio | K8s supporta fino a ~1MB per env var; alternativa: ConfigMap mount |
| AND-fork timing non accurato con molti thread | Bassa | Medio | Limitare ThreadPoolExecutor a max 8 branch paralleli |
| Backward compatibility rotta | Media | Alto | Test regressione dedicati, flag esplicito LQN_TASK_CONFIG |
| Parser LQN non copre tutti i dialetti | Alta | Basso | Supportare SOLO il formato del template annotato; errore chiaro per costrutti non supportati |

---

## File coinvolti (sommario)

| File | Azione | Step |
|---|---|---|
| `src/busy_wait.c` | NUOVO | 1 |
| `src/lqn_parser.py` | NUOVO | 2 |
| `src/app.py` | MODIFICATO (activity engine + entry routing) | 3 |
| `tools/lqn_compiler.py` | NUOVO | 4 |
| `docker/Dockerfile` | MODIFICATO (gcc + compilazione C) | 5 |
| `src/requirements.txt` | INVARIATO | — |
| `docker/entrypoint.sh` | INVARIATO | — |
| `kubernetes/base/*` | INVARIATO (generatore produce YAML autonomamente) | — |
| `kubernetes/examples/*` | INVARIATO | — |
| `tests/unit/test_busy_wait.py` | NUOVO | 1 |
| `tests/unit/test_lqn_parser.py` | NUOVO | 2 |
| `tests/unit/test_activity_engine.py` | NUOVO | 3 |
| `tests/unit/test_lqn_compiler.py` | NUOVO | 4 |
| `tests/unit/test_app_legacy.py` | NUOVO | 3 |
| `tests/e2e/test_template_topology.py` | NUOVO | 6 |
| `tests/conftest.py` | NUOVO | 1 |
