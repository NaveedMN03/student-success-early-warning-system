# Lab 04 — Memory & Retrieval (Short-Term Run State vs. Long-Term Archive)

- **Course:** Agentic AI (`26ECAC401`) — Chapter 11: Student Success & Early Warning System (AURA)
- **Phase:** A · Foundations
- **AURA Engine Mapping:** `Course Project/Source-Code/platform/services/core-api/lib/chapter11/engine.ts`, `connectors.ts`, and `streamlit_app/common.py`

## What This Lab Demonstrates
- Isolates `ShortTermRunState` (mutable draft packet, 48-entry `EvidenceBook`, stage checkpoints, 60-second write-invalidated `SessionReadCache`) from `LongTermKnowledgeStore`.
- Implements AURA's exact zero-cost `sha256-lexical-128-v1` 128-dimensional SHA-256 lexical hash vector for deterministic replay and zero PII egress.
- Filters prior interventions by department + tag intersection and anonymizes returned items to action codes and tags via `anonymous_prior_reference()`.

## Run
```bash
python3 Assignments/Lab04_Memory_And_Retrieval/lab04_memory_and_retrieval.py
```
