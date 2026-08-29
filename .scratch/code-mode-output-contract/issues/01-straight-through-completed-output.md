# 01 — Straight-through completed output

**What to build:** Make a completed Code Mode execution expose the final Monty expression directly as the public program output, without accumulated `print()` text, duplicate semantic wrappers, or redundant completed metadata. Preserve local reduction so large intermediate capability values can stay inside Monty while string/list/dict final values cross the boundary unchanged.

**Blocked by:** None — can start immediately.

**Status:** completed

- [x] A successful completed outcome has exactly `kind`, `execution_id`, and `output` on the public Code Mode surface.
- [x] `output` is the final Monty expression itself; string, list, and dict values survive unchanged.
- [x] Monty `print()` output is not replayed as a normal final `stdout` field.
- [x] No nested semantic `result` wrapper remains between the program value and public `output`.
- [x] Completed output does not repeat `label` or add backend/process/timing metadata.
- [x] Independent capability calls can be gathered and reduced locally without their full intermediate values appearing in the public outcome.
- [x] Existing ADR 0004 durability semantics remain unchanged.
