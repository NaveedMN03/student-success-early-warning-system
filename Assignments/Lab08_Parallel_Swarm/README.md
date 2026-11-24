# Lab 08 — Parallel Swarm (Snapshot Fan-Out/Fan-In & Plan-Aligned Merge)

- **Course:** Agentic AI (`26ECAC401`) — Chapter 11: Student Success & Early Warning System (AURA)
- **Phase:** B · Multi-Agent Orchestration
- **AURA Engine Mapping:** `Course Project/Source-Code/platform/services/core-api/lib/db.ts` (`collectSnapshot`) and `lib/chapter11/service.ts` (`parallelMap`)

## What This Lab Demonstrates
- Exports one frozen snapshot ID (`snap-...`) across 4 source collectors (`academic`, `lms`, `internship`, `placement`) and fans out across all 6 cohort students (`SYN-0001..SYN-0006`) via `ThreadPoolExecutor`.
- Benchmarks sequential vs. parallel execution, verifying identical risk scores, bands, and blocking states at lower wall-clock latency.
- Implements `merge_by_plan_alignment()`, ensuring an eloquent out-of-scope or ungrounded candidate always loses to the plan-aligned draft.

## Run
```bash
python3 Assignments/Lab08_Parallel_Swarm/lab08_parallel_swarm.py
```
