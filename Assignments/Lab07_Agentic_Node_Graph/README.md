# Lab 07 — Agentic Node Graph (`chapter11-graph-v1`)

- **Course:** Agentic AI (`26ECAC401`) — Chapter 11: Student Success & Early Warning System (AURA)
- **Phase:** B · Multi-Agent Orchestration
- **AURA Engine Mapping:** `Course Project/Source-Code/platform/services/core-api/lib/chapter11/graph.ts`

## What This Lab Demonstrates
- Implements AURA's explicit 15-node directed graph (`PlannerAgent` -> `Coordinator` -> 4 Collectors -> `EvidenceValidator` -> `RiskAnalysisAgent` -> `HistoryRetriever` -> `RecommendationAgent` -> `PacketValidator` <-> `Regenerator` -> `JudgeAgent` -> `HumanGate` -> `DashboardPublisher`).
- Routes all 4 branch states deterministically: `not_flagged` (`SYN-0006`), `blocked` (`SYN-0003`), `awaiting_mentor` (`SYN-0002`), and `needs_human` after exactly `max_repairs=2` retries.
- Records per-node visit counts, millisecond timings, and exports Graphviz DOT notation.

## Run
```bash
python3 Assignments/Lab07_Agentic_Node_Graph/lab07_agentic_node_graph.py
```
