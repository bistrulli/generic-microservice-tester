import os
import random
import requests
from requests.adapters import HTTPAdapter
import time
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, jsonify
import numpy as np

app = Flask(__name__)

# --- Worker-Isolated Resource Management ---
# Each Gunicorn worker gets its own isolated resources to prevent cross-worker interference

# Main session for synchronous calls (per worker)
SESSION = requests.Session()
adapter = HTTPAdapter(pool_connections=100, pool_maxsize=100)  # Large pool for sync calls
SESSION.mount('http://', adapter)
SESSION.mount('https://', adapter)

# Dedicated session for asynchronous calls (completely isolated)
ASYNC_SESSION = requests.Session()
async_adapter = HTTPAdapter(
    pool_connections=100,   # Large pool for async calls
    pool_maxsize=100,
    max_retries=0          # No retries for pure async semantics
)
ASYNC_SESSION.mount('http://', async_adapter)
ASYNC_SESSION.mount('https://', async_adapter)

# Worker-isolated thread pool for async calls
# Increased capacity for better throughput while maintaining worker isolation
ASYNC_EXECUTOR = ThreadPoolExecutor(
    max_workers=10,  # More threads per worker for higher async throughput
    thread_name_prefix=f"async-worker-{os.getpid()}"
)


# --- Configuration Section ---
# The behavior of this microservice is controlled by environment variables.
#
# SERVICE_NAME: A friendly name for this instance (e.g., "frontend", "backend-a").
#
# SERVICE_TIME_SECONDS: Simulates a precise amount of CPU time consumption using a busy-wait.
#                       Example: "0.1" for 100ms of CPU time.
#
# OUTBOUND_CALLS: Defines downstream HTTP calls.
#                 Format: "TYPE:service_name:probability,TYPE:service_name:probability,..."
#                 Example: "SYNC:backend-a:0.6,SYNC:backend-b:0.4,ASYNC:logger-svc:1.0"

# --- Process-based CPU Timing with Delta Tracking ---
# Global state for tracking CPU time between requests within the same worker process
_last_user_time = 0.0

def do_work():
    """Simulates CPU-intensive work using precise per-request user CPU time tracking.

    Uses delta tracking to measure only the CPU time consumed by this specific request,
    accounting for the fact that worker processes are persistent and accumulate CPU time
    across multiple requests.

    This implementation:
    - Measures only user-space CPU time (excludes system time)
    - Uses delta tracking to isolate per-request CPU consumption
    - Handles worker process restarts automatically
    - Implements skip strategy when inherited CPU time exceeds target
    """
    global _last_user_time

    try:
        import psutil
        service_time_str = os.environ.get('SERVICE_TIME_SECONDS', '0')
        mean_service_time = float(service_time_str)

        if mean_service_time <= 0:
            return

        # Sample from exponential distribution with specified mean
        service_time = np.random.exponential(mean_service_time)

        # Get current user CPU time of the worker process
        process = psutil.Process()
        current_user = process.cpu_times().user

        # Worker process restart detection
        if current_user < _last_user_time:
            print(f"Worker restart detected: current={current_user:.4f}s, last={_last_user_time:.4f}s")
            _last_user_time = 0.0

        # Calculate inherited CPU time from previous requests in this worker
        inherited_user = current_user - _last_user_time

        # How much additional work do we need to do for this request?
        remaining = service_time - inherited_user

        print(f"CPU timing: mean={mean_service_time:.4f}s, sampled={service_time:.4f}s, inherited={inherited_user:.4f}s, remaining={remaining:.4f}s")

        if remaining > 0:
            # Standard busy-wait for remaining CPU time
            start_busy = time.process_time()
            while (time.process_time() - start_busy) < remaining:
                pass  # Busy computation loop

            print(f"Completed busy-wait for {remaining:.4f}s")
        else:
            # Skip strategy: request completed without additional work
            print(f"Request completed without additional work (excess: {abs(remaining):.4f}s)")

        # Update tracking for next request
        _last_user_time = process.cpu_times().user

    except ImportError as e:
        raise RuntimeError("psutil library not available - required for container-aware CPU timing") from e
    except (ValueError, TypeError) as e:
        raise RuntimeError(f"Invalid SERVICE_TIME_SECONDS value: {service_time_str}") from e
    except Exception as e:
        raise RuntimeError(f"Process-based CPU timing failed: {e}") from e


