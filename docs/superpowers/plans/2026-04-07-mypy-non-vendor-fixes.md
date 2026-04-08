# mypy Non-Vendor Fixes + Pre-Push Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all 9 mypy errors in non-vendored code and add a mypy gate to the pre-push hook so the repo stays clean.

**Architecture:** Six mechanical fixes across four files (type annotations, stale kwargs, type narrowing), one pyproject.toml exclusion for demo scripts, and one addition to the existing `.git/hooks/pre-push` shell script. No new tests — each task is verified by running `mypy gigaevo/` and confirming the error count drops.

**Tech Stack:** Python 3.12, mypy 1.20, pyproject.toml `[tool.mypy]` config, bash pre-push hook

---

## File Map

| File | Change |
|------|--------|
| `gigaevo/adversarial/opponent_provider.py` | Add `set[int]` annotation to `indices` |
| `gigaevo/problems/initial_loaders.py` | `child.id` / `parent.id` → `child` / `parent` |
| `gigaevo/memory/ideas_tracker/ideas_tracker.py` | Add `assert isinstance` to narrow analyzer type |
| `gigaevo/memory/ideas_tracker/cli.py` | Remove stale `config_path` and `path_to_database` kwargs |
| `pyproject.toml` | Exclude `gigaevo/memory/examples/` from mypy |
| `.git/hooks/pre-push` | Add mypy gate after ruff checks |

---

## Task 0: Set Up Git Worktree

**Files:** none

- [ ] **Step 1: Create worktree from main**

```bash
cd /mnt/virtual_ai0001071-04017_SR004-nfs1/CFS-SR008/workspace/mathemage/gigaevo-core-internal
rtk git worktree add .worktrees/mypy-fixes -b chore/mypy-non-vendor-fixes main
```

- [ ] **Step 2: Verify clean baseline**

```bash
cd .worktrees/mypy-fixes
rtk git status
```

Expected: `nothing to commit, working tree clean` on branch `chore/mypy-non-vendor-fixes`.

---

## Task 1: Fix opponent_provider.py — missing set annotation

`indices = set()` on line 105 needs a type annotation. mypy cannot infer the element type.

**Files:**
- Modify: `gigaevo/adversarial/opponent_provider.py:105`

- [ ] **Step 1: Apply the fix**

Find line 105 in `gigaevo/adversarial/opponent_provider.py`:
```python
        indices = set()
```
Replace with:
```python
        indices: set[int] = set()
```

- [ ] **Step 2: Verify fix**

```bash
cd /mnt/virtual_ai0001071-04017_SR004-nfs1/CFS-SR008/workspace/mathemage/gigaevo-core-internal/.worktrees/mypy-fixes
/home/jovyan/.mlspace/envs/evo/bin/python3 -m mypy gigaevo/adversarial/opponent_provider.py --ignore-missing-imports 2>&1 | grep "error:"
```

Expected: no output (0 errors).

- [ ] **Step 3: Commit**

```bash
rtk git add gigaevo/adversarial/opponent_provider.py
rtk git commit -m "fix(types): annotate indices as set[int] in OpponentProvider"
```

---

## Task 2: Fix initial_loaders.py — .id on str

`program.lineage.children` and `program.lineage.parents` are `list[str]` (IDs, not Program objects). Lines 115 and 118 call `.id` on each element, but the element is already the ID string.

**Files:**
- Modify: `gigaevo/problems/initial_loaders.py:115,118`

- [ ] **Step 1: Read the context**

Check lines 112–122 to confirm the loop structure:
```bash
sed -n '112,122p' gigaevo/problems/initial_loaders.py
```

Expected output (approximately):
```python
                for child in program.lineage.children:
                    if child.id in all_ids:
                        copy.lineage.children.append(child)
                for parent in program.lineage.parents:
                    if parent.id in all_ids:
                        copy.lineage.parents.append(parent)
```

- [ ] **Step 2: Apply the fixes**

In `gigaevo/problems/initial_loaders.py`, find:
```python
                for child in program.lineage.children:
                    if child.id in all_ids:
                        copy.lineage.children.append(child)
                for parent in program.lineage.parents:
                    if parent.id in all_ids:
                        copy.lineage.parents.append(parent)
```

Replace with:
```python
                for child in program.lineage.children:
                    if child in all_ids:
                        copy.lineage.children.append(child)
                for parent in program.lineage.parents:
                    if parent in all_ids:
                        copy.lineage.parents.append(parent)
```

- [ ] **Step 3: Verify fix**

```bash
/home/jovyan/.mlspace/envs/evo/bin/python3 -m mypy gigaevo/problems/initial_loaders.py --ignore-missing-imports 2>&1 | grep "error:"
```

Expected: no output.

- [ ] **Step 4: Commit**

```bash
rtk git add gigaevo/problems/initial_loaders.py
rtk git commit -m "fix(types): child/parent in lineage are already ID strings, not Program objects"
```

---

## Task 3: Fix ideas_tracker.py — narrow analyzer type in _process_program

