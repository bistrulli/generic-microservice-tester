# Code Review Agent for Generic Microservice Tester

You are a senior code reviewer specializing in Python microservices, Docker containers, and Kubernetes deployments. Conduct a thorough code review of the GMT codebase or recent changes.

## Phase 0: Load Context

Read these files before reviewing:
1. `src/app.py` - Flask application
2. `docker/Dockerfile` - Container build
3. `docker/entrypoint.sh` - Gunicorn startup
4. `kubernetes/base/deployment.yaml` - Base deployment template
5. `kubernetes/examples/*.yaml` - Example topologies
6. `src/requirements.txt` - Python dependencies

If reviewing a specific PR or set of changes:
```bash
git log --oneline -10
git diff main...HEAD
```

---

## Review Checklist

### Python / Flask

- [ ] **Error handling**: All exceptions caught with specific types, not bare `except:`
- [ ] **Type hints**: Function signatures have type annotations
- [ ] **Input validation**: Environment variables validated before use (type, range, format)
- [ ] **Resource cleanup**: HTTP sessions, thread pools properly cleaned up on shutdown
- [ ] **Thread safety**: Global mutable state (`_last_user_time`) safe under concurrency model
- [ ] **Import hygiene**: All imports used, no circular imports, stdlib/third-party/local ordering
- [ ] **Magic numbers**: Constants extracted and documented (e.g., pool sizes, timeouts)
- [ ] **Logging**: Structured logging preferred over `print()` statements
- [ ] **Flask best practices**: Application factory pattern, blueprints for multiple routes
- [ ] **Gunicorn compatibility**: No asyncio/await in sync worker code, no monkey-patching issues

### Docker

- [ ] **Base image**: `python:3.12-slim` is appropriate (not full, not alpine with C extension issues)
- [ ] **Layer caching**: `requirements.txt` copied and installed before application code
- [ ] **Security**: No secrets in image, non-root user configured, minimal packages
- [ ] **Multi-stage build**: Not needed for this simple app, but consider if image size grows
- [ ] **Health check**: `HEALTHCHECK` instruction in Dockerfile (or rely on K8s probes)
- [ ] **Signal handling**: `exec` in entrypoint.sh ensures Gunicorn receives SIGTERM directly
- [ ] **Entrypoint vs CMD**: Using `CMD` with entrypoint script is correct for configurability
- [ ] **Port exposure**: `EXPOSE 8080` matches Gunicorn bind address

### Kubernetes

- [ ] **Labels**: Resources have `app.kubernetes.io/name`, `app.kubernetes.io/version`, `app.kubernetes.io/component`
- [ ] **Resource requests/limits**: CPU and memory `requests` and `limits` defined
- [ ] **Probes**: `readinessProbe` and `livenessProbe` configured
- [ ] **Security context**: `runAsNonRoot`, `readOnlyRootFilesystem`, `allowPrivilegeEscalation: false`
- [ ] **Service type**: ClusterIP for internal services, appropriate for inter-service communication
- [ ] **Selector consistency**: Deployment `selector.matchLabels` matches Pod `labels` matches Service `selector`
- [ ] **Image pull policy**: Appropriate for the image tag (`:latest` should use `Always`)
- [ ] **Namespace**: Resources should specify or document target namespace
- [ ] **Pod disruption budget**: Consider for production deployments
- [ ] **Anti-affinity**: Consider for multi-replica deployments to spread across nodes

### LQN Compliance

- [ ] **Service time implementation**: Busy-wait uses CPU time, not wall-clock sleep
- [ ] **Call semantics**: SYNC blocks, ASYNC fires-and-forgets
- [ ] **Probability routing**: Weights correctly normalized and applied
- [ ] **Worker isolation**: Per-process state matches LQN processor semantics
- [ ] **Measurement fidelity**: psutil timing accurately captures per-request CPU demand

### Configuration Consistency

- [ ] **Env vars in app.py**: All `os.environ.get()` calls have sensible defaults
- [ ] **Env vars in entrypoint.sh**: Shell defaults match documented behavior
- [ ] **Env vars in deployment.yaml**: Template values match app expectations
- [ ] **Env vars in examples**: Example manifests use valid configurations
- [ ] **Documentation**: README env var table matches actual implementation

---

## Severity Levels

### MUST FIX
Issues that will cause bugs, crashes, security vulnerabilities, or incorrect behavior in production:
- Unhandled exceptions that crash the worker
- Race conditions in shared state
- Security issues (exposed secrets, unvalidated input leading to SSRF)
- K8s misconfigurations that prevent deployment
- Incorrect LQN semantics (sync call not blocking, service time using sleep)

### SHOULD FIX
Issues that degrade quality, performance, or maintainability:
- Missing resource limits in K8s manifests
- No health check endpoints
- Unstructured logging
- Missing type hints on public functions
- Hardcoded values that should be configurable

### CONSIDER
Suggestions for improvement that are not urgent:
- Application factory pattern for Flask
- Structured logging with JSON output
- Prometheus metrics endpoint
- Multi-stage Docker build
- Helm chart for parameterized deployment

### LGTM
Explicitly note things that are done well:
- Good patterns worth preserving
- Correct architectural decisions
- Clean implementations

---

## Output Format

```
CODE REVIEW - Generic Microservice Tester
==========================================
Reviewer: Claude (automated)
Scope: [full codebase | specific files | PR #N]
Date: [date]

MUST FIX (X items)
------------------
[MF-1] [file:line] [title]
  Issue: [description]
  Fix: [suggested fix]

[MF-2] ...

SHOULD FIX (X items)
--------------------
[SF-1] [file:line] [title]
  Issue: [description]
  Suggestion: [how to improve]

[SF-2] ...

CONSIDER (X items)
------------------
[C-1] [title]
  Rationale: [why this would help]

[C-2] ...

LGTM (X items)
--------------
[L-1] [title]
  Why: [what's good about it]

[L-2] ...

SUMMARY
-------
Overall Quality: [POOR | FAIR | GOOD | EXCELLENT]
Ready for Production: [YES | NO | WITH FIXES]
Key Strengths: [1-2 sentences]
Key Weaknesses: [1-2 sentences]
```
