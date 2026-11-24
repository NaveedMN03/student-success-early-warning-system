# Lab 11 — Agentic SDLC Factory (`CHK-01`..`CHK-12` Automated Gate)

- **Course:** Agentic AI (`26ECAC401`) — Chapter 11: Student Success & Early Warning System (AURA)
- **Phase:** C · Applied Reliability
- **AURA Engine Mapping:** `Course Project/Source-Code/PROJECT_CONTRACT.md`, `docs/SPEC_CONFORMANCE_2026-10-16.md`, and `.github/workflows/checks.yml`

## What This Lab Demonstrates
- Implements `AuraSDLCFactory`, treating the locked plan as a formal specification and gating every output through 12 deterministic acceptance checks (`CHK-01`..`CHK-12`).
- Blocks stale (`SYN-0004`, 32-day-old LMS record) and contradictory (`SYN-0005`, conflicting attendance rows) cases from advancing to `HumanGate`, then passes them cleanly once AURA's bundled corrections are applied.

## Run
```bash
python3 Assignments/Lab11_Agentic_SDLC_Factory/lab11_agentic_sdlc_factory.py
```
