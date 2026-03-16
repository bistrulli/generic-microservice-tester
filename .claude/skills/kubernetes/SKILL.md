# Kubernetes Skill -- Generic Microservice Tester

## K8s Deployment Patterns for GMT

GMT uses a single Docker image deployed multiple times with different environment variable configurations to simulate complex microservice topologies. Each "microservice" in the topology is a separate Deployment + Service pair.

### Resource Pair Pattern

Every GMT service requires two K8s resources:

```yaml
# 1. Deployment -- runs the GMT container with specific configuration
apiVersion: apps/v1
kind: Deployment
metadata:
  name: <service>-deployment
spec:
  replicas: 1
  selector:
    matchLabels:
      app: <service>
  template:
    metadata:
      labels:
        app: <service>
    spec:
      containers:
      - name: app
        image: rpizziol/generic-microservice-tester:latest
        imagePullPolicy: Always
        ports:
        - containerPort: 8080
        env:
        - name: SERVICE_NAME
          value: "<service>"
        - name: SERVICE_TIME_SECONDS
          value: "<mean_seconds>"
        - name: OUTBOUND_CALLS
          value: "<TYPE:target-svc:prob,...>"
        - name: GUNICORN_WORKERS
          value: "<workers>"
        - name: GUNICORN_THREADS
          value: "1"
---
# 2. Service -- provides DNS-based discovery for other GMT instances
apiVersion: v1
kind: Service
metadata:
  name: <service>-svc
spec:
  selector:
    app: <service>        # Must match Deployment's pod label
  ports:
  - name: http
    protocol: TCP
    port: 80              # Other services connect to port 80
    targetPort: 8080      # GMT container listens on 8080
```

### Critical Naming Convention

The `name` in the K8s Service metadata determines how other GMT instances address this service in their `OUTBOUND_CALLS`. The service name in `OUTBOUND_CALLS` must exactly match the K8s Service `metadata.name`:

```yaml
# Service definition
metadata:
  name: backend-svc       # <-- This name

# Caller's OUTBOUND_CALLS references it
env:
- name: OUTBOUND_CALLS
  value: "SYNC:backend-svc:1.0"  # <-- Must match exactly
```

## Environment Variable Configuration

| Variable | Description | Constraints |
|---|---|---|
| `SERVICE_NAME` | Identifier returned in JSON response | Any string, for human readability |
| `SERVICE_TIME_SECONDS` | Mean CPU busy-wait time (exponential distribution) | Non-negative float. `0` = no CPU work |
| `OUTBOUND_CALLS` | Downstream call definitions | Comma-separated `TYPE:service:probability` |
| `GUNICORN_WORKERS` | Worker processes per pod | Positive integer. Maps to LQN task multiplicity |
| `GUNICORN_THREADS` | Threads per worker | Positive integer. Use `1` for accurate CPU timing |

### OUTBOUND_CALLS Semantics

```
TYPE:SERVICE_NAME:PROBABILITY[,TYPE:SERVICE_NAME:PROBABILITY,...]
```

- **SYNC**: Blocking HTTP GET. Caller's worker is occupied until response arrives.
- **ASYNC**: Non-blocking. Submitted to a per-worker thread pool. Caller continues immediately.
- **Probability = 1.0**: Call is always made. Multiple 1.0-probability calls are all executed.
- **Probability < 1.0**: Probabilistic routing. Exactly one is chosen per request using weighted random selection.

## Service Discovery (K8s DNS)

GMT relies entirely on K8s DNS for service discovery. When a GMT instance makes an outbound call to `backend-svc`, K8s DNS resolves this to the ClusterIP of the `backend-svc` Service, which load-balances across pods matched by the Service's selector.

```
GMT Container                  K8s DNS                    Target Pod
     |                           |                           |
     |-- GET http://backend-svc/ |                           |
     |                           |-- resolve backend-svc     |
     |                           |-- -> ClusterIP            |
     |-- TCP connect ClusterIP:80|                           |
     |                           |                           |
     |------------------------------------------- GET / ---->|
     |<------------------------------------------ 200 OK ----|
```

### DNS Resolution Details
- Service DNS: `<service-name>.<namespace>.svc.cluster.local`
- Short form works within the same namespace: `<service-name>`
- GMT uses short form: `http://<service-name>/` (port 80 is default for HTTP)
- K8s Service maps port 80 -> container port 8080

## HPA Configuration for Performance Testing

Horizontal Pod Autoscaler (HPA) enables automatic scaling based on metrics, which is essential for validating LQN model predictions under varying load.

