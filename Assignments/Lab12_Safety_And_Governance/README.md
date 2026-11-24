# Lab 12 — Safety & Governance (Egress Firewall, Mentor Gate, Telemetry & Rollback)

- **Course:** Agentic AI (`26ECAC401`) — Chapter 11: Student Success & Early Warning System (AURA)
- **Phase:** D · Governance & Safety
- **AURA Engine Mapping:** `Course Project/Source-Code/platform/services/core-api/lib/chapter11/egress.ts`, `review.ts`, `metrics.ts`, and `lib/data-refresh/generation.ts`

## What This Lab Demonstrates
- Enforces an allowlist-only `EgressFirewall` aliasing student, course, and evidence IDs into `case-xxxx`, `course-N`, and `ev-N` (`EGRESS_BLOCKED` on leaks).
- Binds `MentorApprovalGate` to `(artifact_id, content_hash, expected_revision, policy_attestation, data_generation)` plus `>= 8`-char rationale and two-step visibility confirmation.
- Tracks evaluation telemetry (first-pass rate, repair rate, word edit distance, latency), zero-LLM deterministic `replay_agent_run()`, instant `withdraw()`, and immutable `rollback_restore()`.

## Run
```bash
python3 Assignments/Lab12_Safety_And_Governance/lab12_safety_and_governance.py
```
