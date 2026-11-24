# Lab 01 — Agent vs. Chatbot (AURA Planner Loop)

- **Course:** Agentic AI (`26ECAC401`) — Chapter 11: Student Success & Early Warning System (AURA)
- **Phase:** A · Foundations
- **AURA Engine Mapping:** `Course Project/Source-Code/platform/services/core-api/lib/chapter11/planner.ts` and `planning.ts`

## What This Lab Demonstrates
- Contrasts a stateless `OneShotChatbot` (which guesses numbers and replies immediately) against the stateful `AuraPlannerAgent` (`clarifying -> ready -> locked`).
- Enforces `ground_criteria()` to strip hallucinated numeric filters absent from both mentor prompt text and the signed `CH11-DEMO-1` policy.
- Deduplicates clarifying questions with token Jaccard similarity (`>= 0.5`).
- Preserves explicit `selected_students` scope as authoritative via `ScopeConflict` prompts rather than silently widening scope.
- Restricts `lock_plan()` to the owning mentor and seals the plan with a SHA-256 `plan_hash`.

## Run
```bash
python3 Assignments/Lab01_Agent_Vs_Chatbot/lab01_agent_vs_chatbot.py
```
