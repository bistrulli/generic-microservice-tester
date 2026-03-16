# Cross-Review Agent — GMT (Claude x Gemini)

Refinement incrociato di piani e documenti tecnici. Claude genera, Gemini critica con accesso al codebase, Claude integra. Loop fino a convergenza reale.

## Input

$ARGUMENTS

L'argomento e' il path al file da revieware (es. `plan/my-feature.md`). Se non specificato, cerca il file `.md` piu' recente in `plan/`.

---

## Fase 0: Setup

### 0.1 Verifica Gemini CLI

```bash
gemini --version
```

Se non disponibile: **STOP** — "Installa Gemini CLI: `npm install -g @google/gemini-cli`"

### 0.2 Carica il documento

Leggi il file con Read. Se non esiste, **STOP** con errore.

Identifica il tipo di documento:
- **Piano LQN/topology** (`# Piano:` + tocca `src/app.py` con logica LQN o topologia): usa il prompt LQN-aware
- **Piano K8s/Docker** (tocca `docker/`, `kubernetes/`): usa il prompt K8s-aware
- **Piano generico**: usa il prompt base (comunque con contesto progetto)

### 0.3 Identifica i file coinvolti dal piano

Parsa il piano ed estrai tutti i file elencati nei campi `File:` di ogni task. Questi verranno inclusi nel prompt come istruzione a Gemini di leggerli.

---

## Fase 1: Loop di Refinement (fino a convergenza)

