# Performance Challenge for Generic Microservice Tester

You are a performance engineering expert. Conduct a rigorous, multi-phase performance audit of the Generic Microservice Tester (GMT) codebase.

## Phase 0: Load Context

Read ALL of these files before starting any analysis:
1. `src/app.py` - Flask application with busy-wait, HTTP calls, async delegation
2. `docker/Dockerfile` - Container build
3. `docker/entrypoint.sh` - Gunicorn configuration and startup
4. `kubernetes/base/deployment.yaml` - Base K8s deployment template
5. `src/requirements.txt` - Python dependencies
6. `kubernetes/examples/` - All example topology manifests

---

## Phase 1: Python Performance (Flask/Gunicorn Specific)

Audit these areas and score each PASS / FAIL / NEEDS WORK:

### 1.1 Gunicorn Worker Model
- [ ] Worker class is `sync` (appropriate for CPU-bound busy-wait workload)
- [ ] `GUNICORN_WORKERS` default is reasonable for typical pod CPU allocation
- [ ] `GUNICORN_THREADS` default of 1 is correct for process-based CPU timing accuracy
- [ ] Thread safety: global `_last_user_time` is safe because each worker is a separate process (no shared memory)
- [ ] Worker pre-fork model: module-level `SESSION`, `ASYNC_SESSION`, `ASYNC_EXECUTOR` are correctly isolated per worker via `os.fork()`

### 1.2 psutil Process-Time Measurement
- [ ] `psutil.Process().cpu_times().user` correctly measures user-space CPU only
- [ ] Delta tracking via `_last_user_time` correctly isolates per-request CPU consumption
- [ ] Worker restart detection (`current_user < _last_user_time`) handles edge cases
- [ ] `time.process_time()` in the busy-wait loop is consistent with psutil measurements
- [ ] Mixing psutil `.user` (user-space only) with `time.process_time()` (user + system) - is this a measurement discrepancy?

### 1.3 ThreadPoolExecutor for Async Calls
- [ ] `max_workers=10` per Gunicorn worker - is this appropriate for fire-and-forget semantics?
- [ ] Thread pool is worker-isolated (created at module level, forked with worker)
- [ ] Dedicated `ASYNC_SESSION` prevents HTTP connection pool contention with main `SESSION`
- [ ] No future result collection (correct for LQN send-no-reply semantics)
- [ ] Thread pool exhaustion under high async call volume - what happens?

### 1.4 Flask Request Handling
- [ ] `jsonify()` response serialization overhead
- [ ] No request validation or input parsing (minimal overhead, by design)
- [ ] Global interpreter lock (GIL) impact on threaded workers vs process workers
- [ ] `requests.Session` thread safety when `GUNICORN_THREADS > 1`

---

## Phase 2: Gunicorn + Kubernetes Deployment

### 2.1 Sync Workers Per Pod
- [ ] Default `GUNICORN_WORKERS=2` - does this match typical K8s pod CPU allocation?
- [ ] Formula recommendation: workers = 2 * CPU_CORES + 1 (but in containers, CPU_CORES may be fractional)
- [ ] `multiprocessing.cpu_count()` inside containers reports host CPUs, not cgroup limits - does this affect Gunicorn auto-tuning?

### 2.2 CPU Limits and CFS Throttling
- [ ] Busy-wait loop will consume 100% of allocated CPU - does this trigger CFS throttling?
- [ ] Impact of `resources.limits.cpu` on busy-wait accuracy
- [ ] CFS quota period (typically 100ms) vs typical service times - granularity issues?
- [ ] Difference between `requests` and `limits` for CPU: how does this affect busy-wait calibration?

### 2.3 Resource Configuration
- [ ] Base deployment template lacks `resources.requests` and `resources.limits` - this will cause scheduling issues
- [ ] No `readinessProbe` or `livenessProbe` defined - K8s cannot detect unhealthy pods
- [ ] Missing `terminationGracePeriodSeconds` consideration for in-flight requests
- [ ] Container port 8080 is correctly exposed

### 2.4 Health Checks
- [ ] No `/health` or `/ready` endpoint exists in `app.py`
- [ ] Gunicorn workers may not be ready immediately after container start
- [ ] Startup probe needed for slow-starting workers under heavy `SERVICE_TIME_SECONDS`?

---

## Phase 3: Observability

