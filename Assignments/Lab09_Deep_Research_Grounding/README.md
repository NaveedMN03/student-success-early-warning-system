# Lab 09 — Deep Research & Grounding (`EvidenceBook` & `validate_packet_v2`)

- **Course:** Agentic AI (`26ECAC401`) — Chapter 11: Student Success & Early Warning System (AURA)
- **Phase:** C · Applied Reliability
- **AURA Engine Mapping:** `Course Project/Source-Code/platform/services/core-api/lib/chapter11/investigator.ts`, `packet-v2.ts`, and `engine.ts`

## What This Lab Demonstrates
- Constructs an indexed `EvidenceBook` (`ev-1..ev-N`) from `SYN-0002`'s 4 institutional records (`academic`, `lms`, `internship`, `placement`) with provenance IDs and policy thresholds.
- Enforces AURA's `ROUNDING_TOLERANCE = 0.5`, rejecting uncited sentences (`UNCITED_CLAIM`), fabricated numbers (`UNSUPPORTED_NUMBER`), missing triggers (`MISSING_TRIGGER_COVERAGE`), and cross-student scope leaks (`PRIVACY_SCOPE_MISMATCH`).

## Run
```bash
python3 Assignments/Lab09_Deep_Research_Grounding/lab09_deep_research_grounding.py
```
