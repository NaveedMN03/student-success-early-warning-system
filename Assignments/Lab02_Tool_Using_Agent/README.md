# Lab 02 — Tool-Using Agent (AURA Typed Tools & Alias Lock)

- **Course:** Agentic AI (`26ECAC401`) — Chapter 11: Student Success & Early Warning System (AURA)
- **Phase:** A · Foundations
- **AURA Engine Mapping:** `Course Project/Source-Code/platform/services/core-api/lib/chapter11/agent-loop.ts` and `investigator.ts`

## What This Lab Demonstrates
- Wraps source reads (`read_academic_record`, `read_lms_engagement`, `read_internship_status`, `read_placement_activity`) and deterministic risk computation (`compute_aura_risk` with `fixed` and `graded` modes) in a typed `ToolRegistry`.
- Enforces AURA loop budgets (`max_turns=2`, `max_tool_calls=4`, `max_result_bytes=6000`).
- Locks every investigation loop to a single `case-xxxx` alias (`OUT_OF_SCOPE` refusal on cross-student lookups), checks `ROUNDING_TOLERANCE = 0.5` (`EVIDENCE_DRIFT`), and records SHA-256 `result_hash` + `result_bytes` in the audit trail.

## Run
```bash
python3 Assignments/Lab02_Tool_Using_Agent/lab02_tool_using_agent.py
```