### 3.1 Current State
- [ ] Only `print()` statements for logging - no structured logging
- [ ] No Prometheus metrics endpoint (`/metrics`)
- [ ] No request duration histograms
- [ ] No active request count gauge
- [ ] No error rate tracking

### 3.2 Improvement Opportunities
- [ ] Add `prometheus_flask_instrumentator` or `prometheus_client` for automatic metrics
- [ ] Expose request duration histogram (critical for LQN validation)
- [ ] Expose CPU time per request histogram (validates busy-wait accuracy)
- [ ] Track async call submission rate vs completion rate
- [ ] Gunicorn `statsd` integration for worker-level metrics

### 3.3 Logging
- [ ] Gunicorn access log is enabled (`--access-logfile -`)
- [ ] Application logs go to stdout (container-friendly)
- [ ] Log volume under high load - will `print()` statements cause I/O bottleneck?
- [ ] No log level configuration (all prints are unconditional)

---

## Phase 4: Service Time Calibration

### 4.1 Stochastic Distribution
- [ ] `np.random.exponential(mean_service_time)` correctly implements exponential distribution
- [ ] Mean parameter interpretation: `SERVICE_TIME_SECONDS` is the mean (1/lambda), not the rate
- [ ] No seed control - different workers/pods get different random streams (correct for simulation)
- [ ] Distribution choice (exponential) matches LQN Phase 1 service time assumptions

### 4.2 psutil Delta Tracking Accuracy
- [ ] First request after worker start: `_last_user_time=0.0`, `inherited_user = current_user - 0.0` accounts for Gunicorn/Flask startup CPU
- [ ] Under sequential requests: delta tracking should be accurate
- [ ] Under concurrent requests to same worker (threads > 1): `_last_user_time` race condition?
- [ ] Long idle periods between requests: does OS process accounting drift?

### 4.3 Busy-Wait Loop Calibration
- [ ] `time.process_time()` measures CPU time, not wall-clock time - correct for busy-wait
- [ ] Tight `while` loop with `pass` - does Python bytecode overhead add measurable error?
- [ ] Context switching during busy-wait: OS may preempt the process, but `process_time()` excludes that
- [ ] Inherited time subtraction: if previous request's downstream calls consumed CPU in threads, does this inflate `inherited_user`?
- [ ] Skip strategy (when `remaining <= 0`): effectively zero service time - does this skew the distribution?

---

## Phase 5: Scaling and Bottleneck Analysis

### 5.1 Horizontal Pod Autoscaler
- [ ] HPA configuration example exists in `kubernetes/examples/2-tier-hpa.yaml`
- [ ] CPU-based HPA will react to busy-wait CPU consumption (correct signal)
- [ ] Memory-based HPA: is memory usage stable or does it grow with request volume?
- [ ] Custom metrics HPA: could use Prometheus request rate for more accurate scaling

### 5.2 Bottleneck Identification
- [ ] Gunicorn worker count is the primary bottleneck knob (processor multiplicity)
- [ ] Pod replicas is the secondary bottleneck knob (task multiplicity)
- [ ] HTTP connection pool size (100) - is this sufficient for high fan-out topologies?
- [ ] `ThreadPoolExecutor` size (10) - async call backlog under high volume?
- [ ] Python GIL: irrelevant for sync workers (process-based), relevant if threads > 1

### 5.3 Service Mesh Overhead
- [ ] Istio/Linkerd sidecar proxy adds latency to every `SYNC` and `ASYNC` call
- [ ] Sidecar CPU overhead reduces available CPU for busy-wait
- [ ] mTLS handshake overhead on inter-service calls
- [ ] Impact on LQN model accuracy: sidecar overhead must be accounted for in service times

---

## Output Format

For each phase, produce:

```
PHASE X: [Name]
================
Item X.Y: [Description]
  Status: PASS | FAIL | NEEDS WORK
  Evidence: [file:line or explanation]
  Impact: LOW | MEDIUM | HIGH | CRITICAL
  Recommendation: [if not PASS]
```

Final summary:

```
PERFORMANCE AUDIT SUMMARY - GMT
================================
Phase 1 (Python):      X/Y items need attention
Phase 2 (K8s):         X/Y items need attention
Phase 3 (Observability): X/Y items need attention
Phase 4 (Calibration): X/Y items need attention
Phase 5 (Scaling):     X/Y items need attention

Critical Issues: [count]
High Impact:     [count]
Medium Impact:   [count]
Low Impact:      [count]

Top 3 Recommendations:
1. ...
2. ...
3. ...
```