### Basic CPU-Based HPA

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: <service>-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: <service>-deployment
  minReplicas: 1
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 50
```

### HPA Requirements
- Deployments must have `resources.requests.cpu` set for CPU-based HPA to function.
- Metrics Server must be installed in the cluster.
- HPA checks metrics every 15 seconds by default (configurable via `--horizontal-pod-autoscaler-sync-period`).

### HPA with Resource Requests

```yaml
containers:
- name: app
  image: rpizziol/generic-microservice-tester:latest
  resources:
    requests:
      cpu: "500m"       # Required for HPA percentage calculation
      memory: "128Mi"
    limits:
      cpu: "1000m"      # Maps to LQN processor multiplicity
      memory: "256Mi"
```

## Topology Examples

### 2-Tier (Entry -> Backend)

```
[Load Generator] --> [entry-svc] --SYNC--> [backend-svc]
```

File: `kubernetes/examples/2-tier-app.yaml`
- Entry: `SERVICE_TIME=0.1`, `OUTBOUND_CALLS="SYNC:backend-svc:1.0"`
- Backend: `SERVICE_TIME=0.1`, no outbound calls

### 3-Tier Chain (Entry -> Middle -> Backend)

```
[Load Generator] --> [entry-svc] --SYNC--> [middle-svc] --SYNC--> [backend-svc]
```

File: `kubernetes/examples/chain-app.yaml`
- Entry: `SERVICE_TIME=0.05`, calls `middle-svc`
- Middle: `SERVICE_TIME=0.1`, calls `backend-svc`
- Backend: `SERVICE_TIME=0.2`, leaf node

### Probabilistic Choice (Entry -> A | B)

```
[Load Generator] --> [entry-svc] --SYNC(0.5)--> [backend-a-svc]
                                  --SYNC(0.5)--> [backend-b-svc]
```

File: `kubernetes/examples/choice-app.yaml`
- Entry: `SERVICE_TIME=0.02`, `OUTBOUND_CALLS="SYNC:backend-a-svc:0.5,SYNC:backend-b-svc:0.5"`

### Fan-Out (Entry -> A + B + C)

```
[Load Generator] --> [entry-svc] --SYNC--> [svc-a]
                                  --SYNC--> [svc-b]
                                  --ASYNC-> [svc-c]
```

Configuration: `OUTBOUND_CALLS="SYNC:svc-a:1.0,SYNC:svc-b:1.0,ASYNC:svc-c:1.0"`
- All three calls are made every request.
- SYNC calls to svc-a and svc-b execute sequentially and block.
- ASYNC call to svc-c is fire-and-forget.

### Mixed Sync + Async

```
[Load Generator] --> [entry-svc] --SYNC--> [backend-svc]
                                  --ASYNC-> [logger-svc]
```

Configuration: `OUTBOUND_CALLS="SYNC:backend-svc:1.0,ASYNC:logger-svc:1.0"`

## Manifest Generation from LQN Models

When generating K8s manifests from an LQN model, follow this procedure:

### Step 1: Map Processors to Resource Limits
For each LQN processor, determine the CPU allocation:
```
P p_web  m=2  ->  resources.limits.cpu: "2000m"
```

### Step 2: Map Tasks to Deployments
For each LQN task, create a Deployment:
```
T web  p_web  m=4  ->  GUNICORN_WORKERS: "4", resources from p_web
```

### Step 3: Map Entries to Services
For each LQN entry, the K8s Service name becomes the addressable endpoint:
```
E e_web  web  0.05  ->  SERVICE_NAME: "web", SERVICE_TIME_SECONDS: "0.05"
                        K8s Service: metadata.name: "web-svc"
```

### Step 4: Map Calls to OUTBOUND_CALLS
For each call in the LQN model:
```
y(e_db)=1.0   ->  SYNC:database-svc:1.0
z(e_log)=1.0  ->  ASYNC:logger-svc:1.0
y(e_a)=0.6    ->  SYNC:svc-a:0.6
```

### Step 5: Generate HPA (Optional)
If the LQN model is being used for capacity planning, add HPAs for services that should autoscale.

## Resource Requests and Limits Best Practices

### For LQN-Accurate Deployments
- Set `requests == limits` for Guaranteed QoS. This matches LQN's assumption that each processor has a fixed capacity.
- CPU limits in millicores should reflect LQN processor multiplicity: `m=2` -> `2000m`.
- Memory: 128Mi is sufficient for most GMT workloads. Increase to 256Mi if using large `GUNICORN_WORKERS` values.

### For Performance Testing
- Always set `resources.requests.cpu` -- required for HPA and for meaningful `kubectl top` output.
- Use `resources.limits.cpu` to cap CPU, preventing noisy-neighbor effects.
- Monitor actual usage with `kubectl top pods` and adjust.

### Resource Sizing Guide

| GUNICORN_WORKERS | Recommended CPU Request | Recommended Memory |
|---|---|---|
| 1 | 250m | 128Mi |
| 2 | 500m | 128Mi |
| 4 | 1000m | 256Mi |
| 8 | 2000m | 256Mi |
| 16 | 4000m | 512Mi |

## Monitoring

### Prometheus Metrics
GMT does not export Prometheus metrics natively. Use a sidecar or service mesh for metrics:

```yaml
# Istio sidecar injection (if using Istio)
metadata:
  labels:
    app: <service>
  annotations:
    sidecar.istio.io/inject: "true"
