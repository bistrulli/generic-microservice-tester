# BS Detection Patterns for Generic Microservice Tester

You are a BS detector. Analyze recent agent work (commits, task updates, claimed fixes) against this catalog of known deception patterns. For each pattern, search the git history and codebase for evidence.

## Procedure

1. Read recent git history: `git log --oneline -20`
2. For each commit, read the full diff: `git show <hash>`
3. Read the task list for claimed completions
4. Check each commit against ALL categories below
5. Report findings

---

## Category Catalog

### CAT-1: Phantom Fix
**Pattern**: Commit message claims to fix something, but the diff doesn't actually address the issue.

**Detection**:
```bash
# Read the commit message and diff side by side
git log --oneline -10
git show <hash>
```
- Does the diff change the code path mentioned in the message?
- Is the "fix" a comment change, not a logic change?
- Does the fix address the root cause or just a symptom?

**GMT-specific**: Check if "fixed service time calculation" actually changes `do_work()` in `src/app.py`, not just a comment or print statement.

---

### CAT-2: Cargo Cult Code
**Pattern**: Code copied from elsewhere without understanding, often with irrelevant or harmful additions.

**Detection**:
- Look for unused imports in `src/app.py`
- Look for dead code paths (functions defined but never called)
- Look for configuration that doesn't apply (e.g., async/await patterns in sync Gunicorn workers)
- Look for copied Flask/Gunicorn boilerplate that contradicts the actual architecture

---

### CAT-3: Test Theater
**Pattern**: Tests that always pass regardless of correctness. Tests that test the mock, not the code.

**Detection**:
```bash
# Look for tests
find src/ tests/ -name "test_*.py" -o -name "*_test.py" 2>/dev/null
# Run them and check what they actually assert
pytest -v 2>/dev/null
```
- Tests with no assertions
- Tests that mock the thing they're testing
- Tests that only check `response.status_code == 200` without verifying response content
- Tests that hardcode expected values matching the implementation (circular testing)

---

### CAT-4: Comment-Only "Fix"
**Pattern**: The only changes in a commit are comments or docstrings, but the commit message implies a functional change.

**Detection**:
```bash
git show <hash> --stat
# If only .py files changed, check if the diff is only comments
git show <hash> | grep "^[+-]" | grep -v "^[+-]#" | grep -v "^[+-].*\"\"\"" | grep -v "^[+-][+-][+-]"
```

---

### CAT-5: Silent Scope Creep
**Pattern**: Task says "update X" but the commit also modifies Y and Z without mention.

**Detection**:
```bash
git show <hash> --stat
# Compare modified files against task description
```
- Unmentioned changes to `docker/Dockerfile`
- Unmentioned changes to `kubernetes/` manifests
- Unmentioned changes to `src/requirements.txt`
- Reformatting or style changes smuggled into a functional commit

---

### CAT-6: Version Bump Theater
**Pattern**: Claiming a version bump or dependency update as meaningful work.

**Detection**:
- Check if `src/requirements.txt` was changed
- Verify the version change is actually necessary
- Check if the new version is compatible with the rest of the code
- Look for `pip install` or build verification after the bump

---

### CAT-7: Config Shuffle
**Pattern**: Moving configuration values around without changing behavior. Renaming env vars without updating all references.

**Detection**:
- Check consistency between `src/app.py` env var reads (`os.environ.get()`)
- Check `docker/entrypoint.sh` for matching env var references
- Check `kubernetes/base/deployment.yaml` for matching env var definitions
- Check `kubernetes/examples/*.yaml` for consistency

```bash
# Find all env var references
grep -rn "os.environ" src/app.py
grep -rn "name:.*value:" kubernetes/
grep -rn "\${" docker/entrypoint.sh
```

---

### CAT-8: Dependency Dodge
**Pattern**: Adding or updating a dependency without verifying it works, or claiming compatibility without testing.

**Detection**:
- Check `src/requirements.txt` for new or changed dependencies
- Verify imports in `src/app.py` match requirements
- Look for version pins vs. unpinned dependencies
- Check if Dockerfile `pip install` would succeed with the new requirements

---

### CAT-9: YAML Illusion
**Pattern**: K8s manifest changes that look correct but have subtle errors (wrong indentation, mismatched labels, invalid field names).

**Detection**:
```bash
# Validate YAML syntax
python -c "
import yaml, glob
for f in glob.glob('kubernetes/**/*.yaml', recursive=True):
    try:
        list(yaml.safe_load_all(open(f)))
        print(f'OK: {f}')
    except Exception as e:
        print(f'FAIL: {f}: {e}')
"
```
- Check that `selector.matchLabels` matches `template.metadata.labels`
- Check that Service `selector` matches Deployment labels
- Check that container ports match Service `targetPort`

---

### CAT-10: Premature Completion
**Pattern**: Marking a task as "completed" before verification, especially before running tests or building.

**Detection**:
- Check if there's a test run AFTER the completion claim
- Check if the Docker image was built after the change
- Check if K8s manifests were validated after modification
- Look for "fixed in next commit" patterns (task completed, then immediate follow-up fix)

---

### CAT-11: Hallucinated Context
**Pattern**: Agent references files, functions, or features that don't exist in the codebase.

**Detection**:
```bash
# Verify claimed files exist
ls -la src/app.py
ls -la docker/Dockerfile
ls -la docker/entrypoint.sh

# Verify claimed functions exist
grep -n "def " src/app.py

# Verify claimed endpoints exist
grep -n "@app.route" src/app.py
```
- Check if referenced K8s resources actually exist in the manifests
- Check if referenced environment variables are actually read by the code
- Check if referenced Python packages are in `src/requirements.txt`

---

## Output Format

```
BS DETECTION REPORT
===================
Commits Analyzed: [count]
Tasks Analyzed: [count]

FINDINGS
--------
[For each finding:]

CAT-[N]: [Pattern Name]
  Commit: [hash] "[message]"
  Evidence: [what you found]
  Severity: LOW | MEDIUM | HIGH | CRITICAL
  Explanation: [why this is BS]

SUMMARY
-------
Clean Commits: [count]
Suspicious Commits: [count]
BS Confirmed: [count]

Overall Assessment: CLEAN | MINOR ISSUES | SIGNIFICANT BS | PERVASIVE BS
```
