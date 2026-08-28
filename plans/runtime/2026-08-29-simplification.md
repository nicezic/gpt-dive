# Runtime Simplification - Phase 2

**Created**: 2026-08-29  
**Status**: In Progress  
**Branch**: renewal/260829-simplify  
**Predecessor**: ADR 0004 (renewal/260827-always-durable-runtime)

## Context

The 260827 renewal established **always-durable execution** and **SQLite control-plane authority**. This phase eliminates unnecessary abstractions identified during post-renewal analysis.

## Goals

1. **Remove indirection**: Collapse thin wrapper layers
2. **Consolidate state logic**: Unify duplicated SQL and transitions
3. **Clarify boundaries**: Move code to its natural module
4. **Reduce cognitive load**: Fewer modules, clearer responsibilities

## Non-Goals

- Changing external MCP contract
- Altering core execution lifecycle semantics
- Performance optimization (correctness first)

---

## Phase 1: Foundation Cleanup

### 1.3 Consolidate State Transitions ✓ PRIORITY

**Problem**: `ExecutionStore` has 4 methods (`finish`, `fail_accepted`, `fail_running`, `mark_lost`) with ~100 lines of duplicated SQL and `cancel_requested` logic.

**Solution**: Single `transition_to_terminal()` with parametric state/entry-state guards. Keep the 4 public methods as thin wrappers for semantic clarity at callsites.

**Files**:
- `src/gpt_dive/execution_store.py`

**Callsites**: 13 prod + 2 test (unchanged if using wrapper approach)

**Impact**: -100 LOC, single SQL template, auditable state machine

---

### 1.2 Eliminate ExecutionContext

**Problem**: 53-line `execution_context.py` wraps 3 fields (`execution_id`, `work_deadline_monotonic`, `artifact_dir`) with helper methods that could be module-level functions.

**Solution**: Pass execution record dict directly to capabilities. Move `remaining_seconds()`, `child_budget()`, `spill_path()` helpers into `command_runtime.py`.

**Files**:
- DELETE `src/gpt_dive/execution_context.py`
- UPDATE `src/gpt_dive/command_runtime.py`
- UPDATE `src/gpt_dive/code_capabilities.py`
- UPDATE `src/gpt_dive/code_mode_worker.py`

**Callsites**: ~5 locations

**Impact**: -53 LOC, one fewer abstraction layer

---

### 1.1 Eliminate task_runtime.py

**Problem**: ~250-line `task_runtime.py` is a projection layer with three concerns:
- Envelope parsing (belongs in `execution_manager`)
- Task projection (trivial, belongs in `execution_manager`)
- TrackedTasks formatting (presentation, belongs in `app.py`)

**Solution**:
1. Create `src/gpt_dive/code_mode_protocol.py` with `CODE_MODE_WORKER_PROTOCOL` constant
2. Move envelope parsing into `ExecutionManager.result()`
3. Move `elapsed_seconds` into `ExecutionManager._public_task()`
4. Move TrackedTasks formatting to `app.py`
5. Add `ExecutionManager.task_with_result()`, `.cancel_task()`, `.dismiss_task()`
6. Delete `task_runtime.py`

**Files**:
- CREATE `src/gpt_dive/code_mode_protocol.py`
- DELETE `src/gpt_dive/task_runtime.py`
- UPDATE `src/gpt_dive/execution_manager.py`
- UPDATE `src/gpt_dive/app.py`
- UPDATE `src/gpt_dive/code_mode_worker.py`
- UPDATE `src/gpt_dive/conduit/runtime.py`
- MIGRATE `tests/test_task_runtime.py`

**Callsites**: 8 in `app.py`, 4 in `conduit/runtime.py`, tests

**Impact**: -200 LOC, removes entire unnecessary layer

---

## Phase 2: Manager Simplification (Future)

### 2.1 Inline `_spawn_worker()` into `start()`

One-time private method → inline for clarity of atomic "journal then spawn" sequence.

### 2.2 Unify error handling

Eliminate duplication between `task_runtime._error_result()` and `app.py` Pydantic models.

---

## Phase 3: App Layer Cleanup (Future)

### 3.1 Simplify async publication machinery

9 functions managing deferred task publication → 1 context manager (~40 LOC).

### 3.2 Remove `publish` parameter from `start()`

Publication is delivery decision, not launch concern. Make explicit `manager.publish()` call.

---

## Execution Strategy

1. **One phase at a time**: 1.3 → 1.2 → 1.1
2. **Green commits**: Tests pass after each item
3. **Subagent delegation**: Use `(OpenCode Go) glm-5.3-flash` for implementation
4. **Main session**: Coordination and verification only

---

## Success Criteria

- [ ] All tests pass (143 tests in ~9s)
- [ ] Net reduction: ~350 LOC
- [x] Fewer modules: -2 files (execution_context.py, task_runtime.py)
- [ ] Clearer boundaries: envelope parsing in manager, formatting in app
- [ ] No behavior changes to external MCP contract
