# GMT Codebase Preparation

Explore the Generic Microservice Tester codebase interactively, build understanding, and produce a structured prompt for `/plan` or `/auto`.

## Workflow

### Phase 1: Codebase Exploration
Systematically explore the three main directories:

1. **`src/`** -- Application source code
   - Read `app.py` fully. Identify: route handlers, environment variable configuration, CPU simulation logic, outbound call handling (SYNC vs ASYNC), HTTP session management, thread pool configuration.
   - Read `requirements.txt`. Note all dependencies and their versions.

2. **`docker/`** -- Container configuration
   - Read `Dockerfile`. Identify: base image, build stages, exposed ports, entrypoint.
   - Read `entrypoint.sh`. Identify: Gunicorn configuration, worker/thread defaults, startup behavior.

3. **`kubernetes/`** -- Deployment manifests
   - Read `base/deployment.yaml` and `base/service.yaml`. Identify: template structure, default environment variables.
   - Read each file in `examples/`. For each topology, identify: architecture pattern, service count, call graph, resource configuration.

### Phase 2: Architecture Understanding
After exploration, answer these questions internally:
- What is the request lifecycle? (receive -> do_work -> parse_outbound_calls -> make calls -> respond)
- How does CPU simulation work? (psutil-based delta tracking with exponential distribution)
- How are SYNC vs ASYNC calls implemented? (shared session vs isolated thread pool)
- What LQN concepts does this implement? (Processor, Task, Entry, Activity, sync/async calls)
- What topologies exist in examples? (2-tier, 3-tier chain, probabilistic choice)

### Phase 3: Interactive Clarification
Ask the user:
1. **What is your goal?** (e.g., add a feature, fix a bug, create a new topology, optimize performance, add tests, add monitoring)
2. **Which area of the codebase is involved?** (src/, docker/, kubernetes/, or cross-cutting)
3. **Any constraints?** (e.g., must maintain backward compatibility, must work with specific K8s version, must not change environment variable interface)

### Phase 4: Output Prompt
Based on the answers, produce a structured prompt in this format:

```
## Task
<one-sentence description of what needs to be done>

## Context
- Current state: <what exists today>
- Target state: <what should exist after implementation>
- Key files: <list of files that will be read or modified>

## Constraints
- <constraint 1>
- <constraint 2>

## Acceptance Criteria
- [ ] <criterion 1>
- [ ] <criterion 2>
- [ ] All existing topologies still deploy successfully
- [ ] Docker image builds without errors

## Suggested Approach
1. <step 1>
2. <step 2>
```

Tell the user: "This prompt is ready for `/plan` (to create a detailed plan) or `/auto` (to execute directly)."

## Important Rules
- Do NOT modify any files during preparation.
- Do NOT skip the interactive clarification phase -- always ask the user what they want to do.
- Be specific about file paths (always absolute).
- If you discover issues during exploration (bugs, inconsistencies, missing files), note them but do not fix them.
