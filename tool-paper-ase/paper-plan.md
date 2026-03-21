# Contesto: LQN-to-Microservices Deployment — ASE 2026 Paper

## Chi sono e cosa sto facendo

Sono un ricercatore accademico che ha sviluppato un tool che **deploya modelli LQN (Layered Queueing Networks) come sistemi microservizi reali** su Kubernetes. Sto valutando di sottomettere un paper al track **Tools and Datasets di ASE 2026** (deadline: 11 maggio 2026, Monaco, ACM proceedings).

---

## Il tool — descrizione tecnica

Il tool è scritto in **Python**, deployato su **Kubernetes**, ed è già **open source**.

### Pipeline completa:
```
LQN model (input, semantica activity-based)
      ↓
  [Parser LQN V5]       → dataclass LqnModel (parser completo V5 subset)
      ↓
  [K8s manifest gen]    → Deployment + Service YAML + OTEL annotations
  [Load gen]            → Locustfile dal reference task LQN
  [Deploy script gen]   → deploy.sh (up/down/test) con Locust Job K8s
      ↓
  Deploy su cluster reale (single-image, multi-instance)
      ↓
  [OTEL instrumentation] → trace e metriche via auto-injection
      ↓
  [Validazione]         → confronto con simulazione lqsim (MAPE < 25%)
```

### Modalità operativa: interpretazione a runtime
Il tool opera in **single-image interpretation mode**: ogni task LQN viene deployato come
istanza dello stesso container generico, configurato interamente via variabili d'ambiente
(`LQN_TASK_CONFIG` JSON). Non viene generato codice applicativo — il grafo delle activity
viene interpretato a runtime dall'engine Flask/Gunicorn.

Questo è un punto di forza: **zero code gen = zero drift**, il modello LQN È il sistema.
Lo sviluppatore può sostituire incrementalmente i servizi dummy con codice reale, uno alla
volta, mantenendo le performance verificabili ad ogni step.

### Caratteristiche chiave:
- **Primo tool** a eseguire la semantica core activity-based delle LQN su infrastruttura reale K8s
- Supporta: sequences, AND-fork/join (parallelismo reale via C extension), OR-fork (probabilistico), reply semantics, sync calls (y), async calls (z), mean calls frazionali, entry multiple per task
- Validazione empirica: confronto lqsim vs cluster reale con MAPE < 25% su response time
- OTEL-compliant: auto-instrumentation per Python, Java, Node.js, .NET, Go
- 235+ test (unit + E2E): trace matching, utilization law, closed-loop, lqsim predictions

### Feature LQN supportate (Table 1 nel paper):

| Costrutto LQN | Supportato | Note |
|---|---|---|
| Processori (FCFS, infinite, multiplicity) | ✓ | Mappati su CPU requests/limits K8s |
| Task (multiplicity, think time) | ✓ | multiplicity → GUNICORN_WORKERS |
| Entry (phase-based e activity-based) | ✓ | Endpoint HTTP per entry |
| Activity (service time esponenziale) | ✓ | C extension busy-wait GIL-releasing |
| Activity graph (sequences) | ✓ | Grafo interpretato a runtime |
| AND-fork/join (parallelismo reale) | ✓ | ThreadPoolExecutor + C extension |
| OR-fork (probabilistico) | ✓ | Weighted random choice |
| Reply semantics | ✓ | activity[entry] |
| Sync calls (y) | ✓ | HTTP GET bloccante |
| Async calls (z) | ✓ | Fire-and-forget via ThreadPool |
| Mean calls (frazionali) | ✓ | Parte intera + probabilistica |
| Entry multiple per task | ✓ | Routing HTTP per endpoint |
| Forwarding (f) | ✗ | Future work |
| Phase 2+ execution | ✗ | Parsato ma solo Phase 1 eseguita |
| Open arrivals | ✗ | Solo closed workload (reference task) |
| Semafori/RWLock/Quorum | ✗ | Future work |

