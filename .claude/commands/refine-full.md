# GMT E2E Refinement Pipeline — LQN-to-K8s Full Cycle

Sei l'agente di refinement end-to-end per GMT. Esegui l'intero ciclo di compilazione LQN, deployment, calibrazione e validazione.

**Input richiesto**: `$ARGUMENTS` (path al modello LQN sorgente)

## Overview

Il pipeline completo trasforma un modello LQN in un deployment K8s funzionante e calibrato. Ogni fase ha criteri di uscita chiari.

---

## Phase 1: LQN → K8s Compilation (Generazione manifesti)

### Input
- Modello LQN (`.lqn` o `.lqnx`)

### Procedura

1. **Parsing del modello LQN**
   - Estrai tutti i task, entry, activity, call
   - Identifica la topologia (chain, fan-out, DAG)
   - Nota: i processor definiscono le risorse computazionali

2. **Generazione manifesti K8s**
   Per ogni task LQN, genera un Deployment + Service GMT:

   ```yaml
   apiVersion: apps/v1
   kind: Deployment
   metadata:
     name: <task-name>-deployment
     labels:
       app.kubernetes.io/name: <task-name>
       app.kubernetes.io/part-of: gmt-topology
       lqn.gmt/task: <task-name>
   spec:
     replicas: <ceil(multiplicity / gunicorn_workers)>
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
           image: <gmt-image>
           ports:
           - containerPort: 8080
           env:
           - name: SERVICE_NAME
             value: "<task-name>"
           - name: SERVICE_TIME_SECONDS
             value: "<activity-service-time>"
           - name: OUTBOUND_CALLS
             value: "<SYNC|ASYNC:target-svc:probability,...>"
           - name: GUNICORN_WORKERS
             value: "<workers>"
           - name: GUNICORN_THREADS
             value: "1"
           resources:
             requests:
               cpu: "<based-on-processor>"
               memory: "128Mi"
             limits:
               cpu: "<based-on-processor>"
               memory: "256Mi"
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

3. **Mapping rules**
   - `SERVICE_TIME_SECONDS` = service time dell'activity (in secondi)
   - `OUTBOUND_CALLS` = concatenazione di tutte le call dall'entry:
     - sync call → `SYNC:<target-task>-svc:<mean-calls>`
     - async call → `ASYNC:<target-task>-svc:<mean-calls>`
   - `GUNICORN_WORKERS` = multiplicity del task (o suddiviso con replicas)
   - `GUNICORN_THREADS` = 1 (sync worker mode per accurate CPU timing)

4. **Validazione statica**
   ```bash
   kubectl apply --dry-run=client -f <generated-manifests>/
   ```

### Criterio di uscita Phase 1
- Tutti i manifesti sono YAML validi
- Ogni task LQN ha un corrispondente Deployment + Service
- Le env vars sono coerenti con il modello LQN

---

## Phase 2: Deploy and Calibrate

### Procedura

1. **Deploy sul cluster**
   ```bash
   kubectl create namespace gmt-test --dry-run=client -o yaml | kubectl apply -f -
   kubectl apply -f <generated-manifests>/ -n gmt-test
   kubectl wait --for=condition=ready pod -l app.kubernetes.io/part-of=gmt-topology -n gmt-test --timeout=300s
   ```

2. **Smoke test**
   ```bash
   # Trova il servizio entry point
   ENTRY_SVC=$(kubectl get svc -n gmt-test -o name | head -1)
   kubectl port-forward -n gmt-test $ENTRY_SVC 8080:80 &

   # Singola richiesta di test
   curl -s http://localhost:8080/ | python -m json.tool
   ```

3. **Load test di calibrazione**
   ```bash
   # Warm up
   hey -n 100 -c 5 http://localhost:8080/

   # Test principale
   hey -n 5000 -c 20 -o csv http://localhost:8080/ > results/load_test.csv
   ```

4. **Raccolta metriche**
   ```bash
   # Resource usage
   kubectl top pods -n gmt-test

   # Prometheus queries (se disponibile)
   # - request_duration_seconds_histogram
   # - flask_http_request_total
   # - container_cpu_usage_seconds_total
   ```

### Criterio di uscita Phase 2
- Tutti i pod sono Running e Ready
- Il load test completa senza errori HTTP 5xx
- Metriche raccolte per almeno 5 minuti di carico stabile

---

## Phase 3: Compare Predictions vs Measurements

### Procedura

1. **Esegui solver LQN**
   ```bash
   # Analytical solver
   lqns <model>.lqn

   # Oppure simulazione
   lqsim <model>.lqn -C 0.95 -A 1000000
   ```

2. **Estrai predizioni**
   Dal file `.lqxo` output del solver:
   - Response time per entry
   - Throughput per entry
   - Utilization per task/processor
   - Service time effettivo

3. **Confronta con misurazioni K8s**

   | Metrica | LQN Prediction | K8s Measured | Errore % | Accettabile? |
   |---------|----------------|--------------|----------|--------------|
   | Response time (entry) | X ms | Y ms | Z% | <10%? |
   | Throughput | X req/s | Y req/s | Z% | <10%? |
   | CPU utilization | X% | Y% | Z% | <15%? |

### Criterio di uscita Phase 3
- Report di confronto completo per tutte le metriche
- Identificazione dei disallineamenti >10%

---

## Phase 4: Adjust and Iterate

### Se errore > 10%

1. **Diagnosi delle cause**
   - Overhead di rete (non modellato in LQN)
   - Contention Gunicorn workers
   - K8s scheduling latency
   - Connection pool effects
   - Garbage collection pauses

2. **Strategie di aggiustamento**

   a. **Calibra service time**: Aggiusta `SERVICE_TIME_SECONDS` per compensare overhead non modellati
   ```
   SERVICE_TIME_SECONDS_calibrato = SERVICE_TIME_SECONDS_lqn - overhead_misurato
   ```

   b. **Calibra multiplicity**: Aggiusta `GUNICORN_WORKERS` se la concorrenza effettiva differisce

   c. **Aggiungi overhead al modello LQN**: Se l'overhead e' sistematico, modificare il modello per includerlo

   d. **Rivedi risorse K8s**: Se la CPU e' throttled, aumenta i limits

3. **Re-deploy e ri-misura**
   - Torna a Phase 2 con i parametri aggiustati
   - Massimo 5 iterazioni

### Criterio di convergenza
- Errore relativo < 10% su response time e throughput
- Errore relativo < 15% su CPU utilization
- Risultati stabili su almeno 2 iterazioni consecutive

---

## Output finale

```markdown
## GMT E2E Refinement Report

### Modello: <nome-modello>
### Iterazioni: N
### Stato: [CONVERGED/NOT_CONVERGED]

### Parametri finali calibrati
| Task | SERVICE_TIME | WORKERS | REPLICAS | OUTBOUND_CALLS |
|------|-------------|---------|----------|----------------|
| ...  | ...         | ...     | ...      | ...            |

### Confronto finale
| Metrica | LQN | K8s | Errore |
|---------|-----|-----|--------|
| ...     | ... | ... | ...    |

### Manifest finali
Path: <path-to-calibrated-manifests>

### Note sulla calibrazione
- [osservazioni, compensazioni applicate, limitazioni]
```
