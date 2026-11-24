# Lab 06 — Agent Runtime (Leases, Idempotency, Checkpoints & Append-Only Audit)

- **Course:** Agentic AI (`26ECAC401`) — Chapter 11: Student Success & Early Warning System (AURA)
- **Phase:** A/B · Durable Runtime Layer
- **AURA Engine Mapping:** `Course Project/Source-Code/platform/services/core-api/lib/chapter11/service.ts`, `lease.ts`, and `migrations/001_core.sql`

## What This Lab Demonstrates
- Implements an in-memory SQLite runtime (`AuraRuntime`) uniting step budgets, worker leases (`180s` TTL + `LEASE_EXPIRED` sweep up to `MAX_RETRIES=3`), UUID `Idempotency-Key` receipt deduplication, and `persist_then_audit()`.
- Resumes crashed runs from their last stage checkpoint (`collect_sources` -> `score_risk` -> `draft_packet` -> `human_gate` -> `publish_plan`) without re-executing completed steps.
- Enforces tamper-proof logging via SQLite triggers (`reject_audit_update` and `reject_audit_delete`) that raise `sqlite3.IntegrityError` on any mutation attempt.

## Run
```bash
python3 Assignments/Lab06_Agent_Runtime/lab06_agent_runtime.py
```