### Limitazioni note (da dichiarare nel paper):
- **Forwarding calls** (f): non implementato — raro in topologie microservizi
- **Multi-phase execution**: parser legge tutte le fasi, engine esegue solo Phase 1
- **Open arrivals**: solo closed workload via reference task con think time
- **Sincronizzazione avanzata**: semafori, RWLock, quorum — non implementati
- **Distribuzione service time**: solo esponenziale (assunzione Markoviana)
- Queste limitazioni riguardano costrutti LQN poco comuni nelle topologie microservizi target

---

## La visione: LQN come contratto eseguibile

Lo scenario di utilizzo principale che voglio comunicare nel paper:

> Il modello LQN diventa un **artefatto contrattuale eseguibile** tra committente e sviluppatore: specifica struttura, comportamento e performance attese del sistema. La novità è che questo contratto non è solo simulabile — è **deployabile su K8s**, rendendo il "sistema previsto" eseguibile sull'infrastruttura reale.

Workflow vision:
```
Committente + Sviluppatore concordano il modello LQN
           ↓
Il modello viene deployato su K8s (interpretation mode)
→ entrambe le parti vedono il comportamento reale su cluster
→ il modello LQN È il sistema (zero code gen, zero drift)
           ↓
Lo sviluppatore implementa incrementalmente
→ sostituisce i servizi dummy con codice reale uno alla volta
→ le performance rimangono verificabili ad ogni step
           ↓
Validazione continua: lqsim predictions vs metriche reali (MAPE < 25%)
```

Questo è **incremental performance-aware development** — non esiste in letteratura in questa forma.

**Nota**: il fatto che NON ci sia code gen è un vantaggio architetturale. Il modello LQN
viene interpretato direttamente, quindi non c'è mai divergenza tra modello e implementazione
finché il servizio dummy non viene sostituito con codice reale.

---

## Stato dell'arte — competitor analizzati

### μBench (IEEE TPDS 2023 — Roma Tor Vergata)
- Genera app microservizi dummy per benchmarking di piattaforme cloud/edge
- Input: `workmodel.json` con parametri di stress (CPU, memory, I/O)
- **Nessun formalismo, nessuna garanzia analitica**
- Output comparabile al mio (Python + K8s) ma direzione opposta

### HydraGen (IEEE Cloud 2023 — Ericsson Research + Umeå)
- Genera benchmark con diverse complessità computazionali e topologie
- Input: tabelle di configurazione parametrica
- Focus: inter-service communication per web-serving applications
- **Nessun formalismo**

### Palette (ACM APSys 2025 — Max Planck + Microsoft Research)
- Genera sistemi microservizi a partire da **trace di produzione**
- Usa GCM + PFA per modellare il comportamento osservato
- **Direzione opposta**: parte da sistema esistente, non da modello formale
- Venue: workshop (minore) — da citare brevemente ma non enfatizzare

### La differenza fondamentale:
Tutti i competitor: `sistema reale (o parametri empirici) → generatore → benchmark`
Il mio tool: `modello formale LQN → interpreter → sistema reale verificabile su K8s`

Nessun competitor parte da un **formalismo analitico** con garanzie di performance verificabili.

---

## Claim principale del paper (RIFORMULATO dopo code review)

> *"The first tool to deploy activity-based Layered Queueing Network models as configurable microservice systems on Kubernetes, enabling rapid performance validation and incremental model-driven development with empirically verified analytical predictions."*

### Differenze rispetto alla formulazione precedente:
- "compile" → "deploy" — il tool non genera codice, interpreta il modello a runtime
- "complete LQN" → "activity-based LQN" — supporta il subset core, non tutti i costrutti V5
- "performance guarantees" → "empirically verified analytical predictions" — onesto e verificabile (MAPE < 25%)

---

## Struttura paper proposta (4 pagine, ACM sigconf) — AGGIORNATA

