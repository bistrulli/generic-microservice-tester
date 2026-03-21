# Piano: Pulire deploy generator — zero env var OTEL + naming pulito

<!-- cross-reviewed -->

- **File:** `tools/lqn_compiler.py`, `tools/deploy_gen.py`, `src/app.py`, `tests/unit/test_lqn_compiler.py`
- **Stima:** 4 task, 4 file
- **Data:** 2026-03-20

## Problema

Il generatore di manifest K8s produce Deployment con naming e env var ridondanti:

1. **Deployment name**: `compose-post-deployment` — il suffisso `-deployment` inquina il service name
2. **6 env var OTEL/SERVICE**: tutte settabili automaticamente dall'Operator + Instrumentation CR

## Verifica live: l'Operator inietta TUTTO da solo

Testato con un Deployment senza nessuna env var OTEL, solo l'annotation:

```yaml
annotations:
  instrumentation.opentelemetry.io/inject-python: "true"
```

L'Operator ha iniettato **automaticamente**:

| Env var | Valore iniettato | Fonte |
|---------|-----------------|-------|
| `OTEL_SERVICE_NAME` | `test-no-otel-svcname` (= Deployment name!) | Operator webhook |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://otel-collector.observability:4318` | Instrumentation CR |
| `OTEL_TRACES_EXPORTER` | `otlp` | Default Operator |
| `OTEL_METRICS_EXPORTER` | `otlp` | Default Operator |
| `OTEL_LOGS_EXPORTER` | `otlp` | Default Operator |
| `OTEL_PROPAGATORS` | `tracecontext,baggage` | Instrumentation CR |
| `OTEL_RESOURCE_ATTRIBUTES` | `k8s.deployment.name=..., k8s.namespace.name=...` | Operator |
| `PYTHONPATH` | `/otel-auto-instrumentation-python/...` | Init container |

**Conclusione: ZERO env var OTEL necessarie nel manifest.** L'unico requisito e' che il Deployment name sia il service name desiderato (senza `-deployment` suffix).

## Soluzione

1. Rinominare Deployment da `{name}-deployment` a `{name}`
2. Rimuovere TUTTE le env var OTEL e SERVICE dal template (6 righe per servizio)
3. L'app legge `OTEL_SERVICE_NAME` (iniettata dall'Operator) con fallback per locale

### Prima vs Dopo

**PRIMA (8 env var, 13 righe):**
```yaml
kind: Deployment
metadata:
  name: compose-post-deployment
spec:
  template:
    metadata:
      annotations:
        instrumentation.opentelemetry.io/inject-python: "true"
    spec:
      containers:
      - env:
        - name: SERVICE_NAME
          value: "compose-post"
        - name: OTEL_SERVICE_NAME
          value: "compose-post"
        - name: OTEL_EXPORTER_OTLP_ENDPOINT
          value: "http://otel-collector.observability:4318"
        - name: OTEL_TRACES_EXPORTER
          value: "otlp"
        - name: OTEL_METRICS_EXPORTER
          value: "none"
        - name: OTEL_LOGS_EXPORTER
          value: "none"
        - name: GUNICORN_WORKERS
          value: "5"
        - name: LQN_TASK_CONFIG
          value: '{...}'
```

**DOPO (2 env var, 5 righe):**
```yaml
kind: Deployment
metadata:
  name: compose-post
spec:
  template:
    metadata:
      annotations:
        instrumentation.opentelemetry.io/inject-python: "true"
    spec:
      containers:
      - env:
        - name: GUNICORN_WORKERS
          value: "5"
        - name: LQN_TASK_CONFIG
          value: '{...}'
```

**Per uno sviluppatore terzo (senza GMT):**
```yaml
# L'UNICA cosa da aggiungere al manifest esistente:
annotations:
  instrumentation.opentelemetry.io/inject-java: "true"
# ZERO env var. ZERO config. L'Operator fa tutto.
```

---

## Task 1: Rinominare Deployment (rimuovere suffisso -deployment)

### File

`tools/lqn_compiler.py`

### Modifica

Nella funzione `generate_deployment_yaml()`:
- `name: {k8s_name}-deployment` → `name: {k8s_name}`

Verificare anche `deploy_gen.py` se referenzia il Deployment name nel `cmd_test()` o altrove.

### Perche'

L'Operator usa il Deployment name come `OTEL_SERVICE_NAME`. Senza `-deployment`, il nome e' gia' pulito e non serve override.

### Verifica

```bash
cd /Users/emilio-imt/git/generic-microservice-tester
python -c "
from tools.lqn_compiler import compile_model
from src.lqn_parser import parse_lqn_file
model = parse_lqn_file('test/lqn-groundtruth/template/template.lqn')
yamls = compile_model(model, 'bistrulli/generic-microservice-tester:latest', 'test-ns')
for y in yamls:
    if 'kind: Deployment' in y:
        for line in y.split('\n'):
            if '  name:' in line and '-deployment' in line:
                print(f'FAIL: {line.strip()}')
                break
        else:
            print('OK: no -deployment suffix')
"
```

