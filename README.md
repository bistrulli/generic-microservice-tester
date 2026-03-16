# Generic Microservice Tester

A highly configurable, single-image microservice designed to simulate complex application topologies on Kubernetes for testing and performance analysis. This project was created to provide a flexible "test harness" for experimenting with service meshes, auto-scalers, and monitoring tools without writing custom application code.

## Core Concept

Instead of writing multiple applications to test a distributed system, you can deploy this single Docker image multiple times with different runtime configurations. The behavior of each microservice instance is controlled entirely by environment variables defined in your Kubernetes deployment manifests.

This allows you to rapidly prototype and benchmark sophisticated service chains, fan-out architectures, or any other topology, making it the perfect tool for experimenting with:

- Service meshes like Istio or Linkerd.
- The Kubernetes Horizontal Pod Autoscaler (HPA).
- Monitoring and observability platforms like Prometheus and Grafana.

## Repository Structure

The project is organized into three main directories to keep the source code, container configuration, and Kubernetes manifests separate and clean.

```
/
├── src/            # Application source code (Python/Flask)
├── docker/         # Docker-related files (Dockerfile, entrypoint script)
└── kubernetes/     # Kubernetes YAML manifests
```

- `/src`: Contains the core Python application (`app.py`) built with Flask and its dependencies (`requirements.txt`).
- `/docker`: Contains the `Dockerfile` used to build the container image and the `entrypoint.sh` script that starts the Gunicorn server.
- `/kubernetes`: Contains all YAML manifests.
  - `/base`: A generic template for deploying a single instance of the service.
  - `/examples`: Ready-to-use examples of complex topologies (e.g., 2-tier, probabilistic routing).

## How to Use It: Creating Your Own Topology

The real power of this project is defining your own service architecture directly in YAML. Let's create a 3-service chain (`entry -> middle -> backend`) as an example.

### Step 1: Create a New Manifest File

Create a new file, for instance `kubernetes/examples/chain-app.yaml`.

### Step 2: Define the backend Service

This service is the last in the chain, so it doesn't call any other services.

```yaml
# In chain-app.yaml

apiVersion: apps/v1
kind: Deployment
metadata:
  name: backend-deployment
spec:
  # ... boilerplate ...
  template:
    # ... boilerplate ...
    spec:
      containers:
      - name: app
        image: rpizziol/generic-microservice-tester:latest # Your image
        env:
        - name: SERVICE_NAME
          value: "backend"
        - name: SERVICE_TIME_SECONDS
          value: "0.2" # Simulate 200ms of work
        - name: OUTBOUND_CALLS
          value: "" # <-- KEY: This service calls no others
---
apiVersion: v1
kind: Service
metadata:
  name: backend-svc
# ... boilerplate ...
```

### Step 3: Define the middle Service

This service will be configured to make a single, synchronous call to our `backend-svc`.

```yaml
# In chain-app.yaml, after the backend service

apiVersion: apps/v1
kind: Deployment
metadata:
  name: middle-deployment
spec:
  # ... boilerplate ...
  template:
    # ... boilerplate ...
    spec:
      containers:
      - name: app
        image: rpizziol/generic-microservice-tester:latest
        env:
        - name: SERVICE_NAME
          value: "middle"
        - name: SERVICE_TIME_SECONDS
          value: "0.1" # Simulate 100ms of work
        - name: OUTBOUND_CALLS
          value: "SYNC:backend-svc:1.0" # <-- KEY: Always calls backend-svc
---
apiVersion: v1
kind: Service
metadata:
  name: middle-svc
# ... boilerplate ...
```

### Step 4: Define the entry Service

Finally, the entrypoint service will call the `middle-svc`. This is the service you will point your Istio Gateway to.

```yaml
# In chain-app.yaml, after the middle service

apiVersion: apps/v1
kind: Deployment
metadata:
  name: entry-deployment
spec:
  # ... boilerplate ...
  template:
    # ... boilerplate ...
    spec:
      containers:
      - name: app
        image: rpizziol/generic-microservice-tester:latest
        env:
        - name: SERVICE_NAME
          value: "entry"
        - name: SERVICE_TIME_SECONDS
          value: "0.05" # Simulate 50ms of work
        - name: OUTBOUND_CALLS
          value: "SYNC:middle-svc:1.0" # <-- KEY: Always calls middle-svc
---
apiVersion: v1
kind: Service
metadata:
  name: entry-svc
# ... boilerplate ...
```

