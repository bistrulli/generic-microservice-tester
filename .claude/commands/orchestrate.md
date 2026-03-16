# Orchestrate Agent — GMT

Pipeline autonomo end-to-end. Legge un piano strutturato da disco, crea un feature branch, implementa ogni task con verifica e micro-commit, e produce un report finale.

## Input

$ARGUMENTS

L'argomento e' il path al file piano (es. `plan/add-busy-endpoint.md`). Se non specificato, cerca il file `.md` piu' recente in `plan/`.

## Modalita'

- **Normale:** `/orchestrate plan/<file>.md` — esegue dall'inizio
- **Continue:** `/orchestrate --continue plan/<file>.md` — riprende dal primo task non ancora committato

---

## Fase 0: Setup

### 0.0 Cross-Review obbligatorio (SEMPRE)

Il cross-review Claude x Gemini e' SEMPRE obbligatorio prima di qualsiasi implementazione.

Se il piano contiene il marker `<!-- cross-reviewed -->` nell'header: il cross-review e' gia' stato eseguito in questa sessione — salta questo step.

Altrimenti:

1. Esegui `/cross-review <path_del_piano>` automaticamente
2. Se Gemini non e' disponibile: **STOP** — "Cross-review richiesto. Installa Gemini CLI: `npm install -g @google/gemini-cli`". Non procedere senza cross-review.
3. Mostra il CROSS-REVIEW REPORT all'utente
4. Chiedi conferma: "Procedere con l'implementazione? (s/n)"
5. Se NO: **STOP**
6. Se SI: aggiungi `<!-- cross-reviewed -->` all'header del piano e prosegui

### 0.1b LQN Challenge (se applicabile)

Se il piano tocca file in `src/app.py` relativi alla logica di mapping LQN o generazione modello:

1. Verifica che il piano sia coerente con la visione LQN del progetto (GMT come compilation target per modelli LQN)
2. Se ci sono incoerenze con la semantica LQN (call types, entry naming, workload model): segnala e chiedi conferma
3. Se il piano NON tocca componenti LQN: stampa `LQN Challenge: N/A` e prosegui

### 0.1c K8s/Docker Challenge (se applicabile)

Se il piano tocca file in: `docker/`, `kubernetes/`, o modifica configurazione di deployment:

1. Verifica che i manifest K8s siano corretti (resource limits, probes, service ports)
2. Verifica che il Dockerfile segua le best practice (layer caching, multi-stage se necessario)
3. Se il piano NON tocca componenti K8s/Docker: stampa `K8s/Docker Challenge: N/A` e prosegui

### 0.0b Verify-Plan (SEMPRE, dopo challenge)

Verifica che le assunzioni del piano corrispondano allo stato attuale del codebase. Questo step previene implementazioni basate su line numbers, signature, o strutture di codice outdated.

1. Leggi tutti i file elencati nel piano e verifica che le assunzioni (funzioni esistenti, signature, strutture) siano corrette
2. Se trovi assunzioni sbagliate: **STOP** — "Verify-Plan BLOCKED. Il piano ha assunzioni sbagliate — aggiornalo prima di procedere." Mostra i problemi trovati.
3. Se trovi warning minori: mostra all'utente e chiedi conferma
4. Se tutto e' corretto: procedi

### 0.1 Leggi il piano

```
Read(plan/<file>.md)
```

Parsa il piano markdown. Estrai:
- **Branch name** dal nome del file piano (es. `plan/add-busy-endpoint.md` -> `feat/add-busy-endpoint`)
- **Lista task** dalle sezioni `## Task N: ...`
- Per ogni task: modulo, file, cosa, dipendenze, comando di verifica

Se il file non esiste o il formato e' invalido, **STOP** con messaggio di errore chiaro.

### 0.2 Verifica ambiente

```bash
python3 --version
pip show flask gunicorn 2>/dev/null | head -6
ruff --version 2>/dev/null || echo "ruff non disponibile"
pytest --version 2>/dev/null || echo "pytest non disponibile"
docker --version 2>/dev/null || echo "docker non disponibile"
```

Se Python non e' disponibile: **STOP** — "Python3 richiesto."
Se ruff non e' disponibile: warning, procedi senza lint.

### 0.3 Baseline snapshot

