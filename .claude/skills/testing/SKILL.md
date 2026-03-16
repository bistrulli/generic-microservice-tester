# Testing Skill -- Generic Microservice Tester

## Framework

- **Unit/Integration**: pytest
- **HTTP client testing**: Flask test client (`app.test_client()`)
- **K8s manifest validation**: `kubectl apply --dry-run=client`
- **Load testing**: locust, k6, or curl-based scripts
- **Linting**: ruff

## Flask Test Patterns

### Basic Test Client Setup

```python
import pytest
from app import app

@pytest.fixture
def client():
    """Create a Flask test client."""
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

def test_root_endpoint_returns_json(client):
    """Verify the root endpoint returns valid JSON with service name."""
    response = client.get('/')
    assert response.status_code == 200
    data = response.get_json()
    assert 'message' in data
    assert 'outbound_results' in data
```

### Testing with Environment Variables

```python
import os
from unittest.mock import patch

def test_service_name_from_env(client):
    """Verify SERVICE_NAME env var is reflected in response."""
    with patch.dict(os.environ, {'SERVICE_NAME': 'test-svc'}):
        response = client.get('/')
        data = response.get_json()
        assert 'test-svc' in data['message']

def test_zero_service_time(client):
    """Verify SERVICE_TIME_SECONDS=0 skips CPU work."""
    with patch.dict(os.environ, {'SERVICE_TIME_SECONDS': '0'}):
        response = client.get('/')
        assert response.status_code == 200

def test_service_time_positive(client):
    """Verify positive SERVICE_TIME_SECONDS triggers CPU work."""
    with patch.dict(os.environ, {'SERVICE_TIME_SECONDS': '0.001'}):
        response = client.get('/')
        assert response.status_code == 200
```

### Testing Outbound Call Parsing

```python
from app import parse_outbound_calls
from unittest.mock import patch

def test_empty_outbound_calls():
    """Verify empty OUTBOUND_CALLS returns empty lists."""
    with patch.dict(os.environ, {'OUTBOUND_CALLS': ''}):
        prob, fixed = parse_outbound_calls()
        assert prob == []
        assert fixed == []

def test_sync_call_parsing():
    """Verify SYNC call is parsed correctly."""
    with patch.dict(os.environ, {'OUTBOUND_CALLS': 'SYNC:backend-svc:1.0'}):
        prob, fixed = parse_outbound_calls()
        assert len(fixed) == 1
        assert fixed[0]['type'] == 'SYNC'
        assert fixed[0]['service'] == 'backend-svc'
        assert fixed[0]['probability'] == 1.0

def test_probabilistic_call_parsing():
    """Verify probabilistic calls are separated from fixed calls."""
    with patch.dict(os.environ, {
        'OUTBOUND_CALLS': 'SYNC:svc-a:0.6,SYNC:svc-b:0.4,ASYNC:logger:1.0'
    }):
        prob, fixed = parse_outbound_calls()
        assert len(prob) == 2  # svc-a and svc-b
        assert len(fixed) == 1  # logger

def test_malformed_call_definition():
    """Verify malformed call definitions are skipped gracefully."""
    with patch.dict(os.environ, {'OUTBOUND_CALLS': 'INVALID_FORMAT'}):
        prob, fixed = parse_outbound_calls()
        assert prob == []
        assert fixed == []
```

### Testing CPU Simulation (do_work)

```python
from app import do_work
from unittest.mock import patch
import time

def test_do_work_zero_time():
    """Verify do_work returns immediately when SERVICE_TIME_SECONDS=0."""
    with patch.dict(os.environ, {'SERVICE_TIME_SECONDS': '0'}):
        start = time.monotonic()
        do_work()
        elapsed = time.monotonic() - start
        assert elapsed < 0.1  # Should return near-instantly

def test_do_work_consumes_cpu():
    """Verify do_work actually consumes CPU time."""
    with patch.dict(os.environ, {'SERVICE_TIME_SECONDS': '0.05'}):
        start = time.process_time()
        do_work()
        cpu_elapsed = time.process_time() - start
        # Should have consumed some CPU (exact amount varies due to exponential distribution)
        assert cpu_elapsed > 0
```

