---
id: RISK-001
type: risk
title: Email uniqueness can race under multi-instance deployment
status: active
since: 2026-07-31
likelihood: medium
impact: high
mitigation: Single-writer registration path, or a unique constraint in shared storage
affects: [customer]
---

BR-001 requires an email to identify at most one account, and NFR-002 requires
concurrent duplicate registrations to yield exactly one success. Both current
implementations satisfy this within a single process (an event loop in one, a
lock in the other), but the guarantee evaporates the moment two instances run
against shared storage, because check-and-insert stops being atomic.

Nothing in the knowledge currently constrains deployment topology, so an
operator scaling horizontally would violate BR-001 without changing a line of
code. That gap between "correct as built" and "correct as deployed" is exactly
where this class of system breaks in production.