def parse_outbound_calls():
    """Reads and parses the OUTBOUND_CALLS environment variable."""
    config_str = os.environ.get('OUTBOUND_CALLS', '')
    if not config_str:
        return [], []

    targets = []
    call_defs = config_str.split(',')
    for call_def in call_defs:
        try:
            call_type, service_name, prob_str = call_def.strip().split(':')
            probability = float(prob_str)
            targets.append({
                "type": call_type.upper(),
                "service": service_name,
                "probability": probability
            })
        except ValueError:
            print(f"Skipping malformed call definition: {call_def}")

    # Separate probabilistic calls from fixed calls (which are always executed)
    probabilistic_targets = [t for t in targets if t['probability'] < 1.0]
    fixed_targets = [t for t in targets if t['probability'] >= 1.0]

    return probabilistic_targets, fixed_targets

def make_call(target):
    """Executes a single HTTP GET request using the shared Session object."""
    service_name = target['service']
    # Kubernetes DNS resolves the service name to its internal IP address
    url = f"http://{service_name}"
    try:
        # Use the shared SESSION object to make the request
        response = SESSION.get(url, timeout=300)
        print(f"Called {url}, status: {response.status_code}")
        return {"service": service_name, "status": response.status_code}
    except requests.exceptions.RequestException as e:
        print(f"Failed to call {url}: {e}")
        return {"service": service_name, "status": "error", "reason": str(e)}


def make_async_call_pooled(target):
    """
    Executes asynchronous HTTP calls using worker-isolated thread pool.

    This function implements LQN-semantic compliant "send-no-reply" behavior by:
    1. Using a dedicated thread pool isolated per Gunicorn worker
    2. Using a separate HTTP session for async calls (no resource contention)
    3. Limiting concurrent async threads to prevent worker saturation
    4. Ensuring true fire-and-forget semantics as per LQN 'z' calls

    Args:
        target (dict): Target configuration with 'service' field

    Returns:
        None: Fire-and-forget, no blocking or waiting
    """
    service_name = target['service']
    url = f"http://{service_name}"

    def _async_worker():
        """Worker function executed in isolated thread"""
        try:
            # Use dedicated async session (isolated from main session)
            response = ASYNC_SESSION.get(url, timeout=300)
            print(f"[ASYNC-POOL-{os.getpid()}] {url} -> {response.status_code}")
        except requests.exceptions.RequestException as e:
            print(f"[ASYNC-POOL-{os.getpid()}] {url} -> ERROR: {e}")
        except Exception as e:
            print(f"[ASYNC-POOL-{os.getpid()}] {url} -> UNEXPECTED: {e}")

    try:
        # Submit to worker-isolated thread pool - non-blocking
        future = ASYNC_EXECUTOR.submit(_async_worker)
        print(f"Async call submitted to worker-{os.getpid()} pool: {url}")

        # Optional: We could store futures for monitoring, but for LQN semantics we ignore them

    except Exception as e:
        # Log the submission failure, but don't affect main process
        print(f"Failed to submit async call to pool: {url} -> {e}")


@app.route('/')
def handle_request():
    """Main endpoint to handle incoming requests."""
    my_name = os.environ.get('SERVICE_NAME', 'generic-service')

    # 1. Simulate the service's own workload first
    do_work()

    # 2. Parse the downstream call configuration
    probabilistic_targets, fixed_targets = parse_outbound_calls()
    results = []

    # 3. Execute all fixed calls (probability >= 1.0)
    for target in fixed_targets:
        if target['type'] == 'SYNC':
            results.append(make_call(target))
        elif target['type'] == 'ASYNC':
            # Submit to worker-isolated thread pool (LQN-semantic compliant)
            make_async_call_pooled(target)
            results.append({"service": target['service'], "status": "async_pooled"})

    # 4. Choose and execute one of the probabilistic calls
    if probabilistic_targets:
        services = [t['service'] for t in probabilistic_targets]
        weights = [t['probability'] for t in probabilistic_targets]
        chosen_service_name = random.choices(services, weights=weights, k=1)[0]
        chosen_target = next(t for t in probabilistic_targets if t['service'] == chosen_service_name)

        # Handle both SYNC and ASYNC types correctly for probabilistic calls
        if chosen_target['type'] == 'SYNC':
            results.append(make_call(chosen_target))
        elif chosen_target['type'] == 'ASYNC':
            # Submit to worker-isolated thread pool (LQN-semantic compliant)
            make_async_call_pooled(chosen_target)
            results.append({"service": chosen_target['service'], "status": "async_pooled"})

    return jsonify({"message": f"Response from {my_name}", "outbound_results": results})