By applying this single file, you have just created a 3-tier application without writing a single line of application code!

## Configuration Details (Environment Variables)

| Variable             | Description                                                             | Format / Example                                                   |
|-----------------------|------------------------------------------------------------------------|----------------------------------------------------------------------|
| `SERVICE_NAME`        | A friendly name for the service instance, returned in the JSON response. | `frontend-service`                                                  |
| `SERVICE_TIME_SECONDS`| **Mean** of exponential distribution for CPU work simulation. Each request samples a random service time from an exponential distribution with this mean. Provides realistic stochastic behavior. | `0.2` (mean 200ms, actual times vary) |
| `GUNICORN_WORKERS`    | The number of Gunicorn worker processes to spawn. A good starting point is (2 * number of cores) + 1. | `2` |
| `GUNICORN_THREADS`    | The number of threads per worker. Useful for I/O-bound tasks. | `4` |
| `OUTBOUND_CALLS`      | A comma-separated list defining the outbound HTTP calls to make upon receiving a request. | `TYPE:service_name:probability` |

## OUTBOUND_CALLS Format Explained

Each call is a colon-separated string: `TYPE:SERVICE_NAME:PROBABILITY`.

- **TYPE**: Can be `SYNC` (blocking call) or `ASYNC` (non-blocking call).
- **SERVICE_NAME**: The Kubernetes service name to call (e.g., `backend-svc`).
- **PROBABILITY**:
  - `1.0`: The call is always made. Multiple calls with 1.0 will all be executed.
  - `< 1.0`: The call is probabilistic. If multiple calls have a probability less than 1.0, only one will be chosen randomly based on their relative weights.

**Example:**

```yaml
value: "SYNC:backend-a:0.6,SYNC:backend-b:0.4,ASYNC:logger-svc:1.0"
```

This configuration will:

- Always send an asynchronous, non-blocking call to `logger-svc`.
- Then, make a single synchronous, blocking call to either `backend-a` (60% chance) or `backend-b` (40% chance).

## Stochastic Service Time Modeling

This microservice implements **realistic stochastic service times** using exponential distribution to better simulate real-world microservice behavior.

### Service Time Behavior

- **Exponential Distribution**: Each request samples CPU work time from an exponential distribution
- **Mean Parameter**: `SERVICE_TIME_SECONDS` specifies the mean (λ⁻¹) of the exponential distribution
- **Realistic Variability**: Service times vary naturally - some requests complete quickly, others take longer
- **Mathematical Accuracy**: Follows exponential distribution properties (memoryless, heavy tail)

### Example Behavior

```yaml
env:
- name: SERVICE_TIME_SECONDS
  value: "0.2"  # Mean service time of 200ms
```

**Sample outputs:**
- Request 1: 0.05s (fast completion)
- Request 2: 0.18s (near mean)
- Request 3: 0.73s (long tail event)
- Request 4: 0.12s (typical)

This provides more realistic load patterns for testing autoscalers, monitoring systems, and performance analysis.

## LQN-Semantic Compliance for Asynchronous Calls

This microservice implements **LQN (Layered Queueing Network) semantic compliance** for asynchronous calls to support accurate performance modeling and prediction.

### Key Features

- **Process Isolation**: Asynchronous calls (`ASYNC` type) are executed in completely separate processes
- **Zero Interference**: Async calls do not compete for CPU, memory, or HTTP connection resources with the main service
- **True "Send-No-Reply"**: Implements genuine fire-and-forget semantics as defined in LQN theory
- **Accurate Metrics**: CPU timing and throughput measurements exclude async call overhead

### Technical Implementation

- **Main Process**: Handles synchronous calls and core service logic using shared HTTP session
- **Isolated Processes**: Each async call spawns a separate Python process with independent resources
- **No Blocking**: The main process continues immediately after delegating async calls
- **Resource Separation**: Async processes use dedicated HTTP sessions and connection pools

### Response Status Codes

- **Synchronous calls**: Return actual HTTP status codes (e.g., `200`, `404`, `500`)
- **Asynchronous calls**: Return `"async_delegated"` to indicate successful delegation to isolated process

This architecture ensures that performance measurements and LQN model predictions align accurately with real-world behavior.

## Author
Roberto Pizziol

## License
This project is released under the MIT License.