---

## Task 2: Rimuovere TUTTE le env var OTEL e SERVICE

### File

`tools/lqn_compiler.py`

### Modifica

Nella funzione `generate_deployment_yaml()`, rimuovere 6 env var:

- `SERVICE_NAME` — l'app legge `OTEL_SERVICE_NAME` (Task 3)
- `OTEL_SERVICE_NAME` — l'Operator la inietta dal Deployment name
- `OTEL_EXPORTER_OTLP_ENDPOINT` — l'Operator la inietta dal CR
- `OTEL_TRACES_EXPORTER` — default Operator
- `OTEL_METRICS_EXPORTER` — default Operator
- `OTEL_LOGS_EXPORTER` — default Operator

Mantenere solo: `GUNICORN_WORKERS`, `LQN_TASK_CONFIG`

### Verifica

```bash
cd /Users/emilio-imt/git/generic-microservice-tester
python -c "
from tools.lqn_compiler import compile_model
from src.lqn_parser import parse_lqn_file
model = parse_lqn_file('test/lqn-groundtruth/template/template.lqn')
yamls = compile_model(model, 'bistrulli/generic-microservice-tester:latest', 'test-ns')
for y in yamls:
    for banned in ['OTEL_EXPORTER', 'OTEL_TRACES', 'OTEL_METRICS', 'OTEL_LOGS', 'OTEL_SERVICE_NAME', 'name: SERVICE_NAME']:
        assert banned not in y, f'FAIL: {banned} still present'
    if 'GUNICORN_WORKERS' in y:
        print('OK: only app env vars remain')
"
```

---

## Task 3: Aggiornare app.py per usare OTEL_SERVICE_NAME

### File

`src/app.py`

### Modifica

Righe 656 e 679:

**DA:**
```python
my_name = os.environ.get("SERVICE_NAME", "generic-service")
```

**A:**
```python
my_name = os.environ.get("OTEL_SERVICE_NAME", os.environ.get("SERVICE_NAME", "generic-service"))
```

Catena di fallback:
1. `OTEL_SERVICE_NAME` — iniettata automaticamente dall'Operator in K8s
2. `SERVICE_NAME` — backward compat con vecchi manifest / deploy manuali
3. `"generic-service"` — default locale senza K8s

### Verifica

```bash
cd /Users/emilio-imt/git/generic-microservice-tester
python -m pytest tests/unit/ -v
```

---

## Task 4: Aggiornare test + commento deploy_gen.py

### File

`tests/unit/test_lqn_compiler.py`, `tools/deploy_gen.py`

### Modifica test

1. **Rimuovere** assertion su tutte le env var OTEL (endpoint, traces, metrics, logs, service_name)
2. **Aggiungere** assertion negativa: env var OTEL NON devono essere presenti nei Deployment
3. **Aggiornare** assertion Deployment name: `{name}-deployment` → `{name}`
4. **Mantenere** assertion su annotation `inject-python: "true"`
5. **Mantenere** assertion su `GUNICORN_WORKERS` e `LQN_TASK_CONFIG`

### Modifica commento deploy_gen.py

Nella sezione Instrumentation CR:

```bash
echo "[3/5] Applying OTEL Instrumentation CR..."
# The OTEL Operator auto-injects ALL OTEL env vars into annotated pods:
#   OTEL_SERVICE_NAME (from Deployment name), OTEL_EXPORTER_OTLP_ENDPOINT,
#   OTEL_TRACES/METRICS/LOGS_EXPORTER, OTEL_RESOURCE_ATTRIBUTES, PYTHONPATH.
# No OTEL env vars needed in Deployment manifests — just the annotation.
```

### Verifica

```bash
cd /Users/emilio-imt/git/generic-microservice-tester
python -m pytest tests/unit/ -v

# E2E: genera un deploy.sh e verifica che non contenga env var OTEL
python -m tools.deploy_gen test/lqn-groundtruth/template/template.lqn --namespace test > /tmp/test-deploy.sh
grep -c "OTEL_" /tmp/test-deploy.sh
# Atteso: poche occorrenze (solo nei commenti e nell'Instrumentation CR, non nei Deployment)
```

---

## Impatto per lo sviluppatore terzo

Con questa modifica, il messaggio per il customer diventa ancora piu' semplice:

> Per integrare i tuoi microservizi con SLOPilot:
> 1. Verifica che lo stack observability sia installato (SLOPilotInstallation.md)
> 2. Aggiungi UNA annotation al tuo Deployment:
>    ```yaml
>    annotations:
>      instrumentation.opentelemetry.io/inject-java: "true"
>    ```
> 3. Fatto. Zero env var. Zero config. Zero codice.

---

## Task 5: Supporto multi-linguaggio per annotation OTEL

### File

`tools/lqn_compiler.py`, `tools/deploy_gen.py`

### Problema attuale

L'annotation e' hardcodata a Python:
```yaml
annotations:
  instrumentation.opentelemetry.io/inject-python: "true"
```

