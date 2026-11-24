# Lab 10 — Ops Resilience (Closed-Vocabulary Diagnosis, Targeted Patching & Failover)

- **Course:** Agentic AI (`26ECAC401`) — Chapter 11: Student Success & Early Warning System (AURA)
- **Phase:** C · Applied Reliability
- **AURA Engine Mapping:** `Course Project/Source-Code/platform/services/core-api/lib/chapter11/diagnosis.ts`, `provider.ts`, `faults.ts`, and `unavailable.ts`

## What This Lab Demonstrates
- Runs deterministic closed-vocabulary diagnosis (`DIAGNOSIS_TEXT`) mapping validator errors to exact JSON paths (`rationale[i]`, `actions[j]`).
- Performs surgical `apply_targeted_patch()` so passing sentences and actions remain byte-identical (verified by SHA-256 hash) across repairs.
- Enforces `MAX_REPAIRS = 2` before escalating to `needs_human`, and proves `ProviderFailoverChain` returns `ai_unavailable_retry` (`draft=None`, never fake rule-based templates) when all model providers fail.

## Run
```bash
python3 Assignments/Lab10_Ops_Resilience_Self_Healing/lab10_ops_resilience_self_healing.py
```
