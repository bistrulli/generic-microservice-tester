# Cleanup Git Branches

Clean up stale, merged, and orphaned git branches. This command is project-agnostic and operates purely on git state.

## Workflow

### Phase 1: Inventory
1. Fetch latest remote state:
   ```bash
   git fetch --prune
   ```
2. List all local branches with their tracking status:
   ```bash
   git branch -vv
   ```
3. List all remote branches:
   ```bash
   git branch -r
   ```
4. Identify the default branch (main or master).

### Phase 2: Classification
Classify each local branch into one of these categories:

- **MERGED**: Branch has been merged into the default branch (safe to delete).
  ```bash
  git branch --merged main
  ```
- **ORPHANED**: Branch tracks a remote branch that no longer exists (likely deleted after PR merge).
- **STALE**: Branch has not been updated in more than 30 days and is not merged.
- **ACTIVE**: Branch has recent commits and is not merged.
- **CURRENT**: The currently checked-out branch (never delete).
- **PROTECTED**: The default branch -- main or master (never delete).

### Phase 3: Interactive Confirmation
Present the classification to the user:

```
============================================================
GMT BRANCH CLEANUP REPORT
============================================================

SAFE TO DELETE (merged or orphaned):
  - feature/old-feature        (merged into main, last commit: 2025-12-01)
  - fix/resolved-bug           (remote deleted, last commit: 2025-11-15)

POTENTIALLY STALE (>30 days, not merged):
  - experiment/thing           (last commit: 2025-10-05, 120 days ago)

ACTIVE (keeping):
  - feature/current-work       (last commit: 2026-03-14, 2 days ago)

PROTECTED (never deleted):
  - main
============================================================
```

Ask the user: "Which branches should I delete? Options: (1) all safe-to-delete, (2) safe-to-delete + stale, (3) let me pick individually, (4) abort."

### Phase 4: Cleanup
For each branch to delete:
1. Delete the local branch:
   ```bash
   git branch -d <branch>   # for merged branches
   git branch -D <branch>   # for unmerged branches (only if user confirmed)
   ```
2. If the remote branch still exists and user confirms, delete it:
   ```bash
   git push origin --delete <branch>
   ```

### Phase 5: Final Report
```
CLEANUP COMPLETE
  Branches deleted (local):  X
  Branches deleted (remote): Y
  Branches kept:             Z
```

## Important Rules
- NEVER delete `main` or `master`.
- NEVER delete the currently checked-out branch.
- NEVER force-delete a branch without explicit user confirmation.
- Always use `git branch -d` first (safe delete). Only use `-D` if the user explicitly approves deleting unmerged branches.
- Do not push deletions to remote unless the user explicitly confirms.