Questo impedisce di usare il GMT per generare sistemi con microservizi Java, Node.js, .NET o Go.

### Modifica lqn_compiler.py

1. Aggiungere parametro `language` alla funzione `generate_deployment_yaml()` (default `"python"` per backward compat)
2. L'annotation diventa parametrica:
   ```python
   f'instrumentation.opentelemetry.io/inject-{language}: "true"'
   ```
3. Validare che `language` sia uno dei valori supportati: `python`, `java`, `nodejs`, `dotnet`, `go`, `apache-httpd`

### Modifica deploy_gen.py

1. Aggiungere flag CLI `--language` (default `python`):
   ```python
   parser.add_argument("--language", default="python",
       choices=["python", "java", "nodejs", "dotnet", "go", "apache-httpd"],
       help="Application language for OTEL auto-instrumentation annotation")
   ```
2. Passare il valore a `compile_model()` → `generate_deployment_yaml()`
3. Aggiornare l'Instrumentation CR nel template deploy.sh per includere il linguaggio scelto:
   - Se `python`: sezione `python:` con image auto-instrumentation Python
   - Se `java`: sezione `java:` con image auto-instrumentation Java
   - etc.

   Oppure (piu' semplice): generare SEMPRE l'Instrumentation CR con TUTTI i linguaggi (come in SLOPilotInstallation.md) — l'Operator usa solo quello corrispondente all'annotation.

### Impatto sulla Instrumentation CR

**Opzione semplice (raccomandata)**: l'Instrumentation CR include tutti i linguaggi. Solo quello matchato dall'annotation viene iniettato:

```yaml
spec:
  exporter:
    endpoint: http://otel-collector.observability:4318
  propagators: [tracecontext, baggage]
  python:
    image: ghcr.io/open-telemetry/opentelemetry-operator/autoinstrumentation-python:0.46b0
  java:
    image: ghcr.io/open-telemetry/opentelemetry-operator/autoinstrumentation-java:2.10.0
  nodejs:
    image: ghcr.io/open-telemetry/opentelemetry-operator/autoinstrumentation-nodejs:0.53.0
  dotnet:
    image: ghcr.io/open-telemetry/opentelemetry-operator/autoinstrumentation-dotnet:1.9.0
  go:
    image: ghcr.io/open-telemetry/opentelemetry-operator/autoinstrumentation-go:0.16.0
```

Con questa CR, ogni Deployment sceglie il linguaggio solo via annotation — zero altri cambiamenti.

### Esempio di utilizzo

```bash
# Sistema Python (default, come oggi)
python -m tools.deploy_gen model.lqn --namespace my-ns

# Sistema Java (Spring Boot)
python -m tools.deploy_gen model.lqn --namespace my-ns --language java

# Sistema misto (non supportato in questa fase — tutti i task dello stesso linguaggio)
# Per sistemi misti servirebbe un campo language per-task nel modello LQN — enhancement futuro
```

### Verifica

```bash
cd /Users/emilio-imt/git/generic-microservice-tester

# Default (python)
python -m tools.deploy_gen test/lqn-groundtruth/template/template.lqn --namespace test > /tmp/test-py.sh
grep "inject-python" /tmp/test-py.sh | wc -l
# Atteso: N (uno per ogni task non-reference)

# Java
python -m tools.deploy_gen test/lqn-groundtruth/template/template.lqn --namespace test --language java > /tmp/test-java.sh
grep "inject-java" /tmp/test-java.sh | wc -l
# Atteso: N (uno per ogni task non-reference)
grep "inject-python" /tmp/test-java.sh | wc -l
# Atteso: 0

# Test unitari
python -m pytest tests/unit/test_lqn_compiler.py -v
```

### Note

- Per sistemi **misti** (es. gateway in Go + backend in Java) servirebbe un campo `language` per-task nel modello LQN o nella config. Questo e' un enhancement futuro — per ora tutti i task usano lo stesso linguaggio.
- Le immagini auto-instrumentation sono **pinned a versioni specifiche** (non `:latest`) per riproducibilita' — come documentato in SLOPilotInstallation.md.

---

## Rischi

| Rischio | Probabilita' | Mitigazione |
|---------|--------------|-------------|
| Operator versione vecchia non inietta OTEL_SERVICE_NAME | BASSA | Testato con Operator corrente. Se non funziona, lo sviluppatore puo' aggiungere l'env var manualmente. |
| Deployment name non corrisponde al service name desiderato | MEDIA | Documentare: il Deployment name DEVE essere il service name. Se il Deployment si chiama `my-app-v2`, il service name sara' `my-app-v2`. |
| Backward compat deploy.sh vecchi | NESSUNO | I vecchi manifest con env var esplicite continuano a funzionare — hanno priorita' su quelle iniettate. |
| App in locale senza Operator | CERTA | Fallback chain in app.py: `OTEL_SERVICE_NAME` → `SERVICE_NAME` → `"generic-service"` |