```

Useful Prometheus queries for GMT workloads:
```promql
# Request rate per service
rate(istio_requests_total{destination_service_name="backend-svc"}[1m])

# P95 latency per service
histogram_quantile(0.95, rate(istio_request_duration_milliseconds_bucket{destination_service_name="entry-svc"}[1m]))

# CPU utilization per pod
rate(container_cpu_usage_seconds_total{pod=~"entry-deployment.*"}[1m])

# Memory usage per pod
container_memory_working_set_bytes{pod=~"backend-deployment.*"}
```

### Grafana Dashboards
Recommended panels for GMT topology monitoring:
1. **Request Rate**: per-service request throughput (req/s)
2. **Latency Distribution**: p50, p95, p99 per service
3. **Error Rate**: 4xx and 5xx responses per service
4. **CPU Utilization**: per-pod CPU usage vs. limits
5. **Pod Count**: current replicas per deployment (shows HPA activity)
6. **Network Traffic**: inter-service bytes transferred

### kubectl Monitoring Commands

```bash
# Pod status
kubectl get pods -l app=<service> -o wide

# Resource usage (requires metrics-server)
kubectl top pods

# Recent events (useful for debugging scaling)
kubectl get events --sort-by=.metadata.creationTimestamp | tail -20

# Pod logs
kubectl logs deployment/<service>-deployment --tail=50

# Describe pod (for troubleshooting)
kubectl describe pod -l app=<service>

# HPA status
kubectl get hpa

# Detailed HPA status
kubectl describe hpa <service>-hpa
```

## Load Testing Patterns

### Using k6

```javascript
// k6-script.js
import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  stages: [
    { duration: '30s', target: 10 },   // Ramp up
    { duration: '60s', target: 10 },   // Steady state
    { duration: '30s', target: 0 },    // Ramp down
  ],
};

export default function () {
  const res = http.get('http://entry-svc/');
  check(res, {
    'status is 200': (r) => r.status === 200,
    'has message': (r) => r.json().message !== undefined,
  });
}
```

```bash
# Run from within the cluster (e.g., in a k6 pod)
k6 run k6-script.js
```

### Using locust

```python
# locustfile.py
from locust import HttpUser, task, between

class GMTUser(HttpUser):
    wait_time = between(0.1, 0.5)
    host = "http://entry-svc"

    @task
    def hit_entry(self):
        self.client.get("/")
```

```bash
# Run from within the cluster
locust -f locustfile.py --headless --users 50 --spawn-rate 5 --run-time 120s
```

### Using hey (simple HTTP load generator)

```bash
# 100 requests, 10 concurrent
hey -n 100 -c 10 http://entry-svc/

# Sustained load for 60 seconds, 20 concurrent
hey -z 60s -c 20 http://entry-svc/

# Fixed rate: 50 req/s for 60 seconds
hey -z 60s -q 50 -c 50 http://entry-svc/
```

### Load Test from Outside the Cluster

If the entry service is not exposed externally, use port-forwarding:

```bash
# Forward local port 8080 to entry service
kubectl port-forward svc/entry-svc 8080:80 &

# Run load test against localhost
hey -z 60s -c 10 http://localhost:8080/

# Or expose via NodePort/LoadBalancer for production-like testing
```

## Troubleshooting

| Symptom | Diagnosis | Fix |
|---|---|---|
| Pod stuck in `Pending` | `kubectl describe pod` -- check events | Insufficient cluster resources. Reduce `resources.requests` or add nodes |
| Pod in `CrashLoopBackOff` | `kubectl logs <pod>` -- check error | Usually entrypoint issue. Verify image and env vars |
| Service not resolving | `kubectl exec <pod> -- nslookup <svc>` | Check Service `metadata.name` matches OUTBOUND_CALLS target |
| Connection refused between services | Check targetPort matches containerPort (8080) | Verify Service `targetPort: 8080` and container `containerPort: 8080` |
| HPA not scaling | `kubectl describe hpa` -- check conditions | Ensure `resources.requests.cpu` is set and metrics-server is installed |
| High latency under load | `kubectl top pods` -- check CPU | Increase `GUNICORN_WORKERS` or CPU limits |
| Async calls failing silently | Check pod logs for `[ASYNC-POOL-*]` messages | Verify target service exists and is reachable |
| Image pull errors | `kubectl describe pod` -- check events | Verify image name, tag, and `imagePullPolicy` |