## Docker Build Tests

```bash
# Test 1: Image builds successfully
docker build -f docker/Dockerfile -t gmt:test . && echo "PASS: build" || echo "FAIL: build"

# Test 2: Container starts and responds
CONTAINER_ID=$(docker run -d --rm -p 8080:8080 \
  -e SERVICE_NAME=test \
  -e SERVICE_TIME_SECONDS=0.001 \
  gmt:test)
sleep 3
STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/)
docker stop $CONTAINER_ID
[ "$STATUS" = "200" ] && echo "PASS: responds" || echo "FAIL: responds (got $STATUS)"

# Test 3: Response contains expected fields
RESPONSE=$(curl -s http://localhost:8080/)
echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); assert 'message' in d; assert 'outbound_results' in d; print('PASS: response format')" || echo "FAIL: response format"
```

## Kubernetes Manifest Validation

```bash
# Validate all manifests with dry-run
for f in kubernetes/examples/*.yaml; do
  kubectl apply --dry-run=client -f "$f" 2>&1
  if [ $? -eq 0 ]; then
    echo "PASS: $f"
  else
    echo "FAIL: $f"
  fi
done

# Validate base templates
kubectl apply --dry-run=client -f kubernetes/base/deployment.yaml
kubectl apply --dry-run=client -f kubernetes/base/service.yaml
```

## Integration Test Patterns

### Deploy-and-Verify (requires live cluster)

```bash
# 1. Deploy a topology
kubectl apply -f kubernetes/examples/2-tier-app.yaml

# 2. Wait for rollout
kubectl rollout status deployment/entry-deployment --timeout=120s
kubectl rollout status deployment/backend-deployment --timeout=120s

# 3. Verify pods are running
kubectl get pods -l app=entry -o jsonpath='{.items[0].status.phase}' | grep -q Running
kubectl get pods -l app=backend -o jsonpath='{.items[0].status.phase}' | grep -q Running

# 4. Port-forward and test
kubectl port-forward svc/task1-svc 8080:80 &
PF_PID=$!
sleep 2
curl -s http://localhost:8080/ | python3 -m json.tool
kill $PF_PID

# 5. Cleanup
kubectl delete -f kubernetes/examples/2-tier-app.yaml
```

### Load Test with curl

```bash
# Simple load test: 100 sequential requests
for i in $(seq 1 100); do
  curl -s -o /dev/null -w "%{http_code} %{time_total}\n" http://localhost:8080/
done | awk '{
  codes[$1]++;
  sum+=$2; count++;
  if($2>max) max=$2;
} END {
  print "Requests:", count;
  for(c in codes) print "  HTTP", c ":", codes[c];
  print "Mean latency:", sum/count "s";
  print "Max latency:", max "s";
}'
```

## Module-to-Test Mapping

| Source | Test Focus |
|---|---|
| `src/app.py::handle_request()` | Root endpoint returns JSON, includes service name, includes outbound results |
| `src/app.py::do_work()` | CPU time consumption, zero-time bypass, exponential distribution behavior |
| `src/app.py::parse_outbound_calls()` | Parsing logic, probabilistic vs fixed separation, malformed input handling |
| `src/app.py::make_call()` | HTTP call execution, error handling, timeout behavior |
| `src/app.py::make_async_call_pooled()` | Fire-and-forget semantics, thread pool submission, isolation |
| `docker/Dockerfile` | Image builds, container starts, port exposed |
| `docker/entrypoint.sh` | Gunicorn starts with correct workers/threads, env var defaults |
| `kubernetes/base/*.yaml` | Valid K8s resources, correct labels/selectors |
| `kubernetes/examples/*.yaml` | Valid K8s resources, service names match OUTBOUND_CALLS references |

## Test Conventions

- Test files go in a `tests/` directory at the project root.
- Test file naming: `test_<module>.py`.
- Use `conftest.py` for shared fixtures (Flask test client, environment variable presets).
- Mock external HTTP calls with `unittest.mock.patch` or `responses` library.
- Never make real outbound HTTP calls in unit tests.
- For integration tests that require K8s, check for cluster availability first and skip if unavailable.
