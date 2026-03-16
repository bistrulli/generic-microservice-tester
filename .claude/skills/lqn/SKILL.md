# LQN Modeling Skill -- Generic Microservice Tester

## LQN Fundamentals

Layered Queueing Networks (LQN) are an extension of queueing networks designed for modeling software with nested resource contention -- where a server at one layer becomes a client at another layer.

### Core Concepts

| LQN Element | Definition | GMT Mapping |
|---|---|---|
| **Processor** | Hardware resource (CPU). Has multiplicity (cores) and scheduling discipline. | Pod resource limits (`resources.limits.cpu`) |
| **Task** | Software entity deployed on a processor. Has multiplicity (threads/processes). | Deployment with `GUNICORN_WORKERS` |
| **Entry** | Named service interface on a task. Receives requests. | `SERVICE_NAME` + HTTP path (`/`) |
| **Activity** | Unit of work within an entry. Has service time demand. | `SERVICE_TIME_SECONDS` (exponential distribution) |
| **Sync Call (y)** | Blocking request-reply. Caller waits for response. | `OUTBOUND_CALLS` with `SYNC:target:probability` |
| **Async Call (z)** | Fire-and-forget. Caller continues immediately. | `OUTBOUND_CALLS` with `ASYNC:target:probability` |
| **Forwarding Call (F)** | Request passed to next layer; original caller waits for final reply. | Not implemented in GMT |
| **Open Workload** | External arrival process (Poisson). | External load generator (locust, k6, etc.) |
| **Closed Workload** | Fixed population of circulating customers. | Fixed concurrency load generator |

### LQN Layering

```
[Clients / Open Workload]
        |
        v  (sync call)
  [Entry Task]          <-- Layer 1: receives external requests
        |
        v  (sync call)
  [Middle Task]         <-- Layer 2: intermediate processing
        |
        v  (sync call)
  [Backend Task]        <-- Layer 3: leaf service
```

Each layer introduces **nested resource contention**: a task waiting for a downstream reply still holds its own processor. This is the key phenomenon LQN captures that basic queueing models miss.

## The 9 Fundamental LQN Patterns

### Pattern 1: Single Task (Baseline)
One task on one processor. No downstream calls.
```
P processor  m=1
T task       processor  m=1
E entry      task       0.1
```
**GMT**: Single deployment, `SERVICE_TIME_SECONDS=0.1`, no `OUTBOUND_CALLS`.

### Pattern 2: Two-Tier Sync Chain
Client task makes a synchronous call to a server task.
```
P p_client   m=1
P p_server   m=1
T client     p_client   m=1
T server     p_server   m=1
E e_client   client     0.05   y(e_server)=1.0
E e_server   server     0.1
```
**GMT**: `OUTBOUND_CALLS="SYNC:server-svc:1.0"`.

### Pattern 3: N-Tier Chain
Sequential chain of synchronous calls through N layers.
```
E e_entry    entry_task    0.05   y(e_middle)=1.0
E e_middle   middle_task   0.1    y(e_backend)=1.0
E e_backend  backend_task  0.2
```
**GMT**: Each service calls the next via `SYNC:next-svc:1.0`. See `kubernetes/examples/chain-app.yaml`.

### Pattern 4: Fan-Out (Parallel Sync)
One task makes synchronous calls to multiple downstream tasks. All calls with probability 1.0 are executed sequentially.
```
E e_entry    entry_task    0.05   y(e_svc_a)=1.0  y(e_svc_b)=1.0
```
**GMT**: `OUTBOUND_CALLS="SYNC:svc-a:1.0,SYNC:svc-b:1.0"`. Note: GMT executes these sequentially, not in parallel.

### Pattern 5: Probabilistic Routing (Choice)
One task routes requests to one of several downstream tasks based on probability.
```
E e_entry    entry_task    0.02   y(e_backend_a)=0.6  y(e_backend_b)=0.4
```
**GMT**: `OUTBOUND_CALLS="SYNC:backend-a-svc:0.6,SYNC:backend-b-svc:0.4"`. See `kubernetes/examples/choice-app.yaml`.

### Pattern 6: Async Fire-and-Forget
One task sends an asynchronous message without waiting for a reply (LQN 'z' call).
```
E e_entry    entry_task    0.1    z(e_logger)=1.0
```
**GMT**: `OUTBOUND_CALLS="ASYNC:logger-svc:1.0"`. Implemented via worker-isolated thread pool.

