# Assignments — Agentic AI (`26ECAC401`) · Team 12 (AURA)

This folder contains 12 standalone, zero-external-dependency Python 3.10+ assignments grounded directly in **AURA (Chapter 11: Student Success & Early Warning System)** under [`Course Project/Source-Code/`](../Course%20Project/Source-Code/) and aligned with the *Agentic AI: 15 Worklets / 14-Lab Build Book* and Team 12's *Lab Worklet Review Sheet*.

All 12 labs run strictly on the Python standard library (`sqlite3`, `concurrent.futures`, `hashlib`, `dataclasses`, `json`, `re`, `pathlib`) at **INR 0 cloud cost** using AURA's synthetic cohort fixtures (`SYN-0001`–`SYN-0006`, `CH11-DEMO-1`).

## Run All 12 Labs
```bash
python3 Assignments/verify_all_labs.py
```

## Lab Index (Labs 01–12 + Capstone Mapping 13–14)

| Lab | Directory | Concept | AURA Engine Equivalent |
| --- | --- | --- | --- |
| 01 | [Lab01_Agent_Vs_Chatbot](Lab01_Agent_Vs_Chatbot/) | Stateful clarify -> plan -> revise -> lock loop, Jaccard dedup, `ground_criteria()`, `scope_conflict` | `lib/chapter11/planner.ts`, `planning.ts` |
| 02 | [Lab02_Tool_Using_Agent](Lab02_Tool_Using_Agent/) | Typed tool registry, turn/call/byte budgets, `case-xxxx` alias lock (`OUT_OF_SCOPE`), `0.5` drift guard | `lib/chapter11/agent-loop.ts`, `investigator.ts` |
| 03 | [Lab03_Skill_Creation](Lab03_Skill_Creation/) | Case-agnostic `PlanBlueprintSkill` and `PacketV2FormatSkill`, 7-action catalogue, locked faculty owner | `lib/chapter11/catalogue.ts`, `packet-v2.ts` |
| 04 | [Lab04_Memory_And_Retrieval](Lab04_Memory_And_Retrieval/) | Short-term `EvidenceBook`/60s cache vs. long-term `sha256-lexical-128-v1` anonymized `HistoryRetriever` | `lib/chapter11/engine.ts`, `streamlit_app/common.py` |
| 05 | [Lab05_MCP_Style_Connector](Lab05_MCP_Style_Connector/) | Single JSON-RPC 2.0 gateway with actor RBAC (`403 FORBIDDEN`) and swappable JSON/SQLite adapters | `streamlit-worker.mts`, `connectors.ts`, `bridge.py` |
| 06 | [Lab06_Agent_Runtime](Lab06_Agent_Runtime/) | 180s worker leases (`LEASE_EXPIRED`), UUID `Idempotency-Key`, checkpoints, SQLite append-only audit triggers | `lib/chapter11/service.ts`, `lease.ts`, `001_core.sql` |
| 07 | [Lab07_Agentic_Node_Graph](Lab07_Agentic_Node_Graph/) | 15-node `chapter11-graph-v1` DAG with `not_flagged`, `blocked`, `awaiting_mentor`, and bounded `needs_human` | `lib/chapter11/graph.ts` |
| 08 | [Lab08_Parallel_Swarm](Lab08_Parallel_Swarm/) | Snapshot-isolated `ThreadPoolExecutor` fan-out/fan-in benchmark and `merge_by_plan_alignment()` selector | `lib/db.ts` (`collectSnapshot`), `service.ts` |
| 09 | [Lab09_Deep_Research_Grounding](Lab09_Deep_Research_Grounding/) | Tagged `EvidenceBook` synthesis and `validate_packet_v2()` citation + `ROUNDING_TOLERANCE = 0.5` guard | `investigator.ts`, `packet-v2.ts`, `engine.ts` |
| 10 | [Lab10_Ops_Resilience_Self_Healing](Lab10_Ops_Resilience_Self_Healing/) | Closed-vocabulary diagnosis, surgical JSON-path patching, `MAX_REPAIRS=2`, `AI_QUOTA_WAIT` failover | `diagnosis.ts`, `provider.ts`, `faults.ts` |
| 11 | [Lab11_Agentic_SDLC_Factory](Lab11_Agentic_SDLC_Factory/) | Spec-to-artifact pipeline gated by 12 deterministic acceptance checks (`CHK-01`..`CHK-12`) + cohort corrections | `PROJECT_CONTRACT.md`, `.github/workflows/checks.yml` |
| 12 | [Lab12_Safety_And_Governance](Lab12_Safety_And_Governance/) | Allowlist `EgressFirewall`, cryptographic `MentorApprovalGate`, telemetry + replay, `withdraw()` & `rollback_restore()` | `egress.ts`, `review.ts`, `metrics.ts`, `generation.ts` |

### Labs 13–14 (Integrated System in `Course Project/Source-Code/`)
- **Lab 13 — Discipline-Specific Agents:** Implemented in `Course Project/Source-Code/platform/services/core-api/lib/chapter11/specialists.ts` (`AcademicSpecialist`, `AttendanceSpecialist`, `WellbeingReferralSpecialist`) and `lib/meetings.ts` (7-day meet / 14-day submit conversation tracking).
- **Lab 14 — Capstone Project Studio:** Full integrated 6-workspace system deployed in `Course Project/Source-Code/` (Streamlit UI + bundled Node 22 Core + Neon PostgreSQL).
