# Piano: Fix OTEL span naming for per-entry metrics

<!-- cross-reviewed -->

- **File:** `src/app.py`
- **Stima:** 1 task, 1 file, ~10 righe
- **Data:** 2026-03-20

## Problema

Il route Flask principale è un wildcard parametrico:

```python
# src/app.py, riga 617
@app.route("/<entry_name>")
def handle_request(entry_name):
```

L'auto-instrumentation OTEL (FlaskInstrumentor) genera lo span_name dal **pattern** del route, non dal valore reale del parametro. Risultato:

- Richiesta HTTP: `GET /POST_compose`
- span_name in Jaeger/Prometheus: `GET /<entry_name>` (letteralmente la stringa parametrica)
- span_name atteso: `GET /POST_compose`

Questo rende **impossibile distinguere le metriche per-endpoint** in Prometheus (throughput, latency per entry), perché tutte le entry di un servizio appaiono sotto lo stesso span_name `GET /<entry_name>`.

**Impatto:** SLOPilot/TLG non riesce a fare confronto per-entry tra predizioni del solver e metriche reali. Per servizi multi-entry (es. user_service con GET_user_id + GET_user_profile), il throughput/response_time aggregato non matcha le predizioni per-entry del solver.

## Soluzione

Aggiornare lo span_name manualmente **dopo** che Flask ha risolto il parametro, usando l'API OpenTelemetry. L'import è protetto da try/except perché OTEL è disponibile solo quando l'auto-instrumentation è iniettata (in K8s), non in esecuzione locale.

## Root cause analysis

1. Flask registra `/<entry_name>` come route parametrico (Werkzeug rule)
2. FlaskInstrumentor crea lo span **durante il routing**, usando `request.url_rule.rule` che è il pattern `/<entry_name>`
3. Il valore reale di `entry_name` è disponibile solo DOPO il routing (in `flask.request.view_args`)
4. Lo span è già creato con il nome sbagliato → serve `span.update_name()` per sovrascriverlo

## Alternativa scartata: route individuali

Registrare route individuali per ogni entry name dalla LQN_TASK_CONFIG:

```python
for entry_name in config.get("entries", {}):
    app.add_url_rule(f"/{entry_name}", ...)
```

Scartata perché:
- LQN_TASK_CONFIG è un env var caricata a runtime, non disponibile al modulo import time
- Gunicorn fork workers dopo l'inizializzazione → serve pre-fork hook o app factory pattern
- Troppo invasivo per un fix che risolve lo stesso problema in 3 righe

---

## Task 1: Aggiungere span.update_name() in handle_request

### File da modificare

`src/app.py`

### Modifica 1: Handler principale (riga 617-623)

**DA:**
```python
@app.route("/<entry_name>")
def handle_request(entry_name):
    """LQN entry endpoint or legacy handler."""
    config = load_task_config()
    if config:
        return handle_lqn_request(entry_name, config)
    return handle_legacy_request()
```

**A:**
```python
@app.route("/<entry_name>")
def handle_request(entry_name):
    """LQN entry endpoint or legacy handler."""
    # Override OTEL span name from Flask route pattern (/<entry_name>)
    # to the actual entry value (e.g., /POST_compose) for per-endpoint
    # metrics in Prometheus spanmetrics.
    try:
        from opentelemetry import trace
        span = trace.get_current_span()
        if span.is_recording():
            span.update_name(f"GET /{entry_name}")
    except ImportError:
        pass  # OTEL not available (local dev without auto-instrumentation)

    config = load_task_config()
    if config:
        return handle_lqn_request(entry_name, config)
    return handle_legacy_request()
```

### Spiegazione riga per riga