`_process_program` calls `self.analyzer.process_ideas(program_ideas, active_ideas, inactive_ideas)` — the 3-argument form that belongs to `IdeaAnalyzer`. But mypy sees `self.analyzer` as potentially `IdeaAnalyzerFast`, whose `process_ideas()` takes 0 arguments. The method is only ever called from `_default_analyzer_pipeline`, which already has an `isinstance(self.analyzer, IdeaAnalyzer)` guard. Adding the same assert at the top of `_process_program` narrows the type.

**Files:**
- Modify: `gigaevo/memory/ideas_tracker/ideas_tracker.py` (`_process_program` method, ~line 263)

- [ ] **Step 1: Locate _process_program**

```bash
grep -n "def _process_program" gigaevo/memory/ideas_tracker/ideas_tracker.py
```

Expected output: something like `263:    def _process_program(self, program: ProgramRecord) -> None:`

- [ ] **Step 2: Apply the fix**

In `gigaevo/memory/ideas_tracker/ideas_tracker.py`, find the start of `_process_program`:
```python
    def _process_program(self, program: ProgramRecord) -> None:
        active_ideas = self.ideas_manager.ideas_groups_texts()
```

Replace with:
```python
    def _process_program(self, program: ProgramRecord) -> None:
        assert isinstance(self.analyzer, IdeaAnalyzer)
        active_ideas = self.ideas_manager.ideas_groups_texts()
```

`IdeaAnalyzer` is already imported at the top of the file — no new import needed.

- [ ] **Step 3: Verify fix**

```bash
/home/jovyan/.mlspace/envs/evo/bin/python3 -m mypy gigaevo/memory/ideas_tracker/ideas_tracker.py --ignore-missing-imports 2>&1 | grep "error:"
```

Expected: no output.

- [ ] **Step 4: Commit**

```bash
rtk git add gigaevo/memory/ideas_tracker/ideas_tracker.py
rtk git commit -m "fix(types): assert isinstance(IdeaAnalyzer) in _process_program to narrow analyzer type"
```

---

## Task 4: Fix cli.py — remove stale constructor and run() kwargs

`IdeaTracker.__init__` does not accept `config_path` (the config is read from `EVO_MEMORY_CONFIG_PATH` env var, already set on line 217). `IdeaTracker.run()` does not accept `path_to_database` — that parameter was removed when the API was refactored. Both call-sites reference APIs that no longer exist.

**Files:**
- Modify: `gigaevo/memory/ideas_tracker/cli.py:219-222`

- [ ] **Step 1: Apply the fix**

In `gigaevo/memory/ideas_tracker/cli.py`, find:
```python
        tracker = IdeaTracker(config_path=runtime_config_path, logs_dir=args.logs_dir)
        if args.source == "csv":
            tracker.run(path_to_database=args.csv_path)
        else:
            tracker.run()
```

Replace with:
```python
        tracker = IdeaTracker(logs_dir=args.logs_dir)
        tracker.run()
```

(The `config_path` kwarg was never a valid parameter — the env var on line 217 is the mechanism. The `path_to_database` kwarg and CSV source branch never worked after the `run()` API was simplified to accept `list[Program] | None`.)

- [ ] **Step 2: Verify fix**

```bash
/home/jovyan/.mlspace/envs/evo/bin/python3 -m mypy gigaevo/memory/ideas_tracker/cli.py --ignore-missing-imports 2>&1 | grep "error:"
```

Expected: no output.

- [ ] **Step 3: Commit**

```bash
rtk git add gigaevo/memory/ideas_tracker/cli.py
rtk git commit -m "fix(types): remove stale config_path/path_to_database kwargs from IdeaTracker usage in CLI"
```

---

## Task 5: Exclude examples/ from mypy in pyproject.toml

`gigaevo/memory/examples/a_mem_memory_creation.py` is a demo script that uses a type-incompatible call. It's not production code. Exclude it from the mypy check rather than fixing vendored-adjacent demo code.

**Files:**
- Modify: `pyproject.toml` (`[tool.mypy]` section, `exclude` field)

- [ ] **Step 1: Apply the fix**

In `pyproject.toml`, find the `exclude` line in `[tool.mypy]`:
```toml
exclude = ["build/", "dist/", "gigaevo/memory/_vendor/A_mem/", "gigaevo/memory/_vendor/GAM_root/"]
```

Replace with:
```toml
exclude = ["build/", "dist/", "gigaevo/memory/_vendor/A_mem/", "gigaevo/memory/_vendor/GAM_root/", "gigaevo/memory/examples/"]
```

- [ ] **Step 2: Verify clean full run**

```bash
/home/jovyan/.mlspace/envs/evo/bin/python3 -m mypy gigaevo/ --ignore-missing-imports 2>&1 | grep "^gigaevo" | grep "error:" | grep -v "_vendor"
```

Expected: **no output** — zero non-vendor errors.

Also confirm total:
```bash
/home/jovyan/.mlspace/envs/evo/bin/python3 -m mypy gigaevo/ --ignore-missing-imports 2>&1 | grep "^Found"
```