**Nessun cap fisso sui round.** Safety limit: 5 round (solo per evitare loop infiniti — non e' un target).

Per ogni round:

### 1.1 Costruisci il prompt per Gemini

Il prompt ha 4 sezioni: **contesto progetto**, **domain knowledge**, **file da leggere**, **piano + criteri di review**.

**IMPORTANTE**: Scrivi SEMPRE il prompt in un file temporaneo per evitare problemi di escaping:

```bash
cat > /tmp/gmt_cross_review_prompt.txt << 'PROMPT_EOF'
<contenuto del prompt>
PROMPT_EOF
```

#### Sezione 1: Contesto progetto (SEMPRE inclusa)

```
## CONTESTO PROGETTO

GMT (Generic Microservice Tester) e' un microservizio Flask/Gunicorn progettato per simulare topologie di microservizi su Kubernetes. La visione e' che GMT sia il compilation target per modelli LQN (Layered Queueing Network).

Ogni istanza GMT simula un nodo nella topologia: riceve richieste HTTP, esegue busy-wait calibrato (per simulare CPU load), chiama altri nodi GMT downstream, e risponde. La topologia e' configurabile via variabili d'ambiente.

Struttura:
- src/ — Flask app (app.py) + requirements (requirements.txt)
- docker/ — Dockerfile + entrypoint.sh per il container
- kubernetes/base/ — Manifest K8s base (Deployment, Service, ConfigMap)
- kubernetes/examples/ — Configurazioni di topologia d'esempio

Pipeline deployment: build image → push → apply K8s manifests → traffic generator → observe metrics

Il microservizio espone endpoint configurabili che simulano:
- CPU-bound work (busy-wait con psutil per precisione)
- Chiamate downstream a catena (HTTP calls ad altri nodi GMT)
- Latenza configurabile per endpoint
```

#### Sezione 2: Domain knowledge (varia per tipo di piano)

**Per piani LQN/topology:**

```
## DOMAIN KNOWLEDGE — LQN → K8s Mapping

GMT e' il compilation target per modelli LQN. Il mapping e':
- LQN Processor → K8s Node (o resource limits per CPU)
- LQN Task → K8s Deployment (un'istanza GMT per task)
- LQN Task multiplicity → K8s replicas
- LQN Entry → Flask endpoint (route)
- LQN Activity con host_demand → busy-wait calibrato (durata = service time)
- LQN Call (sync/y) → HTTP request a un altro nodo GMT (request-response)
- LQN Call (async/z) → HTTP request fire-and-forget (non implementato ancora)
- LQN Open workload → traffic generator esterno (es. locust, k6, vegeta)

Vincoli importanti:
- Il busy-wait deve essere CPU-bound reale (non sleep) per simulare service time
- psutil e' usato per misurare il tempo CPU effettivo (non wall-clock)
- Le chiamate downstream devono rispettare il DAG della topologia (no cicli)
- Ogni nodo GMT deve avere un nome univoco (corrisponde al task name LQN)
- Il service time (host_demand) si configura via env var per endpoint
```

**Per piani K8s/Docker:**

```
## DOMAIN KNOWLEDGE — K8s/Docker

- Deployment su Kubernetes (k3s via Rancher Desktop o cluster reale)
- Servizi comunicano via K8s DNS: <service>.<namespace>:<port>
- Ogni pod: resource requests/limits, liveness/readiness probes
- ConfigMap per la configurazione della topologia (downstream services, service times)
- Il Dockerfile usa Python slim, installa requirements.txt, avvia con Gunicorn
- entrypoint.sh gestisce la configurazione di avvio Gunicorn (workers, bind, etc.)
- I manifest K8s in kubernetes/base/ sono parametrizzabili per creare topologie diverse
- kubernetes/examples/ contiene configurazioni pre-fatte di topologie comuni
```

#### Sezione 3: File da leggere (SEMPRE inclusa)

```
## FILE DA LEGGERE

PRIMA di dare il tuo feedback, LEGGI i seguenti file dal codebase per capire lo stato attuale del codice.
Non dare feedback basato solo sul piano — verifica che le assunzioni del piano corrispondano al codice reale.

File coinvolti dal piano:
{lista_file_dal_piano — uno per riga}

File di contesto aggiuntivi (leggi almeno i primi 2):
- README.md (descrizione progetto)
- src/app.py (Flask app — il file principale)
- docker/Dockerfile (come viene buildato il container)
- docker/entrypoint.sh (come viene avviato Gunicorn)
- src/requirements.txt (dipendenze Python)
```

Se esiste un output problematico o un manifest da correggere, aggiungi:

```
File problematico (il motivo per cui serve questo piano):
- {path_output}
Leggilo per capire cosa c'e' di sbagliato nella configurazione attuale.
```

#### Sezione 4: Piano + Criteri di review specifici

**Per piani LQN/topology:**

```
## REVIEW CRITERIA

Analizza il piano e fornisci feedback strutturato. Per ogni punto, indica il NUMERO DEL TASK e il FILE specifico.

### 1. SCORE (1-10)
9-10: Pronto per implementazione diretta
7-8: Buono ma con miglioramenti importanti
5-6: Problemi significativi da risolvere
1-4: Ripensare l'approccio

### 2. CRITICAL ISSUES (bloccanti — devono essere risolti)

Verifica specifica per piani LQN/topology:
- Il mapping LQN → K8s proposto e' corretto? Ogni elemento LQN ha un corrispondente K8s?
- Il busy-wait simula correttamente il service time? Usa psutil o metodi meno precisi?
- Le chiamate downstream rispettano la topologia (DAG, no cicli)?
- La configurazione via env var e' sufficiente per esprimere la topologia?
- I test proposti verificano COMPORTAMENTO o solo che non crasha?
- L'ordine dei task e' eseguibile? Task N+1 puo' funzionare se Task N non e' ancora fatto?
- Il Docker build funziona con le modifiche proposte?
- I manifest K8s sono validi e coerenti?

Verifica generica:
- Task ambigui dove non e' chiaro COSA fare esattamente
- Rischi di regressione: il piano rompe funzionalita' esistenti?
- Backward compatibility: le env var cambiano in modo incompatibile?

### 3. IMPROVEMENTS (importanti ma non bloccanti)
- Task troppo grandi che andrebbero spezzati
- Edge case non coperti
- Test mancanti per scenari specifici
- Alternative architetturali migliori (con motivazione)

### 4. QUESTIONS
- Domande su scelte architetturali ambigue
- Chiarimenti su come un task dovrebbe funzionare
- Dubbi su assunzioni implicite

Per ogni punto sii SPECIFICO: Task #N, file X:riga Y, "il piano assume Z ma il codice fa W".

---

PIANO DA REVIEWARE:

{contenuto_del_piano}
```

**Per piani K8s/Docker:**

```
## REVIEW CRITERIA

Analizza il piano e fornisci feedback strutturato.

### 1. SCORE (1-10)
### 2. CRITICAL ISSUES (bloccanti)

Verifica specifica per piani K8s/Docker:
- I manifest K8s sono corretti? (resource limits, probes, service ports)
- Le variabili d'ambiente sono coerenti tra i servizi?
- Il networking funziona? (DNS names, ports, namespaces)
- Il Dockerfile segue le best practice? (layer caching, security, size)
- L'entrypoint.sh gestisce errori? (set -e, health check, graceful shutdown)
- I ConfigMap sono strutturati correttamente per esprimere topologie?

### 3. IMPROVEMENTS
### 4. QUESTIONS

---

PIANO DA REVIEWARE:

{contenuto_del_piano}
```

**Per piani generici:**

```
## REVIEW CRITERIA

Analizza il piano e fornisci feedback strutturato.

### 1. SCORE (1-10)
### 2. CRITICAL ISSUES — problemi bloccanti
### 3. IMPROVEMENTS — miglioramenti non bloccanti
### 4. QUESTIONS — dubbi e chiarimenti

Leggi i file coinvolti e verifica che le assunzioni del piano corrispondano al codice reale.

---

PIANO DA REVIEWARE:

{contenuto_del_piano}
```

### 1.2 Chiama Gemini

Scrivi il prompt completo nel file temporaneo e lancia Gemini dalla root del progetto:

```bash
gemini -p "$(cat /tmp/gmt_cross_review_prompt.txt)" 2>&1
```

Timeout: 180 secondi. Se non risponde, stampa warning e riprova una volta.

Cattura l'output completo di Gemini.

### 1.3 Analizza la risposta

Dall'output di Gemini, estrai:
- **Score**: il punteggio numerico (1-10)
- **Critical issues**: lista dei problemi bloccanti — con task number e file
- **Improvements**: lista dei miglioramenti suggeriti
- **Questions**: domande da considerare

**Valuta la qualita' del feedback di Gemini:**
- Se il feedback e' generico/superficiale (es. "Task 3 potrebbe avere problemi" senza specificare quali), NON contarlo come un round valido. Riprova con un prompt piu' specifico che chiede di leggere i file coinvolti.
- Se Gemini non ha letto i file (lo si capisce perche' non cita righe di codice o dettagli implementativi), segnalalo nel report del round.

### 1.4 Decisione

- **Score >= 9** e **0 critical issues**: il piano e' maturo. **CONVERGED** — procedi con output.
- **Score >= 8** e **0 critical issues** e **round >= 2**: accettabile dopo almeno 2 round. **CONVERGED**.
- **Altrimenti**: integra il feedback e ri-itera.
- **Safety limit**: se round == 5, **STOP** con lo stato corrente (non e' un target — e' una rete di sicurezza).

### 1.5 Integra feedback

Per ogni critical issue:
1. Verifica leggendo il codice che il feedback sia corretto (Gemini puo' sbagliare)
2. Se confermato: modifica il piano nel file originale
3. Aggiungi un commento `<!-- Round N: risolto issue X — dettaglio -->` per tracciabilita'

Per ogni improvement valido:
1. Valuta se il miglioramento e' coerente con lo scope del piano
2. Se SI e aggiunge valore reale: integra
3. Se NO o e' scope creep: ignora con motivazione nel report

Salva il piano aggiornato.

### 1.6 Prepara il prompt per il round successivo (Round 2+)

Nei round successivi, il prompt include una sezione aggiuntiva PRIMA del piano:

```
## FEEDBACK ROUND PRECEDENTE

Nel round precedente hai dato questo feedback:
{feedback_gemini_round_precedente}

Ho applicato le seguenti modifiche al piano per risolvere i tuoi concern:
{lista_modifiche_applicate}

Per i seguenti punti ho deciso di NON applicare modifiche, con questa motivazione:
{lista_punti_ignorati_con_motivazione}

Adesso riesamina il piano aggiornato. Concentrati su:
1. Le modifiche risolvono EFFETTIVAMENTE i tuoi concern precedenti?
2. Le modifiche hanno introdotto NUOVI problemi?
3. Ci sono aspetti che non avevi notato nel round precedente?

NON ripetere feedback gia' risolti. Concentrati su cio' che e' nuovo o non risolto.
```

### 1.7 Report del round

Stampa:

```
Cross-Review Round N:
  Gemini Score: X/10
  Feedback quality: HIGH (cita codice) | MEDIUM (specifico ma senza codice) | LOW (generico)
  Critical Issues: N (risolti: M, rigettati: K con motivazione)
  Improvements: N (integrati: M, ignorati: K)
  Questions: N
  Status: CONVERGED | ITERATING
```

---

## Fase 2: Output finale

Stampa il report completo:

```
===================================================
  CROSS-REVIEW REPORT — Claude x Gemini
===================================================

  Documento: <path>
  Round totali: <N>
  Score: <round1> -> <round2> -> ... -> <finale>
  Feedback quality: <HIGH/MEDIUM/LOW per round>

  Modifiche applicate:
    Round 1: <lista modifiche>
    Round 2: <lista modifiche>
    ...

  Feedback rigettati (con motivazione):
    Round 1: <lista con motivazione>
    ...

  Issues risolti:  N
  Improvements:    N integrati / M suggeriti / K rigettati
  Questions:       <lista per l'utente>

  Verdict: APPROVED (score >= 9, 0 critical) |
           ACCEPTED (score >= 8, 0 critical, round >= 2) |
           NEEDS_REVIEW (score < 8 dopo safety limit)

===================================================
```

Se ci sono QUESTIONS non risolvibili automaticamente, elencale per l'utente.

---

## Regole

1. **Nessun cap artificiale** — itera fino a convergenza reale (safety limit 5 per loop infiniti)
2. **No scope creep** — le modifiche di Gemini devono essere coerenti col piano originale
3. **Tracciabilita'** — ogni modifica ha un commento HTML con round, issue, e dettaglio
4. **Claude decide** — Gemini suggerisce, Claude valuta LEGGENDO IL CODICE e integra. Non integrare feedback incoerenti o errati
5. **Gemini deve leggere il codice** — se il feedback e' generico/superficiale, non conta come round valido
6. **Timeout** — se gemini non risponde entro 180s, riprova una volta poi salta il round con warning
7. **Qualita' > velocita'** — un round di feedback approfondito vale piu' di 3 round superficiali
8. **Trasparenza sui rigetti** — se Claude rigetta un feedback di Gemini, deve motivare il perche' nel report
