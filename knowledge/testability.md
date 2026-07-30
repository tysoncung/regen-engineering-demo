# Testability affordances

Two endpoints exist so that contracts can be executed. They are not part of the
domain, and no business rule refers to them, but every implementation must
provide them or its contracts cannot be run at all.

This file exists because of a real gap. A Regeneration Test on 2026-07-31
produced an implementation that was missing both, because the knowledge
described the domain and forgot that contracts need somewhere to stand. An
implementation regenerated from the knowledge alone would have been unscoreable.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Returns 200 once the service is accepting requests. The runner polls this before starting, so it must respond before any other route is used. |
| `POST` | `/reset` | Discards all state and returns 204. |

## Why reset exists

The contract runner calls `POST /reset` before **every scenario**, so each one
starts from an empty system.

Without it, scenarios would share state and their outcomes would depend on the
order they ran in. A suite whose result depends on ordering is not a fair test
of a regenerated implementation, which is the entire job of the contract suite
here.

Reset must also return identifier sequences to their starting point, so that a
scenario can rely on the ids it creates.

## The obvious objection

Yes, a production service should not expose an endpoint that erases everything.

The honest answer is that this demo optimises for being cloneable and runnable
in five minutes with no dependencies and no configuration. A real system would
gate these behind an environment flag, a separate admin port, or a test-only
build, and that decision would deserve an ADR of its own.

What matters for the methodology is that the affordance is **written down**
rather than living in the tacit understanding of whoever wrote the test harness.
That tacit knowledge is exactly the kind that regeneration loses.
