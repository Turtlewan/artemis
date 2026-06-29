---
status: ready
coder_effort: low
cross_model_review: true
---

# staging-at-most-once-on-external-effect

Stop `ActionStagingService.approve` from making a row re-approvable after its execute-twin has already
been dispatched. A `takes-action` twin that performs an external side effect and then raises must not
be silently re-runnable. Rationale: `docs/findings/tier1-concurrency-audit-2026-06-29.md` (§ genuine
non-race gap).

## Files to change
- `src/artemis/staging/model.py` — **modify** (add `ActionStatus.FAILED`).
- `src/artemis/staging/service.py` — **modify** (route post-dispatch failure to terminal `FAILED`).
- `tests/test_action_staging.py` — **modify** (replace the rollback-to-PENDING expectation).

## Exact changes

### Task 1 — add a terminal FAILED status
**`src/artemis/staging/model.py`.** Add to `ActionStatus(StrEnum)`:
```python
    FAILED = "failed"
```
Place it after `EXPIRED`. No other model change.

### Task 2 — terminal failure instead of rollback after dispatch
**`src/artemis/staging/service.py`.** In `approve`, the rollback only fires *after* the conditional
`PENDING→EXECUTING` flip, i.e. after the twin has been invoked. Change that path to move the row to a
terminal `FAILED` state carrying the error, and stop re-flipping to `PENDING`:

```python
        try:
            result_obj = await tool_spec.callable_ref(validated_args)
        except Exception as exc:
            self.store.set_status(
                action_id,
                ActionStatus.FAILED,
                result={"error": str(exc)},
            )
            raise
```

Pre-flip failures are unchanged and still correct: twin lookup (`get_tool`) and
`args_schema.model_validate` run *before* the `set_status_conditional` flip, so a preparation failure
never enters `EXECUTING` and the row stays `PENDING` (re-approvable). Update the `approve` docstring's
second paragraph to state that a failure *after* dispatch lands in terminal `FAILED` (not re-approvable),
while preparation failures before the flip remain re-approvable.

### Task 3 — tests
**`tests/test_action_staging.py`.** Find the test asserting that a callable exception leaves the action
back in `PENDING` and rewrite it to assert:
- after the dispatched callable raises, `store.get(action_id).status is ActionStatus.FAILED`;
- the stored `result` contains the error (`result["error"]` is the exception message);
- a subsequent `approve(action_id)` raises `ValueError` (status is `failed`, not `pending`);
- a subsequent `reject(action_id)` raises `ValueError` for the same reason.
Keep the existing pre-flip-failure tests (twin missing / args invalid leave status `PENDING`) — they
must still pass unchanged.

## Acceptance criteria
1. A `takes-action` twin that raises after the `EXECUTING` flip leaves the action in `FAILED` with the
   error recorded, and the action cannot be re-approved or rejected. Verify:
   `uv run pytest tests/test_action_staging.py -q`.
2. Preparation failures (missing `{tool}_execute` twin, invalid args) still leave the action `PENDING`
   and re-approvable. Verify: same test module green.
3. No regression. Verify: full `uv run mypy` clean + `uv run pytest -q` green.

## Commands to run
```sh
uv run pytest tests/test_action_staging.py -q
uv run mypy
uv run pytest -q
```
