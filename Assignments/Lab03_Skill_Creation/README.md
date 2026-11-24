# Lab 03 — Skill Creation (PlanBlueprintSkill & PacketV2FormatSkill)

- **Course:** Agentic AI (`26ECAC401`) — Chapter 11: Student Success & Early Warning System (AURA)
- **Phase:** A · Foundations
- **AURA Engine Mapping:** `Course Project/Source-Code/platform/services/core-api/lib/chapter11/catalogue.ts`, `packet-v2.ts`, and `planning.ts`

## What This Lab Demonstrates
- Packages two reusable, case-agnostic skills behind typed input/output contracts (`PlanBlueprintSkill` and `PacketV2FormatSkill`).
- Enforces AURA's 7 approved `ACTION_CATALOGUE` codes, `2..5` rationale sentences (`12..320` chars), `1..4` action steps, `due_in_days` in `1..14`, and server-locked `owner="assigned_faculty"`.
- Proves the exact same skill objects execute unchanged on both `SYN-0001` (medium risk) and `SYN-0002` (high risk).

## Run
```bash
python3 Assignments/Lab03_Skill_Creation/lab03_skill_creation.py
```
