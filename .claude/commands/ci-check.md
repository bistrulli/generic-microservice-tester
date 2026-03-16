# GMT CI Diagnostics Agent

Sei l'agente diagnostico CI per Generic Microservice Tester. Il tuo compito e' identificare e risolvere fallimenti nella pipeline di build/test.

**Input opzionale**: `$ARGUMENTS` (URL del run CI fallito o descrizione del problema)

## Pipeline diagnostica

### Step 1: Stato corrente del repository

```bash
# Stato git
git status
git log --oneline -5

# File modificati rispetto a main
git diff --name-only main...HEAD
```

### Step 2: Test Python

```bash
# Verifica che le dipendenze siano installate
pip install -r src/requirements.txt
pip install pytest pytest-mock pytest-cov ruff

# Esegui test
pytest tests/ -v --tb=long

# Se falliscono, esegui singolarmente per isolare
pytest tests/test_app.py -v --tb=long -x
```

### Step 3: Linting e type checking

```bash
# Ruff (linter)
ruff check src/
ruff check tests/

# Ruff format check
ruff format --check src/
ruff format --check tests/
```

### Step 4: Docker build

```bash
# Build immagine
docker build -t gmt-ci-check:latest -f docker/Dockerfile .

# Verifica che il container si avvii
docker run --rm -d --name gmt-ci-test \
  -e SERVICE_NAME=ci-test \
  -e SERVICE_TIME_SECONDS=0 \
  -e OUTBOUND_CALLS="" \
  -e GUNICORN_WORKERS=1 \
  -p 8080:8080 \
  gmt-ci-check:latest

# Health check
sleep 3
curl -s http://localhost:8080/ | python -m json.tool

# Cleanup
docker stop gmt-ci-test
```

### Step 5: Kubernetes manifests validation

```bash
# Valida manifesti base
kubectl apply --dry-run=client -f kubernetes/base/deployment.yaml
kubectl apply --dry-run=client -f kubernetes/base/service.yaml

# Valida esempi
for f in kubernetes/examples/*.yaml; do
  echo "Validating $f..."
  kubectl apply --dry-run=client -f "$f"
done
```

### Step 6: Dependency check

```bash
# Verifica versioni in requirements.txt
pip install pip-audit
pip-audit -r src/requirements.txt

# Verifica compatibilita' versioni
pip check
```

## Diagnosi dei fallimenti comuni

### Test falliti
1. **ImportError**: Dipendenza mancante in requirements.txt
2. **Mock non configurato**: psutil o requests non mockati correttamente
3. **Env var mancante**: Test che dipende da env vars non impostate
4. **Port conflict**: Container gia' in ascolto su 8080

### Docker build fallito
1. **COPY failed**: File rinominato/spostato senza aggiornare Dockerfile
2. **pip install failed**: Versione pacchetto non disponibile
3. **Permission denied**: entrypoint.sh non eseguibile

### K8s validation fallita
1. **Invalid YAML**: Indentazione errata
2. **Missing field**: Campo required mancante nel manifest
3. **Invalid value**: Tipo errato per un campo (es. string invece di int)

## Output

Per ogni problema trovato, riporta:
```
### Problema: [titolo]
- **Dove**: [file:linea]
- **Cosa**: [descrizione errore]
- **Perche'**: [causa root]
- **Fix**: [soluzione proposta]
```

Al termine, riporta lo stato complessivo:
```
## Stato CI: [GREEN/RED]
- Test: [PASS/FAIL] (X/Y passati)
- Lint: [PASS/FAIL]
- Docker: [PASS/FAIL]
- K8s: [PASS/FAIL]
```
