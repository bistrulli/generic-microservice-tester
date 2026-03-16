# GMT Model Refinement with lqsim

Sei l'agente di refinement del modello LQN. Il tuo compito e' iterare sul modello LQN usando il simulatore `lqsim` per allinearlo ai dati misurati dal deployment GMT su K8s.

**Input richiesto**: `$ARGUMENTS` (path al modello LQN e/o ai dati misurati)

## Contesto

Il refinement del modello e' il processo inverso della compilazione: invece di generare K8s dal LQN, si aggiusta il modello LQN perche' le sue predizioni corrispondano alle misurazioni reali dal deployment GMT.

## Prerequisiti

- `lqsim` installato e disponibile nel PATH
- `lqns` (solver analitico) opzionale ma utile per confronto
- Modello LQN sorgente (`.lqn` o `.lqnx`)
- Dati misurati dal deployment GMT (response times, throughput, utilization)

## Pipeline di refinement

### Step 1: Baseline — Esegui simulazione sul modello originale

```bash
# Simulazione con intervallo di confidenza 95%
lqsim $ARGUMENTS -C 0.95 -A 1000000 -o baseline_output.lqxo

# Anche solver analitico per confronto
lqns $ARGUMENTS -o baseline_analytical.lqxo
```

Estrai dal `.lqxo`:
- Response time per ogni entry
- Throughput per ogni entry
- Utilization per ogni task e processor
- Waiting time nelle code

### Step 2: Confronto baseline vs misurazioni

Costruisci tabella di confronto:

```
| Metrica | lqsim | lqns | K8s Misurato | Err sim% | Err ana% |
|---------|-------|------|--------------|----------|----------|
| RT entry1 | ... | ... | ... | ... | ... |
| TP entry1 | ... | ... | ... | ... | ... |
| Util task1 | ... | ... | ... | ... | ... |
```

### Step 3: Identifica parametri da raffinare

In ordine di priorita':
1. **Service time** — Il parametro piu' critico. Se RT misurato > RT predetto, il service time reale potrebbe essere maggiore (overhead non modellato)
2. **Multiplicity** — Se utilization misurata >> predetta con stesso throughput, la multiplicity effettiva potrebbe essere minore
3. **Call frequency** — Se il throughput downstream non corrisponde, le probabilita' di chiamata potrebbero essere errate
4. **Think time** — Per modelli closed, il think time del reference task influenza tutto

### Step 4: Aggiusta il modello

Per ogni parametro da raffinare:

1. **Modifica il file `.lqn`**
   - Aggiorna il service time: `s(<entry>) = <nuovo-valore>`
   - Aggiorna multiplicity: `m <task> = <nuovo-valore>`
   - Aggiorna call mean: `y(<caller>,<callee>) = <nuovo-valore>`

2. **Riesegui simulazione**
   ```bash
   lqsim <modello-modificato>.lqn -C 0.95 -A 1000000 -o refined_iter_N.lqxo
   ```

3. **Confronta con iterazione precedente**
   - L'errore e' diminuito?
   - Quali metriche sono migliorate/peggiorate?

### Step 5: Validazione crociata

Dopo il refinement:

1. **Verifica coerenza interna** del modello LQN
   ```bash
   lqns <modello-raffinato>.lqn  # deve convergere senza errori
   ```

2. **Verifica che i parametri raffinati siano fisicamente sensati**
   - Service time > 0
   - Multiplicity >= 1 e intera
   - Probabilita' in [0, 1]
   - Utilization < 1 (altrimenti il sistema e' instabile)

3. **Deploy GMT con parametri raffinati**
   - Aggiorna manifesti K8s con i nuovi valori
   - Re-deploy e ri-misura
   - Confronta nuove misurazioni vs nuove predizioni

### Step 6: Iterazione

Ripeti Step 2-5 fino a convergenza:
- **Criterio**: errore relativo < 10% su tutte le metriche principali
- **Max iterazioni**: 10
- **Early stop**: se l'errore non migliora per 2 iterazioni consecutive

## Tecniche avanzate di refinement

### Sensitivity analysis
```bash
# Varia un parametro alla volta e osserva l'effetto
for st in 0.05 0.08 0.10 0.12 0.15; do
  sed "s/s(entry1) = .*/s(entry1) = $st/" model.lqn > model_st_$st.lqn
  lqsim model_st_$st.lqn -C 0.95 -A 500000
done
```

### Bottleneck identification
- Se un task ha utilization > 0.8, e' probabile bottleneck
- Raffinare prima i parametri del bottleneck ha impatto maggiore
- Usare `lqns -p` per ottenere il bottleneck strength

### Multi-objective fitting
Se si hanno misurazioni a diversi livelli di carico:
1. Esegui simulazione per ogni livello di carico
2. Calcola errore medio su tutti i livelli
3. Ottimizza per minimizzare l'errore medio (non solo un punto)

## Output

```markdown
## Model Refinement Report

### Modello: <nome>
### Iterazioni completate: N
### Stato: [CONVERGED/NOT_CONVERGED/DIVERGING]

### Parametri modificati
| Parametro | Originale | Raffinato | Delta | Motivazione |
|-----------|-----------|-----------|-------|-------------|
| s(entry1) | 0.10 | 0.12 | +20% | overhead rete non modellato |
| m(task2) | 4 | 3 | -25% | 1 worker dedicato a health check |

### Confronto finale
| Metrica | lqsim (raffinato) | K8s Misurato | Errore % |
|---------|-------------------|--------------|----------|
| RT | ... | ... | <10%? |

### File output
- Modello raffinato: `<path>.lqn`
- Output simulazione: `<path>.lqxo`
- Dati confronto: `<path>_comparison.csv`
```
