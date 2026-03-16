# Sync Documentation with Project State

Synchronize all Markdown documentation files (`.md`) with the actual current state of the GMT codebase. Only modify `.md` files -- never touch source code, Dockerfiles, or Kubernetes manifests.

## Workflow

### Phase 1: Inventory
1. List all `.md` files in the repository (README.md, any docs in subdirectories).
2. List all `.md` files in `.claude/` (commands, skills).
3. Read the current state of every source file:
   - `src/app.py` -- routes, environment variables, dependencies, algorithms
   - `src/requirements.txt` -- dependency versions
   - `docker/Dockerfile` -- base image, build steps, exposed port
   - `docker/entrypoint.sh` -- Gunicorn defaults, startup flags
   - `kubernetes/base/` -- template structure, default values
   - `kubernetes/examples/` -- available topologies

### Phase 2: Drift Detection
For each `.md` file, check for:
- **Stale references**: environment variables, file paths, or configuration values that no longer match the source code.
- **Missing features**: functionality that exists in the code but is not documented.
- **Incorrect examples**: code snippets or YAML examples that would not work with the current implementation.
- **Wrong dependency versions**: documented versions that differ from `requirements.txt`.
- **Outdated architecture descriptions**: descriptions that do not match the current implementation (e.g., process-based vs thread-based async, psutil vs time-based CPU timing).

### Phase 3: Update
For each detected drift:
1. Fix the documentation to match the actual code.
2. Preserve the existing writing style and structure.
3. Do not add new sections unless critical information is completely missing.
4. Do not remove sections unless they describe removed functionality.

### Phase 4: Report
Produce a summary of all changes:

```
DOCUMENTATION SYNC REPORT
==========================
Files scanned: X
Files updated: Y
Files unchanged: Z

Changes:
  <file>: <one-line description of what changed>
  <file>: <one-line description of what changed>

No drift detected in:
  <file>
  <file>
```

## Important Rules
- ONLY modify `.md` files. Never modify `.py`, `.yaml`, `.sh`, `Dockerfile`, or any other non-Markdown file.
- When in doubt about intent, match the code -- code is the source of truth.
- Preserve all existing sections and headings unless they reference removed features.
- Do not reformat files gratuitously -- only change content that is actually wrong.
