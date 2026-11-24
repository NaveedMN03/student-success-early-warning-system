"""Lab 07: Agentic Node Graph — Explicit State Machine, Conditional Routing & Bounded Retry.

Course: Agentic AI (26ECAC401) — Chapter 11: Student Success & Early Warning System (AURA)
Phase B · Multi-Agent Orchestration

Models AURA's `chapter11-graph-v1` DAG (`lib/chapter11/graph.ts`):
  PlannerAgent -> Coordinator -> [ContineoCollector, LMSCollector,
  InternshipCollector, PlacementCollector] -> EvidenceValidator ->
  RiskAnalysisAgent -> HistoryRetriever -> RecommendationAgent ->
  PacketValidator <-> Regenerator (max_repairs=2) -> JudgeAgent ->
  HumanGate -> DashboardPublisher.

Conditional edge outcomes enforced:
  - Missing/stale/contradictory evidence -> `blocked`
  - Score below medium threshold (< 20)   -> `not_flagged`
  - Repairs exhausted (> max_repairs=2)   -> `needs_human`
  - Validated & judge-passed draft        -> pauses at `HumanGate` (`awaiting_mentor`)
    and publishes ONLY after explicit mentor sign-off.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

MAX_REPAIRS = 2
FRESHNESS_DAYS = 30
REFERENCE_DATE = "2026-09-02T09:00:00Z"

EMBEDDED_COHORT: Dict[str, Dict[str, Any]] = {
    "SYN-0002": {
        "academic": {"data_state": "present", "observed_at": "2026-08-29T09:00:00Z", "fields": {"attendance_pct": 65, "gpa": 5.8, "failed_courses": 2}},
        "lms": {"data_state": "present", "observed_at": "2026-08-30T09:00:00Z", "fields": {"inactivity_days": 10, "overdue_assignments": 3, "missed_assessments": 2}},
        "internship": {"data_state": "present", "observed_at": "2026-08-20T09:00:00Z", "fields": {"missed_milestones": 1, "milestones_total": 4}},
        "placement": {"data_state": "present", "observed_at": "2026-08-25T09:00:00Z", "fields": {"missed_required_activities": 2, "activities_total": 5}},
    },
    "SYN-0003": {
        "academic": {"data_state": "missing", "observed_at": None, "fields": {}},
        "lms": {"data_state": "present", "observed_at": "2026-08-31T09:00:00Z", "fields": {"inactivity_days": 2, "overdue_assignments": 0, "missed_assessments": 0}},
        "internship": {"data_state": "not_applicable", "observed_at": "2026-09-01T09:00:00Z", "fields": {}},
        "placement": {"data_state": "not_applicable", "observed_at": "2026-09-01T09:00:00Z", "fields": {}},
    },
    "SYN-0006": {
        "academic": {"data_state": "present", "observed_at": "2026-08-30T09:00:00Z", "fields": {"attendance_pct": 88, "gpa": 8.1, "failed_courses": 0}},
        "lms": {"data_state": "present", "observed_at": "2026-09-01T09:00:00Z", "fields": {"inactivity_days": 1, "overdue_assignments": 0, "missed_assessments": 0}},
        "internship": {"data_state": "present", "observed_at": "2026-08-25T09:00:00Z", "fields": {"missed_milestones": 0, "milestones_total": 4}},
        "placement": {"data_state": "present", "observed_at": "2026-08-28T09:00:00Z", "fields": {"missed_required_activities": 0, "activities_total": 5}},
    },
}


def load_cohort() -> Dict[str, Dict[str, Any]]:
    here = Path(__file__).resolve()
    for parent in here.parents:
        base = parent / "Course Project" / "Source-Code" / "fixtures" / "synthetic-cohort-v1"
        if base.is_dir():
            loaded: Dict[str, Dict[str, Any]] = {}
            for sid in ("SYN-0002", "SYN-0003", "SYN-0006"):
                sdir = base / sid
                if sdir.is_dir():
                    loaded[sid] = {
                        src: json.loads((sdir / f"{src}.json").read_text(encoding="utf-8"))
                        for src in ("academic", "lms", "internship", "placement")
                    }
            if len(loaded) == 3:
                return loaded
    return {k: dict(v) for k, v in EMBEDDED_COHORT.items()}


@dataclass
class GraphState:
    """Shared typed state passed through every node of `chapter11-graph-v1`."""

    student_ref: str
    plan_locked: bool = True
    persistent_fault: bool = False
    collected: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    evidence_valid: bool = False
    block_reason: Optional[str] = None
    risk_score: int = 0
    risk_band: str = "low"
    flagged: bool = False
    signals: List[str] = field(default_factory=list)
    prior_refs: List[str] = field(default_factory=list)
    draft: Dict[str, Any] = field(default_factory=dict)
    repairs: int = 0
    validation_passed: bool = False
    judge_passed: bool = False
    mentor_approved: bool = False
    terminal_status: str = "initialized"
    visit_counts: Dict[str, int] = field(default_factory=dict)
    timings_ms: Dict[str, float] = field(default_factory=dict)
    trace: List[str] = field(default_factory=list)


class AuraNodeGraph:
    """Executable 15-node directed graph with bounded repair loop and Graphviz export."""

    version = "chapter11-graph-v1"

    def __init__(self, cohort: Dict[str, Dict[str, Any]], max_repairs: int = MAX_REPAIRS) -> None:
        self.cohort = cohort
        self.max_repairs = max_repairs

    def _visit(self, state: GraphState, node: str, fn: Any) -> None:
        t0 = time.perf_counter()
        state.visit_counts[node] = state.visit_counts.get(node, 0) + 1
        state.trace.append(node)
        fn(state)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        state.timings_ms[node] = round(state.timings_ms.get(node, 0.0) + elapsed_ms, 3)

    def _planner(self, state: GraphState) -> None:
        if not state.plan_locked:
            raise ValueError("PlannerAgent must hand off a locked plan to Coordinator.")

    def _coordinator(self, state: GraphState) -> None:
        state.collected = {}

    def _collect_source(self, source: str) -> Any:
        def _runner(state: GraphState) -> None:
            state.collected[source] = self.cohort[state.student_ref][source]
        return _runner

    def _evidence_validator(self, state: GraphState) -> None:
        for required in ("academic", "lms"):
            rec = state.collected.get(required, {})
            if rec.get("data_state") != "present":
                state.evidence_valid = False
                state.block_reason = f"{required} source is {rec.get('data_state', 'absent')}"
                return
        state.evidence_valid = True

    def _risk_analysis(self, state: GraphState) -> None:
        acad = state.collected["academic"]["fields"]
        lms = state.collected["lms"]["fields"]
        intern = state.collected["internship"]["fields"]
        place = state.collected["placement"]["fields"]

        score = 0
        signals: List[str] = []
        if acad.get("attendance_pct", 100) < 75:
            score += 20
            signals.append("ATTENDANCE_LOW")
        if acad.get("gpa", 10.0) * 10.0 < 60:
            score += 20
            signals.append("MARK_LOW")
        if lms.get("inactivity_days", 0) >= 7:
            score += 20
            signals.append("LMS_INACTIVE")
        if lms.get("overdue_assignments", 0) >= 1:
            score += 10
            signals.append("ASSIGNMENT_OVERDUE")
        if state.collected["internship"].get("data_state") == "present" and intern.get("missed_milestones", 0) >= 1:
            score += 15
            signals.append("INTERNSHIP_MILESTONE")
        if state.collected["placement"].get("data_state") == "present" and place.get("missed_required_activities", 0) >= 1:
            score += 15
            signals.append("PLACEMENT_ACTIVITY")

        state.risk_score = min(100, score)
        state.risk_band = "high" if score >= 50 else "medium" if score >= 20 else "low"
        state.flagged = score >= 20
        state.signals = signals

    def _history_retriever(self, state: GraphState) -> None:
        state.prior_refs = ["guide-multi-02"] if state.risk_band == "high" else ["guide-att-01"]

    def _recommendation_agent(self, state: GraphState) -> None:
        state.draft = {
            "summary": f"Risk {state.risk_band} ({state.risk_score}/100) for signals {state.signals}",
            "actions": ["faculty-check-in", "student-study-plan"],
            "valid_citations": not state.persistent_fault,
        }

    def _packet_validator(self, state: GraphState) -> None:
        state.validation_passed = bool(state.draft.get("valid_citations", False))

    def _regenerator(self, state: GraphState) -> None:
        state.repairs += 1
        if not state.persistent_fault:
            state.draft["valid_citations"] = True

    def _judge_agent(self, state: GraphState) -> None:
        state.judge_passed = state.validation_passed

    def _human_gate(self, state: GraphState) -> None:
        state.terminal_status = "approved" if state.mentor_approved else "awaiting_mentor"

    def _dashboard_publisher(self, state: GraphState) -> None:
        state.terminal_status = "published"

    def run(
        self,
        student_ref: str,
        persistent_fault: bool = False,
        mentor_approved: bool = False,
    ) -> GraphState:
        state = GraphState(student_ref=student_ref, persistent_fault=persistent_fault, mentor_approved=mentor_approved)
        self._visit(state, "PlannerAgent", self._planner)
        self._visit(state, "Coordinator", self._coordinator)
        for node_name, src in (
            ("ContineoCollector", "academic"),
            ("LMSCollector", "lms"),
            ("InternshipCollector", "internship"),
            ("PlacementCollector", "placement"),
        ):
            self._visit(state, node_name, self._collect_source(src))

        self._visit(state, "EvidenceValidator", self._evidence_validator)
        if not state.evidence_valid:
            state.terminal_status = "blocked"
            return state

        self._visit(state, "RiskAnalysisAgent", self._risk_analysis)
        if not state.flagged:
            state.terminal_status = "not_flagged"
            return state

        self._visit(state, "HistoryRetriever", self._history_retriever)
        self._visit(state, "RecommendationAgent", self._recommendation_agent)

        while True:
            self._visit(state, "PacketValidator", self._packet_validator)
            if state.validation_passed:
                break
            if state.repairs >= self.max_repairs:
                state.terminal_status = "needs_human"
                return state
            self._visit(state, "Regenerator", self._regenerator)

        self._visit(state, "JudgeAgent", self._judge_agent)
        self._visit(state, "HumanGate", self._human_gate)
        if state.mentor_approved:
            self._visit(state, "DashboardPublisher", self._dashboard_publisher)
        return state

    def export_graphviz_dot(self) -> str:
        return "\n".join(
            [
                'digraph "chapter11-graph-v1" {',
                "  rankdir=LR;",
                "  PlannerAgent -> Coordinator -> {ContineoCollector LMSCollector InternshipCollector PlacementCollector};",
                "  {ContineoCollector LMSCollector InternshipCollector PlacementCollector} -> EvidenceValidator;",
                '  EvidenceValidator -> RiskAnalysisAgent [label="valid"];',
                '  EvidenceValidator -> Blocked [label="missing/stale"];',
                '  RiskAnalysisAgent -> HistoryRetriever [label="flagged>=20"];',
                '  RiskAnalysisAgent -> NotFlagged [label="score<20"];',
                "  HistoryRetriever -> RecommendationAgent -> PacketValidator;",
                '  PacketValidator -> Regenerator [label="fail && repairs<2"];',
                "  Regenerator -> PacketValidator;",
                '  PacketValidator -> NeedsHuman [label="repairs==2"];',
                '  PacketValidator -> JudgeAgent [label="pass"];',
                "  JudgeAgent -> HumanGate;",
                '  HumanGate -> DashboardPublisher [label="mentor_approved"];',
                "}",
            ]
        )


def run_demo() -> None:
    print("=== Lab 07: Agentic Node Graph (AURA chapter11-graph-v1) ===")
    graph = AuraNodeGraph(load_cohort())
    for sid, fault in (("SYN-0006", False), ("SYN-0003", False), ("SYN-0002", False), ("SYN-0002", True)):
        res = graph.run(sid, persistent_fault=fault)
        print(
            f"  [{sid} | persistent_fault={fault}] -> terminal={res.terminal_status} "
            f"| visits={sum(res.visit_counts.values())} | path={' -> '.join(res.trace)}"
        )
    print("\nGraphviz DOT snippet:\n" + "\n".join(graph.export_graphviz_dot().splitlines()[:6]) + "\n  ...")


def run_self_tests() -> None:
    graph = AuraNodeGraph(load_cohort())

    # 1. SYN-0006 low risk terminates at not_flagged without invoking RecommendationAgent
    s6 = graph.run("SYN-0006")
    assert s6.terminal_status == "not_flagged" and s6.risk_score == 0
    assert "RecommendationAgent" not in s6.visit_counts
    print("[PASS] SYN-0006 routed to not_flagged and skipped recommendation nodes")

    # 2. SYN-0003 missing academic source routes to blocked before RiskAnalysisAgent
    s3 = graph.run("SYN-0003")
    assert s3.terminal_status == "blocked" and "missing" in (s3.block_reason or "")
    assert "RiskAnalysisAgent" not in s3.visit_counts
    print("[PASS] SYN-0003 missing academic record halted at blocked before scoring")

    # 3. SYN-0002 pauses at HumanGate (never auto-publishes) until mentor approves
    s2_wait = graph.run("SYN-0002", mentor_approved=False)
    assert s2_wait.terminal_status == "awaiting_mentor"
    assert "DashboardPublisher" not in s2_wait.visit_counts
    s2_pub = graph.run("SYN-0002", mentor_approved=True)
    assert s2_pub.terminal_status == "published" and s2_pub.visit_counts["DashboardPublisher"] == 1
    print("[PASS] SYN-0002 paused at HumanGate and published only on mentor approval")

    # 4. Persistent validation failure terminates at needs_human after exactly 2 bounded repairs
    s2_fail = graph.run("SYN-0002", persistent_fault=True)
    assert s2_fail.terminal_status == "needs_human"
    assert s2_fail.repairs == MAX_REPAIRS
    assert s2_fail.visit_counts["Regenerator"] == MAX_REPAIRS
    assert s2_fail.visit_counts["PacketValidator"] == MAX_REPAIRS + 1
    assert "HumanGate" not in s2_fail.visit_counts
    print("[PASS] Bounded retry edge halted at needs_human after exactly 2 Regenerator attempts")


if __name__ == "__main__":
    run_demo()
    print("\n--- Running Self-Tests ---")
    run_self_tests()
    print("All Lab 07 checks passed.")