- **§1 Introduction (~0.5p)** — problema: gap tra modello e implementazione in performance engineering
- **§2 Background & Positioning (~0.5p)** — LQN activity-based subset, confronto con μBench/HydraGen/Palette, Table 1 (feature supportate)
- **§3 Tool Architecture (~1p)** — pipeline: parser → K8s manifest gen → deploy → OTEL instrumentation. Single-image interpretation mode (NO "due modalità"). Diagramma architetturale
- **§4 Validation (~1p)** — evidenza dagli E2E test: lqsim predictions MAPE < 25%, utilization law, closed-loop. Grafici lqsim vs misurato
- **§5 Usage & Availability (~0.5p)** — workflow incrementale, repo GitHub, CLI tools (`lqn-compile`, `lqn-deploy`), licenza
- **References (~0.5p)**

### Note per §4 Validation:
I dati per i grafici vengono dai test E2E esistenti:
- `test_lqsim_predictions.py` → MAPE response time (lqsim vs Docker)
- `test_closed_loop_utilization.py` → U = X × S con 22 client, 60s measurement
- `test_utilization_law.py` → sanity check a basso carico
I grafici vanno prodotti manualmente dai risultati di questi test

---

## Code review completata (2026-03-21)

### Pipeline confermata:
| Modulo | File | Funzione |
|---|---|---|
| Parser LQN V5 | `src/lqn_parser.py` (446 righe) | Parsa LQN V5 subset → dataclass `LqnModel` |
| K8s Manifest Gen | `tools/lqn_compiler.py` (400 righe) | `LqnModel` → Deployment + Service YAML + `LQN_TASK_CONFIG` JSON |
| Deploy Script Gen | `tools/deploy_gen.py` (260 righe) | Genera `deploy.sh` (up/down/test) + OTEL Instrumentation CR |
| Locustfile Gen | `tools/locustfile_gen.py` (264 righe) | Genera Locust client dal reference task LQN |
| Activity Engine | `src/app.py` (718 righe) | Interprete activity graph a runtime (Flask/Gunicorn) |
| C Extension | `src/busy_wait.c` | Busy-wait GIL-releasing per AND-fork parallelismo reale |
| lqsim Runner | `tools/lqsim_runner.py` (243 righe) | Wrapper lqsim: esegue e parsa output .p |
| Trace Validator | `tests/helpers/trace_validator.py` (454 righe) | Validazione formale trace vs config |

### Gap identificate e risolte:
1. ~~"Modalità compilazione"~~ → NON ESISTE. Solo interpretation mode. **Riformulato sopra.**
2. ~~"Sintassi e semantica completa"~~ → Subset activity-based. **Table 1 aggiunta sopra.**
3. ~~"Measurement tool"~~ → OTEL pass-through, no built-in Prometheus/Jaeger query. **Riformulato.**
4. Nome tool: **GMT (Generic Microservice Tester)** — già definito nel repo.

### Moduli E2E per validazione empirica:
- `test_lqsim_predictions.py` — MAPE < 25% su response time (lqsim vs Docker)
- `test_closed_loop_utilization.py` — U = X × S con 22 client closed-loop
- `test_utilization_law.py` — sanity check a basso carico
- `test_template_topology.py` — deploy e2e su K8s reale

### Statistiche codebase:
- 235 unit test + E2E
- 4 CLI tools: `lqn-compile`, `lqn-deploy`, `lqn-locustfile`, `lqsim-run`
- Docker multi-stage build (gcc + python:3.12-slim)
- OTEL multi-linguaggio (Python, Java, Node.js, .NET, Go)

L'obiettivo finale è scrivere un tool paper di 4 pagine per ASE 2026 Tools & Datasets track che sia tecnicamente preciso, ben posizionato rispetto allo stato dell'arte, e costruito attorno alla visione della LQN come contratto eseguibile per sistemi distribuiti.