### Pattern 7: Mixed Sync + Async
One task makes both synchronous and asynchronous calls.
```
E e_entry    entry_task    0.05   y(e_backend)=1.0  z(e_logger)=1.0
```
**GMT**: `OUTBOUND_CALLS="SYNC:backend-svc:1.0,ASYNC:logger-svc:1.0"`. Async calls are submitted to the thread pool and do not block the main request processing.

### Pattern 8: Multi-Entry Task
One task exposes multiple entries (different service interfaces). Each entry may have different service times and call patterns.
**GMT limitation**: Each GMT instance has a single entry point (`/`). To model multi-entry tasks, deploy multiple GMT instances on the same node with different `SERVICE_NAME` values.

### Pattern 9: Infinite Server (Delay)
A task with infinite multiplicity -- no queueing, pure delay.
```
T delay_task  p_delay  m=inf
```
**GMT**: Approximate with very high `GUNICORN_WORKERS` and `GUNICORN_THREADS` values so no request ever waits for a thread.

## .lqn File Format Reference

### Processors
```
P <name>                        # Processor declaration
  s <discipline>                # Scheduling: f=FCFS, ps=PS, inf=infinite
  m <multiplicity>              # Number of cores
```

### Tasks
```
T <name>  <processor>           # Task on a processor
  s <discipline>                # Scheduling: n=non-ref, r=ref
  m <multiplicity>              # Number of threads/workers
  z <think_time>                # Think time (reference tasks only)
```

### Entries
```
E <name>  <task>  <service_time>
  y <target_entry> <mean_calls>  # Synchronous call
  z <target_entry> <mean_calls>  # Asynchronous call
  F <target_entry> <probability> # Forwarding call
```

### Workloads
```
# Open workload (Poisson arrivals)
W <entry>  <arrival_rate>

# Closed workload (reference task)
T <ref_task>  <processor>  r  m=<population>  z=<think_time>
```

## LQN-to-K8s Compilation Mapping

This is the critical mapping that makes GMT a "compilation target" for LQN models. Each LQN element translates directly to a GMT/K8s configuration.

### Processor -> Pod Resource Limits

```yaml
# LQN: P webserver  m=2  s=ps
resources:
  requests:
    cpu: "2000m"      # m=2 cores
  limits:
    cpu: "2000m"      # Hard limit matches multiplicity
```

The processor multiplicity maps to CPU cores. Scheduling discipline maps to K8s QoS:
- `s=f` (FCFS) -> Guaranteed QoS (requests == limits)
- `s=ps` (Processor Sharing) -> Guaranteed QoS (requests == limits), standard Linux CFS scheduler provides PS semantics
- `s=inf` (Infinite) -> No CPU limits (BestEffort or Burstable QoS)

### Task -> Deployment with GUNICORN_WORKERS

```yaml
# LQN: T app  webserver  m=4
env:
- name: GUNICORN_WORKERS
  value: "4"          # Task multiplicity = worker count
- name: GUNICORN_THREADS
  value: "1"          # Keep 1 for accurate CPU measurement
spec:
  replicas: 1         # Single replica per LQN task instance
```

Task multiplicity maps to `GUNICORN_WORKERS`. Each worker is an independent process with its own CPU time tracking, matching LQN's thread pool semantics.

### Entry -> SERVICE_NAME + HTTP Path

```yaml
# LQN: E handle_request  app  0.1
env:
- name: SERVICE_NAME
  value: "app"        # Entry name for identification
```

GMT exposes a single entry per instance on path `/`. The K8s Service name determines how other tasks address this entry.

### Activity -> SERVICE_TIME_SECONDS

```yaml
# LQN: Activity a1  0.1   (exponential service time, mean=0.1s)
env:
- name: SERVICE_TIME_SECONDS
  value: "0.1"        # Mean of exponential distribution
```

GMT samples from an exponential distribution with the specified mean, matching the standard LQN assumption of exponentially distributed service times. The psutil-based implementation uses delta tracking to measure actual per-request CPU consumption.

### Sync Call -> OUTBOUND_CALLS SYNC

```yaml
# LQN: y(e_backend) = 1.0
env:
- name: OUTBOUND_CALLS
  value: "SYNC:backend-svc:1.0"
```

Synchronous calls block the calling worker until a response is received. Multiple SYNC calls with probability 1.0 are executed sequentially. Probabilistic SYNC calls (probability < 1.0) are mutually exclusive -- exactly one is chosen per request using weighted random selection.