Cattura lo stato dei test su `main` PRIMA di creare il branch (questa e' la baseline di riferimento):

```bash
pytest tests/ -q 2>&1 | tail -3 || echo "No tests directory — baseline: 0 tests"
```

Salva il risultato come **BASELINE**. Se main ha test che falliscono:
- Documentali esplicitamente nel report iniziale
- Elenca i test falliti con il loro nome
- NON ignorarli e NON procedere senza averli documentati
- Questi sono gli unici test per cui "pre-existing" e' una giustificazione valida, ma solo con questo output come prova

### 0.4 Docker build baseline

Verifica che il Docker build funzioni prima delle modifiche:

```bash
docker build -t gmt:baseline-check -f docker/Dockerfile . 2>&1 | tail -5
```

### 0.5 Setup git

```bash
# Assicurati di essere su un working tree pulito
git status --porcelain
```

- Se ci sono modifiche non committate: **STOP** — "Working tree non pulito. Committa o stasha prima di procedere."
- Se flag `--continue`: salta la creazione branch, verifica di essere gia' sul branch corretto.

```bash
# Crea e switcha al feature branch (solo se non --continue)
git checkout -b feat/<feature-name>
```

### 0.6 Draft PR anticipata (solo se non --continue)

Pusha il branch e crea una draft PR subito, cosi' la CI si attiva ad ogni push successivo:

```bash
git commit --allow-empty -m "feat: start <titolo dal piano>

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
git push -u origin feat/<feature-name>
gh pr create --draft --title "feat: <titolo dal piano>" --body "$(cat <<'PREOF'
## In progress

Piano: `plan/<file>.md`

Auto-created by `/orchestrate` — will be updated on completion.
PREOF
)"
```

Stampa:
```
Draft PR creata — la CI girara' ad ogni push durante l'esecuzione.
```

### 0.7 Determina progresso (se --continue)

Leggi i commit message del branch per capire quali task sono gia' completati:

```bash
git log --oneline main..HEAD
```

I commit seguono il pattern `feat(<modulo>): <titolo> (#N/M)`. Marca come completati i task il cui numero appare nei commit.

---

## Fase 1: Esecuzione task-by-task

Per ogni task **non ancora completato**, in ordine numerico:

### 1.1 Verifica dipendenze

Se il task ha `Dipende da: Task N` e Task N non e' completato:
- Se Task N e' stato **skippato** — **STOP** con messaggio: "Task #X dipende da Task #N che e' fallito."
- Se Task N non e' ancora stato raggiunto — **errore nel piano** (ordine sbagliato)

### 1.2 Implementa

```
Stampa: "Task #N/M: <titolo>"
```

1. **Leggi** tutti i file elencati nel task PRIMA di modificarli
2. **Implementa** il cambiamento minimale — solo quello che il task richiede
3. Segui le convenzioni del codebase esistente
4. Se il task richiede un nuovo file, usa `Write`; altrimenti `Edit`

### 1.3 Lint

```bash
ruff check <file_modificati> 2>&1 | tail -20
```

Se il lint fallisce, fixa automaticamente:
```bash
ruff check --fix <file_modificati>
```

### 1.4 Test specifico

Esegui il comando di verifica specificato nel task:

```bash
<comando dal campo Verifica>
```

Di default: `pytest tests/ -q` (se la directory tests/ esiste)

### 1.4c BS Detection

Prima di committare, analizza le modifiche del task corrente per scovare pattern tipici di LLM.

1. Sulle righe aggiunte, cerca:
   - **CAT-1 (Scaffolding vuoto)**: funzioni con solo `pass`, `raise NotImplementedError()`, `# TODO`
   - **CAT-2 (Fallback silenziosi)**: `except: pass`, `except Exception: return None`
   - **CAT-6 (Test finti)**: test senza assert, `assert True`, `assert result is not None` come unica verifica
   - **CAT-7 (Workaround fragili)**: `time.sleep()` come sincronizzazione, substring check su repr
   - **CAT-8 (Blame Deflection)**: testo con "pre-existing", "known issue", "not related" senza output di prova
   - **CAT-9 (Responsibility Avoidance)**: "out of scope", "would require refactoring", CI fallisce → WARNING
   - **CAT-10 (Silent Degradation)**: assert indebolite, `pytest.mark.skip` aggiunti, CI=WARNING ignorata

2. **Analisi semantica**: Confronta con la descrizione del task:
   - **CAT-3 (Over-engineering)**: file nuovi con <10 righe di logica, helper monouso
   - **CAT-5 (Scope creep)**: error handling non richiesto, parametri bonus

**Azione:**
- **BLOCKER (CAT-1, CAT-2, CAT-6, CAT-7, CAT-8, CAT-9, CAT-10)**: fixa automaticamente, ri-testa
- **WARNING (CAT-3, CAT-4, CAT-5, CAT-11)**: stampa i finding, procedi
- **CLEAN**: procedi silenziosamente

### 1.5 Commit e push

**Se PASS:**

```bash
git add <file modificati>
git commit -m "feat(<modulo>): <titolo task> (#N/M)

<una riga di spiegazione del perche'>

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

Stampa:
```
Task #N/M: <titolo> — PASS
   File: <lista>
   Commit: <hash breve>
```

Push al remote per attivare la CI in background:
```bash
git push origin $BRANCH
```

**Se FAIL (primo tentativo):**
- Analizza l'errore
- Tenta un fix (max 2 tentativi)
- Se il fix funziona — committa normalmente
- Se il fix non funziona — vai a 1.6

### 1.6 Gestione fallimento

Stampa:
```
Task #N/M: <titolo> — FAIL dopo 2 tentativi
   Errore: <messaggio di errore>
```

**Strategia smart:**
- Controlla se task successivi dipendono da questo task
- Se **SI** (task bloccante): **STOP COMPLETO**
  ```
  STOP: Task #N e' bloccante per task successivi.
     Intervento manuale richiesto.
     Per riprendere dopo il fix: /orchestrate --continue plan/<file>.md
  ```
- Se **NO** (task indipendente): **SKIP e continua**
  ```
  SKIP: Task #N non blocca task successivi. Continuo con Task #N+1.
     Task #N andra' completato manualmente.
  ```
  Annulla le modifiche del task fallito:
  ```bash
  git checkout -- <file modificati dal task>
  ```

---

## Fase 2: Self-review

Dopo che tutti i task (o tutti quelli non skippati) sono completati:

```bash
git diff main..HEAD --stat
git diff main..HEAD
```

Verifica rapida su tutte le modifiche del branch:
- [ ] Correttezza logica
- [ ] No credenziali esposte
- [ ] Naming coerente (snake_case funzioni, PascalCase classi)
- [ ] Import corretti
- [ ] Type hints presenti nelle signature
- [ ] Configurazioni Flask/Gunicorn corrette

Se trovi problemi:
1. Fixa
2. Committa il fix: `fix(<modulo>): <descrizione fix>`
3. Push: `git push origin $BRANCH`

---

## Fase 2.5: Docker Build Verification

Verifica che il Docker build funzioni con le modifiche:

```bash
docker build -t gmt:test -f docker/Dockerfile .
```

Confronta con la baseline catturata in Fase 0.4:
- **Build** deve completare senza errori
- **Entrypoint** non deve avere errori di sintassi
- Se il piano tocca kubernetes/: verifica anche i manifest con `kubectl apply --dry-run=client -f kubernetes/base/`

Se il build fallisce: analizza la causa e fixa.

---

## Fase 3: Test suite completa

```bash
pytest tests/ -v 2>/dev/null || echo "No tests directory — skipping full test suite"
```

Se la test suite fallisce ma i test specifici dei task erano passati, potrebbe essere una regressione. Analizza e fixa.

---

## Fase 3.5: CI Verification

La draft PR e' stata creata in Fase 0.6 e ogni task ha fatto push in Fase 1.5, quindi la CI e' gia' in corso sull'ultimo commit. Qui aspettiamo il risultato e fixiamo se necessario.

### 3.5.1 Aspetta la CI run

```bash
# Aspetta che la run venga creata (la CI si attiva su PR)
sleep 10

# Trova la run piu' recente
gh run list -b $BRANCH --limit 1 --json databaseId,status,conclusion,headSha
```

Se c'e' una run in corso o appena creata:
```bash
gh run watch <run-id> --exit-status
```

Se non c'e' CI configurata: stampa `CI: N/A (no workflows configured)` e procedi alla Fase 4.

### 3.5.2 Analisi risultato

**Se PASS:**
```
CI PASS — Tutti i job sono passati.
```
Procedi alla Fase 4.

**Se FAIL:**
```
CI FAIL — Analisi in corso...
```

Scarica i log dei job falliti:
```bash
gh run view <run-id> --log-failed 2>&1 | tail -200
```

Per ogni job fallito:
1. Identifica tipo di errore e root cause
2. Leggi i file coinvolti
3. Applica il fix minimale
4. Lint + test locale
5. Commit:
   ```bash
   git add <file>
   git commit -m "fix(ci): <descrizione fix>

   Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
   ```
6. Push:
   ```bash
   git push origin $BRANCH
   ```

### 3.5.3 Retry loop

- Dopo ogni push, aspetta la nuova CI run (sleep 10, poi `gh run list`)
- **Tentativo 1**: fix manuale come descritto in 3.5.2
- **Tentativo 2**: analisi approfondita dei log
- **Tentativo 3**: ultimo tentativo

Se dopo 3 tentativi la CI ancora fallisce:
```
CI FAIL dopo 3 tentativi — STOP COMPLETO.
   Ultimo errore: <descrizione>
   Nessun fix automatico trovato.
   Intervento manuale richiesto su CI.
   Per riprendere: /orchestrate --continue plan/<file>.md
```
**STOP COMPLETO** — non procedere alla Fase 4.

**IMPORTANTE: NON esiste la possibilita' di procedere con `CI = WARNING`.** La CI deve passare. L'unica eccezione e' se il fallimento e' dimostrabilmente pre-existing (il test fallisce anche sulla baseline di main documentata in Fase 0.3 — vedi Fase 3.5.4).

### 3.5.4 Verifica pre-existing (solo se CI fallisce per test)

Se i log mostrano test falliti nella CI, prima di procedere con i retry:

```bash
# Verifica se il test fallisce anche su main tramite worktree isolato
git worktree remove /tmp/gmt-main-check --force 2>/dev/null || true
git worktree add /tmp/gmt-main-check main
cd /tmp/gmt-main-check && pytest tests/ -q 2>&1
git worktree remove /tmp/gmt-main-check --force
```

- Se il test **passa su main**: e' una REGRESSIONE dell'agente — vai al retry loop, DEVI fixare
- Se il test **fallisce anche su main**: e' genuinamente pre-existing — documentare con output come prova, applicare boy scout fix se possibile, procedere

---

## Fase 4: Finalizzazione PR

Se tutti i check sono passati, aggiorna la PR da draft a ready:

```bash
gh pr ready
```

Aggiorna il body della PR con un summary delle modifiche:

```bash
gh pr edit --body "$(cat <<'PREOF'
## Summary
<bullet points delle modifiche principali>

## Test plan
- Tests passing (or: tests to be created)
- Docker build: verified
- K8s manifests: validated (if applicable)
- CI: passing (if configured)

Auto-generated by `/orchestrate` from `plan/<file>.md`

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
PREOF
)"
```

---

## Fase 5: Report finale

```
===================================================
  ORCHESTRATE REPORT — GMT
