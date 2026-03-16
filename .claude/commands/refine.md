# GMT Refinement Loop — LQN-to-K8s Calibration

Sei l'agente di refinement per GMT. Il tuo compito e' iterare sul ciclo compare-diagnose-fix-verify per allineare il modello LQN alla configurazione K8s effettiva.

**Input richiesto**: `$ARGUMENTS` (path al modello LQN o descrizione del disallineamento)

## Contesto

GMT e' il target di compilazione LQN: un modello LQN viene "compilato" in una topologia K8s di istanze GMT. Il refinement verifica che la configurazione K8s produca il comportamento previsto dal modello LQN.

### Mapping LQN → GMT/K8s

| LQN Concept | GMT/K8s Equivalent |
|---|---|
| Task | K8s Deployment (istanza GMT) |
| Task multiplicity | `spec.replicas` + `GUNICORN_WORKERS` |
| Entry | Endpoint Flask `/` |
| Activity service time | `SERVICE_TIME_SECONDS` (media distribuzione esponenziale) |
| Sync call (y) | `SYNC:service-name:probability` in OUTBOUND_CALLS |
| Async call (z) | `ASYNC:service-name:probability` in OUTBOUND_CALLS |
| Processor | K8s Node / resource limits |
| Call probability | Terzo campo in OUTBOUND_CALLS |

## Ciclo di refinement

### Fase 1: COMPARE — Confronta modello vs deployment

1. Leggi il modello LQN sorgente (`.lqn` o `.lqnx`)
2. Leggi i manifesti K8s generati (`kubernetes/` o path specificato)
3. Per ogni task LQN, verifica:
   - Service time nel modello == `SERVICE_TIME_SECONDS` nel deployment
   - Multiplicity nel modello == `replicas * GUNICORN_WORKERS`
   - Chiamate nel modello == `OUTBOUND_CALLS` nel deployment
   - Probabilita' chiamata nel modello == probabilita' in OUTBOUND_CALLS
4. Produci tabella di confronto:

```
| Task LQN | Service Time (LQN) | SERVICE_TIME_SECONDS (K8s) | Match? |
|-----------|--------------------|-----------------------------|--------|
| frontend  | 0.05               | 0.05                        | OK     |
| backend   | 0.2                | 0.15                        | MISMATCH |
```

### Fase 2: DIAGNOSE — Identifica causa dei disallineamenti

Per ogni MISMATCH trovato:
- **Service time errato**: Valore copiato male? Unita' diverse (ms vs s)?
- **Multiplicity errata**: replicas e workers non corrispondono alla multiplicity LQN?
- **Chiamate mancanti/extra**: OUTBOUND_CALLS non riflette il grafo LQN?
- **Probabilita' errate**: Pesi normalizzati diversamente?
- **Topologia errata**: Servizi K8s non collegati correttamente?

### Fase 3: FIX — Correggi la configurazione

1. Aggiorna i manifesti K8s per allinearli al modello LQN
2. Oppure, se il modello LQN e' quello errato, segnala le correzioni necessarie
3. Per ogni fix, documenta:
   - File modificato
   - Valore vecchio → valore nuovo
   - Motivazione

### Fase 4: VERIFY — Verifica le correzioni

```bash
# 1. Valida manifesti K8s
kubectl apply --dry-run=client -f <manifest-path>

# 2. Se possibile, deploy su cluster di test
kubectl apply -f <manifest-path> -n test

# 3. Attendi che i pod siano ready
kubectl wait --for=condition=ready pod -l app=<service-name> -n test --timeout=120s

# 4. Esegui load test (esempio con hey o wrk)
hey -n 1000 -c 10 http://<entry-service-url>/

# 5. Raccogli metriche
kubectl top pods -n test
# Oppure query Prometheus per response time, throughput

# 6. Confronta metriche misurate vs predizioni LQN
# - Response time misurato vs predetto
# - Throughput misurato vs predetto
# - Utilization misurata vs predetta
```

## Iterazione

Se dopo la verifica ci sono ancora disallineamenti significativi (>10% errore relativo):

1. Torna a Fase 1 con i nuovi dati
2. Aggiorna la diagnosi considerando i risultati del load test
3. Possibili cause di secondo ordine:
   - Overhead di rete non modellato nel LQN
   - Contention su risorse condivise (CPU, memoria)
   - Gunicorn worker scheduling non ideale
   - Connection pool saturation
   - K8s scheduler effects (co-location, node affinity)

## Output

Report finale:

```markdown
## Refinement Report

### Iterazione: N
### Stato: [ALIGNED/IN_PROGRESS/BLOCKED]

### Tabella di confronto finale
| Metrica | LQN Prediction | K8s Measured | Errore % |
|---------|----------------|--------------|----------|
| Response time (frontend) | 350ms | 380ms | 8.6% |
| Throughput | 100 req/s | 95 req/s | 5.0% |

### Modifiche applicate
1. [descrizione fix]

### Prossimi passi
- [se non aligned, cosa fare]
```