Expected: `Found 0 errors` (or only vendor errors if mypy still processes vendor dirs — either way, grep above confirmed no non-vendor errors).

- [ ] **Step 3: Commit**

```bash
rtk git add pyproject.toml
rtk git commit -m "chore(mypy): exclude gigaevo/memory/examples/ from mypy (demo scripts)"
```

---

## Task 6: Add mypy gate to pre-push hook

The current `.git/hooks/pre-push` runs ruff check + ruff format + gitnexus analyze. Add mypy after ruff, before gitnexus.

**Files:**
- Modify: `.git/hooks/pre-push`

- [ ] **Step 1: Read the current hook**

```bash
cat .git/hooks/pre-push
```

The hook currently has this structure:
```sh
#!/bin/sh
PYTHON="${GIGAEVO_PYTHON:-python3}"
NPX="$(dirname "$PYTHON")/npx"

echo "Running ruff check..."
"$PYTHON" -m ruff check . --quiet || { echo "❌ ruff check failed. Fix lint errors before pushing."; exit 1; }

echo "Running ruff format check..."
"$PYTHON" -m ruff format --check . --quiet || { echo "❌ ruff format failed. Run 'ruff format .' before pushing."; exit 1; }

echo "✅ Lint clean."

echo "Running gitnexus analyze..."
"$NPX" gitnexus analyze 2>&1 || echo "⚠️  gitnexus analyze failed — index may be stale. Push continues."
```

- [ ] **Step 2: Apply the fix**

Find the line:
```sh
echo "✅ Lint clean."
```

Replace with:
```sh
echo "✅ Lint clean."

echo "Running mypy..."
"$PYTHON" -m mypy gigaevo/ --ignore-missing-imports --no-error-summary --quiet 2>&1 | grep "error:" | grep -v "_vendor" | head -20
if "$PYTHON" -m mypy gigaevo/ --ignore-missing-imports --no-error-summary --quiet 2>&1 | grep "error:" | grep -v "_vendor" | grep -q "error:"; then
    echo "❌ mypy failed. Fix type errors before pushing."
    exit 1
fi
echo "✅ mypy clean."
```

- [ ] **Step 3: Verify the hook runs correctly**

```bash
bash .git/hooks/pre-push
```

Expected: ruff ✅, mypy ✅, gitnexus runs. No errors.

- [ ] **Step 4: Commit the hook**

The hook is in `.git/` and is not tracked by git. No commit needed — just verify it works.

Report that the hook is updated and tested.

---

## Task 7: Full verification + PR

- [ ] **Step 1: Run full mypy to confirm zero non-vendor errors**

```bash
cd /mnt/virtual_ai0001071-04017_SR004-nfs1/CFS-SR008/workspace/mathemage/gigaevo-core-internal/.worktrees/mypy-fixes
/home/jovyan/.mlspace/envs/evo/bin/python3 -m mypy gigaevo/ --ignore-missing-imports 2>&1 | grep "^gigaevo" | grep "error:" | grep -v "_vendor"
```

Expected: no output.

- [ ] **Step 2: Run ruff to confirm no lint regressions**

```bash
/home/jovyan/.mlspace/envs/evo/bin/python3 -m ruff check gigaevo/adversarial/opponent_provider.py gigaevo/problems/initial_loaders.py gigaevo/memory/ideas_tracker/ideas_tracker.py gigaevo/memory/ideas_tracker/cli.py
```

Expected: no output (clean).

- [ ] **Step 3: Run the test suite on changed files**

```bash
PYTHONPATH=. /home/jovyan/.mlspace/envs/evo/bin/python3 -m pytest tests/ -x -q 2>&1 | tail -10
```

Expected: all tests pass.

- [ ] **Step 4: Push branch and open PR**

```bash
rtk git push -u origin chore/mypy-non-vendor-fixes
gh pr create \
  --base main \
  --title "fix(types): resolve all non-vendor mypy errors + add mypy pre-push gate" \
  --body "$(cat <<'EOF'
## Summary

- Fixes 9 mypy errors across 4 non-vendored files: missing `set[int]` annotation, stale `.id` on string IDs, analyzer type narrowing via `assert isinstance`, and removed stale `config_path`/`path_to_database` kwargs from CLI
- Excludes `gigaevo/memory/examples/` from mypy (demo scripts)
- Adds mypy check to `.git/hooks/pre-push` so the repo stays clean going forward

## Files Changed

- `gigaevo/adversarial/opponent_provider.py` — `indices: set[int] = set()`
- `gigaevo/problems/initial_loaders.py` — `child`/`parent` are already ID strings
- `gigaevo/memory/ideas_tracker/ideas_tracker.py` — `assert isinstance(self.analyzer, IdeaAnalyzer)`
- `gigaevo/memory/ideas_tracker/cli.py` — removed stale kwargs
- `pyproject.toml` — exclude `gigaevo/memory/examples/`

## Test Plan

- [ ] `mypy gigaevo/ --ignore-missing-imports` → 0 non-vendor errors
- [ ] `ruff check .` → clean
- [ ] Full test suite passes

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```
