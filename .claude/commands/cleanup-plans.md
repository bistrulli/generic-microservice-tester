# Cleanup Plans and Tasks

Clean up stale plans, completed tasks, and orphaned task lists. This command operates on Claude Code task state.

## Workflow

### Phase 1: Inventory
1. List all existing tasks using TaskList.
2. For each task, note: ID, title, status (pending, in_progress, completed), and creation context.

### Phase 2: Classification
Classify each task:

- **COMPLETED**: Status is `completed`. Safe to remove.
- **STALE**: Status is `in_progress` or `pending` but the associated code changes have already been made (verify by checking if the files mentioned in the task description reflect the intended state).
- **ORPHANED**: Task references files, branches, or features that no longer exist in the repository.
- **ACTIVE**: Task is `in_progress` or `pending` and the associated work is genuinely incomplete.

### Phase 3: Report

```
============================================================
GMT PLAN CLEANUP REPORT
============================================================

COMPLETED (safe to remove):
  - [ID] <title>
  - [ID] <title>

STALE (work done, task not updated):
  - [ID] <title> -- Evidence: <why it's stale>

ORPHANED (references don't exist):
  - [ID] <title> -- Missing: <what's missing>

ACTIVE (keeping):
  - [ID] <title> -- Status: <status>

============================================================
SUMMARY: X completed, Y stale, Z orphaned, W active
Recommended action: Remove X + Y + Z tasks (total: N)
============================================================
```

### Phase 4: Interactive Confirmation
Ask the user: "Should I remove (1) completed only, (2) completed + stale, (3) completed + stale + orphaned, (4) let me pick, (5) abort?"

### Phase 5: Cleanup
For each task to remove:
1. Update the task status to `completed` (if not already).
2. Record what was removed in the final summary.

### Phase 6: Final Report
```
CLEANUP COMPLETE
  Tasks removed:  X
  Tasks kept:     Y
  Active backlog: Z items
```

## Important Rules
- NEVER remove tasks that are genuinely `in_progress` without user confirmation.
- Always verify stale classification by checking actual file state -- do not guess.
- If there are no tasks to clean up, report "No cleanup needed" and exit.