| Riga | Cosa fa | Perché |
|------|---------|--------|
| `try:` | Protegge l'import | OTEL disponibile solo con auto-instrumentation K8s |
| `from opentelemetry import trace` | Import lazy | Evita errore ImportError in locale |
| `span = trace.get_current_span()` | Prende lo span corrente | Creato da FlaskInstrumentor prima dell'handler |
| `if span.is_recording():` | Guard | Non fare nulla se lo span è un NoopSpan |
| `span.update_name(f"GET /{entry_name}")` | Sovrascrive il nome | Da `GET /<entry_name>` a `GET /POST_compose` |
| `except ImportError: pass` | Fallback silenzioso | Nessun effetto se OTEL non è installato |

### Note importanti

1. **L'import è lazy (dentro la funzione)**: non al top del file. Questo perché `opentelemetry` non è nelle dipendenze di `requirements.txt` — viene iniettato dall'OTEL Operator init container. Un import al top fallirebbe in locale.

2. **`span.update_name()` è idempotente**: può essere chiamato più volte, l'ultimo valore vince. Non crea un nuovo span, aggiorna quello esistente.

3. **Il metodo HTTP è hardcoded `GET`**: perché il generic-microservice-tester usa solo GET (il route `/<entry_name>` è mappato solo a GET). Se in futuro si aggiungessero POST, usare `flask.request.method` al posto di `"GET"`.

4. **Performance**: `trace.get_current_span()` è O(1) (thread-local lookup). L'overhead è trascurabile (~1μs per request).

### Verifica

1. **Build e deploy:**
   ```bash
   docker build -t bistrulli/generic-microservice-tester:latest -f docker/Dockerfile .
   docker push bistrulli/generic-microservice-tester:latest
   ```

2. **Test locale (senza OTEL):**
   ```bash
   cd /Users/emilio-imt/git/generic-microservice-tester
   LQN_TASK_CONFIG='{"task_name":"test","entries":{"my_entry":{"service_time":0.01}}}' \
     python -m flask --app src.app run --port 8080 &
   curl http://localhost:8080/my_entry
   # Deve ritornare 200 OK senza errori ImportError
   ```

3. **Test in K8s (con OTEL):**
   ```bash
   # Dopo deploy in K8s con annotation inject-python
   kubectl port-forward -n observability svc/jaeger 16686:16686 &

   # Verifica che Jaeger mostri span_name specifici per entry
   curl -s "http://localhost:16686/api/traces?service=<SERVICE>&limit=5" | \
     python3 -c "
   import sys, json
   for trace in json.load(sys.stdin).get('data', [])[:1]:
       for span in trace['spans'][:5]:
           print(f'{span[\"operationName\"]}')"
   # Atteso: GET /POST_compose, GET /GET_timeline, etc.
   # NON più: GET /<entry_name>
   ```

4. **Test Prometheus per-entry:**
   ```bash
   kubectl port-forward -n observability svc/prometheus 9090:9090 &

   # Verifica che span_name abbia valori specifici per entry
   curl -s --data-urlencode 'query=count by (span_name, service_name) (calls_total{span_kind="SPAN_KIND_SERVER"})' \
     "http://localhost:9090/api/v1/query" | python3 -m json.tool
   # Atteso: span_name="GET /POST_compose", span_name="GET /GET_timeline", etc.
   # NON più: span_name="GET /<entry_name>"
   ```

5. **Test unitari esistenti:**
   ```bash
   cd /Users/emilio-imt/git/generic-microservice-tester
   python -m pytest tests/unit/ -v
   # Tutti devono passare (il try/except non rompe nulla senza OTEL)
   ```

### Rischi

| Rischio | Probabilità | Mitigazione |
|---------|-------------|-------------|
| Import OTEL fallisce in locale | Certa | try/except con pass — nessun effetto |
| `update_name()` non supportato dalla versione OTEL | Bassa | API stabile dal 2021 (opentelemetry-api >= 1.0) |
| Span non è recording (NoopSpan) | Media | Guard `is_recording()` previene AttributeError |
| Overhead performance | Trascurabile | ~1μs per request (thread-local lookup) |
| Break dei test esistenti | Nulla | Nessuna nuova dipendenza, import protetto |