### Async Call -> OUTBOUND_CALLS ASYNC

```yaml
# LQN: z(e_logger) = 1.0
env:
- name: OUTBOUND_CALLS
  value: "ASYNC:logger-svc:1.0"
```

Asynchronous calls are submitted to a per-worker thread pool (`ASYNC_EXECUTOR`) and execute without blocking the main request. This matches LQN 'z' call (send-no-reply) semantics. The async calls use a dedicated HTTP session (`ASYNC_SESSION`) isolated from the main session.

### Open Workload -> External Load Generator

```
# LQN: W e_entry  10.0   (10 requests/second, Poisson)
```

Open workloads are modeled by external load generators pointed at the entry service:

```bash
# Using k6
k6 run --vus 10 --duration 60s script.js

# Using locust
locust --host=http://entry-svc --users=10 --spawn-rate=2

# Using hey
hey -q 10 -z 60s http://entry-svc/
```

The load generator is not part of the GMT deployment -- it runs externally and drives traffic into the entry service.

## Complete Compilation Example

### LQN Model
```
# 2-tier web application
P p_web     m=2  s=ps
P p_db      m=4  s=ps

T web       p_web    m=4
T database  p_db     m=8

E e_web     web      0.05   y(e_db)=1.0
E e_db      database 0.02

W e_web  20.0
```

### Compiled K8s Manifest
```yaml
# web task
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web-deployment
spec:
  replicas: 1
  template:
    spec:
      containers:
      - name: app
        image: rpizziol/generic-microservice-tester:latest
        resources:
          requests:
            cpu: "2000m"    # P p_web m=2
          limits:
            cpu: "2000m"
        env:
        - name: SERVICE_NAME
          value: "web"
        - name: SERVICE_TIME_SECONDS
          value: "0.05"     # E e_web service time
        - name: OUTBOUND_CALLS
          value: "SYNC:database-svc:1.0"  # y(e_db)=1.0
        - name: GUNICORN_WORKERS
          value: "4"        # T web m=4
        - name: GUNICORN_THREADS
          value: "1"
---
# database task
apiVersion: apps/v1
kind: Deployment
metadata:
  name: database-deployment
spec:
  replicas: 1
  template:
    spec:
      containers:
      - name: app
        image: rpizziol/generic-microservice-tester:latest
        resources:
          requests:
            cpu: "4000m"    # P p_db m=4
          limits:
            cpu: "4000m"
        env:
        - name: SERVICE_NAME
          value: "database"
        - name: SERVICE_TIME_SECONDS
          value: "0.02"     # E e_db service time
        - name: OUTBOUND_CALLS
          value: ""         # Leaf task
        - name: GUNICORN_WORKERS
          value: "8"        # T database m=8
        - name: GUNICORN_THREADS
          value: "1"
```

## LQN V5 Solver

The LQN V5 analytical solver (`lqns`) computes steady-state performance metrics from an LQN model:

- **Throughput**: requests per second processed by each entry.
- **Utilization**: fraction of time each processor/task is busy.
- **Service Time**: mean response time at each entry (includes downstream wait time).
- **Waiting Time**: mean time spent waiting for a downstream resource.
- **Queue Length**: mean number of requests waiting at each task.

### Solver Invocation
```bash
lqns model.lqn              # Solve with default parameters
lqns -P model.lqn           # Generate parseable output
lqns -o output.lqn model.lqn  # Write results to file
```

### Solver Output Interpretation
Compare solver predictions against GMT measurements:
- Predicted throughput vs. measured throughput (from load test)
- Predicted utilization vs. measured CPU utilization (from `kubectl top pods` or Prometheus)
- Predicted response time vs. measured latency (from load test p50/mean)

## Key References

1. Franks, G., et al. "Layered Queueing Network Software (V5)." User Manual, Carleton University.
2. Rolia, J. A., and K. C. Sevcik. "The Method of Layers." IEEE Transactions on Software Engineering, 1995.
3. Woodside, C. M., J. E. Neilson, D. C. Petriu, and S. Majumdar. "The Stochastic Rendezvous Network Model for Performance of Synchronous Client-Server-like Distributed Software." IEEE Transactions on Computers, 1995.
4. Franks, G., T. Al-Omari, M. Woodside, O. Das, and S. Derisavi. "Enhanced Modeling and Solution of Layered Queueing Networks." IEEE Transactions on Software Engineering, 2009.