===================================================

  Piano:    plan/<file>.md
  Branch:   feat/<feature-name>
  PR:       #<numero> (<url>)
  Durata:   <N task completati>/<M totali>

  Task completati:
    #1: <titolo> — PASS — <commit hash>
    #2: <titolo> — PASS — <commit hash>
    #3: <titolo> — SKIPPED (non bloccante)

  Cross-Review:     APPROVED (score X/10) | SKIPPED (marker presente)
  LQN Challenge:    APPROVED | N/A
  K8s/Docker Check: PASS | FAIL | N/A
  Verify-Plan:      PASS | NEEDS_PLAN_UPDATE | BLOCKED
  Review:           CLEAN | <N fix applicati>
  BS Check:         <N BLOCKER fixati, M WARNING segnalati> | CLEAN
  Docker Build:     PASS | FAIL
  Test:             PASS (N tests) | FAIL | N/A (no tests)
  CI:               PASS | FAIL | N/A (no workflows)

  Commit totali: N
  File modificati: N

===================================================
```

Se ci sono task SKIPPED, aggiungere:
```
  Task incompleti:
    #3: <titolo> — <motivo del fallimento>
    Risolvi manualmente, poi: /orchestrate --continue plan/<file>.md
```

---

## Regole fondamentali

1. **Autonomia massima** — procedi senza chiedere, fermati solo su fallimenti bloccanti
2. **Verifica sempre** — mai committare codice che non passa lint o test
3. **Comandi diretti** — usare `pytest`, `ruff` (non prefissi .venv/bin/)
4. **Micro-commit** — un commit per task, messaggi descrittivi con numero task
5. **Reversibilita'** — se un task fallisce, annulla le sue modifiche prima di procedere
6. **Trasparenza** — stampa lo stato dopo ogni task
7. **No scope creep** — implementa ESATTAMENTE quello nel piano
8. **Docker build** — il build deve sempre funzionare dopo le modifiche
9. **Working tree pulito** — non lasciare mai modifiche non committate tra un task e l'altro
10. **Zero excuses** — se un test fallisce, fixalo. "Pre-existing" non e' una scusa valida senza prova
    oggettiva (output del test eseguito su main via worktree). Se la CI fallisce, analizza i log.
    Mai procedere con WARNING su CI o test. Mai.
11. **Ownership totale** — l'agente e' responsabile dell'intero codebase durante l'esecuzione, non solo
    delle righe che ha toccato. Un bug trovato durante l'esecuzione va fixato, non classificato come
    "out of scope" o "pre-existing". Boy scout rule: lascia il codebase meglio di come l'hai trovato.
