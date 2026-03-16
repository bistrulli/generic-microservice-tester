# GMT Topology Benchmark

Benchmark different Kubernetes topologies deployed with Generic Microservice Tester. Verify Docker builds, K8s deployments, and load test results. Produce a structured report.

## Workflow

### Phase 1: Build Verification
1. Verify the Docker image builds successfully:
   ```bash
   docker build -f docker/Dockerfile -t gmt-benchmark:test .
   ```
2. Confirm the image starts and responds on port 8080:
   ```bash
   docker run --rm -d -p 8080:8080 -e SERVICE_NAME=test -e SERVICE_TIME_SECONDS=0.01 gmt-benchmark:test
   curl -s http://localhost:8080/ | python3 -m json.tool
   ```
3. Record build time, image size, and startup latency.

### Phase 2: Topology Deployment
For each topology in `kubernetes/examples/`:
1. Parse the manifest to identify all services, their `SERVICE_TIME_SECONDS`, `OUTBOUND_CALLS`, and `GUNICORN_WORKERS` settings.
2. Validate the manifest:
   ```bash
   kubectl apply --dry-run=client -f kubernetes/examples/<topology>.yaml
   ```
3. If a live cluster is available, deploy and wait for rollout:
   ```bash
   kubectl apply -f kubernetes/examples/<topology>.yaml
   kubectl rollout status deployment/<name> --timeout=120s
   ```
4. Verify all pods reach `Running` state and all services resolve via DNS.

### Phase 3: Load Testing (if cluster available)
For each deployed topology:
1. Identify the entry service (the service that receives external traffic).
2. Run a baseline load test against the entry service endpoint.
3. Record: throughput (req/s), mean latency, p50/p95/p99 latencies, error rate.
4. If HPA is configured, observe scaling events and record time-to-scale.

### Phase 4: Report Generation

Produce the report in this exact format:

```
============================================================
GMT TOPOLOGY BENCHMARK REPORT
Date: YYYY-MM-DD
============================================================

BUILD VERIFICATION
  Image Build:       PASS/FAIL (build time: Xs, size: XMB)
  Container Start:   PASS/FAIL (startup latency: Xms)
  Health Check:      PASS/FAIL (response: HTTP XXX)

------------------------------------------------------------
TOPOLOGY: <name>
------------------------------------------------------------
  Manifest Valid:    PASS/FAIL
  Services:          <count> services, <count> deployments
  Architecture:      <description (e.g., "3-tier chain")>

  Service Configuration:
    <service-name>:
      SERVICE_TIME:    <value>s
      OUTBOUND_CALLS:  <value>
      WORKERS/THREADS: <workers>w/<threads>t
      REPLICAS:        <count>

  Deployment Status: PASS/FAIL/SKIPPED
  Load Test Results: (if available)
    Throughput:      X req/s
    Mean Latency:    Xms
    P95 Latency:     Xms
    P99 Latency:     Xms
    Error Rate:      X%

------------------------------------------------------------
SUMMARY
------------------------------------------------------------
  Topologies Tested: X
  All Manifests Valid: YES/NO
  Deployments Successful: X/Y
  Recommendations:
    - <actionable recommendation>
============================================================
```

## Important Rules
- NEVER modify source code, Dockerfiles, or Kubernetes manifests during benchmarking.
- If no live cluster is available, still validate manifests with `--dry-run=client` and report deployment as SKIPPED.
- Always parse actual environment variable values from the YAML -- do not guess or assume defaults.
- Report exact numbers, not approximations.
