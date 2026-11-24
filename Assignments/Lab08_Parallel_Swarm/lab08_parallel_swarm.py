"""Lab 08: Parallel Swarm — Concurrent Fan-Out/Fan-In & Plan-Aligned Merge.

Course: Agentic AI (26ECAC401) — Chapter 11: Student Success & Early Warning System (AURA)
Phase B · Multi-Agent Orchestration

Demonstrates AURA's snapshot-isolated parallel fan-out/fan-in (`lib/db.ts`
`collectSnapshot()` and `service.ts` `parallelMap`):
  1. Exports one consistent cohort snapshot ID (`snap-...`) so parallel collectors
     cannot observe time-skew between sources.
  2. Executes the 4 source collectors concurrently per student AND fans out across
     all 6 cohort students (`SYN-0001..SYN-0006`) via `ThreadPoolExecutor`.
  3. Benchmarks sequential vs. parallel execution, verifying identical outputs at
     lower wall-clock latency.
  4. Implements `merge_by_plan_alignment()`, which picks the candidate draft that
     strictly satisfies locked-plan scope, trigger coverage, catalogue constraints,
     and grounded citations — rejecting an eloquent out-of-scope decoy.
"""

from __future__ import annotations

import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

SOURCE_IO_DELAY_SEC = 0.03  # 30ms simulated read latency per source call

ACTION_CATALOGUE = {
    "faculty-check-in",
    "student-study-plan",
    "attendance-review",
    "lms-catch-up",
    "internship-review",
    "placement-review",
    "wellbeing-referral",
}

EMBEDDED_COHORT: Dict[str, Dict[str, Any]] = {
    "SYN-0001": {
        "academic": {"data_state": "present", "observed_at": "2026-08-28T09:00:00Z", "fields": {"attendance_pct": 72, "gpa": 7.2}},
        "lms": {"data_state": "present", "observed_at": "2026-08-31T09:00:00Z", "fields": {"inactivity_days": 3, "overdue_assignments": 1}},
        "internship": {"data_state": "not_applicable", "observed_at": "2026-09-01T09:00:00Z", "fields": {}},
        "placement": {"data_state": "not_applicable", "observed_at": "2026-09-01T09:00:00Z", "fields": {}},
    },
    "SYN-0002": {
        "academic": {"data_state": "present", "observed_at": "2026-08-29T09:00:00Z", "fields": {"attendance_pct": 65, "gpa": 5.8}},
        "lms": {"data_state": "present", "observed_at": "2026-08-30T09:00:00Z", "fields": {"inactivity_days": 10, "overdue_assignments": 3}},
        "internship": {"data_state": "present", "observed_at": "2026-08-20T09:00:00Z", "fields": {"missed_milestones": 1}},
        "placement": {"data_state": "present", "observed_at": "2026-08-25T09:00:00Z", "fields": {"missed_required_activities": 2}},
    },
    "SYN-0003": {
        "academic": {"data_state": "missing", "observed_at": None, "fields": {}},
        "lms": {"data_state": "present", "observed_at": "2026-08-31T09:00:00Z", "fields": {"inactivity_days": 2, "overdue_assignments": 0}},
        "internship": {"data_state": "not_applicable", "observed_at": "2026-09-01T09:00:00Z", "fields": {}},
        "placement": {"data_state": "not_applicable", "observed_at": "2026-09-01T09:00:00Z", "fields": {}},
    },
    "SYN-0004": {
        "academic": {"data_state": "present", "observed_at": "2026-08-29T09:00:00Z", "fields": {"attendance_pct": 81, "gpa": 7.8}},
        "lms": {"data_state": "present", "observed_at": "2026-08-01T09:00:00Z", "fields": {"inactivity_days": 1, "overdue_assignments": 0}},
        "internship": {"data_state": "not_applicable", "observed_at": "2026-09-01T09:00:00Z", "fields": {}},
        "placement": {"data_state": "not_applicable", "observed_at": "2026-09-01T09:00:00Z", "fields": {}},
    },
    "SYN-0005": {
        "academic": {"data_state": "contradictory", "observed_at": "2026-08-30T09:00:00Z", "fields": {"attendance_pct_values": [68, 82], "gpa": 7.0}},
        "lms": {"data_state": "present", "observed_at": "2026-08-31T09:00:00Z", "fields": {"inactivity_days": 2, "overdue_assignments": 0}},
        "internship": {"data_state": "not_applicable", "observed_at": "2026-09-01T09:00:00Z", "fields": {}},
        "placement": {"data_state": "not_applicable", "observed_at": "2026-09-01T09:00:00Z", "fields": {}},
    },
    "SYN-0006": {
        "academic": {"data_state": "present", "observed_at": "2026-08-30T09:00:00Z", "fields": {"attendance_pct": 88, "gpa": 8.1}},
        "lms": {"data_state": "present", "observed_at": "2026-09-01T09:00:00Z", "fields": {"inactivity_days": 1, "overdue_assignments": 0}},
        "internship": {"data_state": "present", "observed_at": "2026-08-25T09:00:00Z", "fields": {"missed_milestones": 0}},
        "placement": {"data_state": "present", "observed_at": "2026-08-28T09:00:00Z", "fields": {"missed_required_activities": 0}},
    },
}


def load_cohort() -> Dict[str, Dict[str, Any]]:
    here = Path(__file__).resolve()
    for parent in here.parents:
        base = parent / "Course Project" / "Source-Code" / "fixtures" / "synthetic-cohort-v1"
        if base.is_dir():
            loaded: Dict[str, Dict[str, Any]] = {}
            for sid in sorted(EMBEDDED_COHORT.keys()):
                sdir = base / sid
                if sdir.is_dir():
                    loaded[sid] = {
                        src: json.loads((sdir / f"{src}.json").read_text(encoding="utf-8"))
                        for src in ("academic", "lms", "internship", "placement")
                    }
            if len(loaded) == len(EMBEDDED_COHORT):
                return loaded
    return {k: dict(v) for k, v in EMBEDDED_COHORT.items()}


@dataclass(frozen=True)
class StudentOutcome:
    student_ref: str
    snapshot_id: str
    status: str
    score: int
    band: str
    signal_codes: Tuple[str, ...]


@dataclass(frozen=True)
class DraftCandidate:
    worker_id: str
    target_student: str
    cited_triggers: Tuple[str, ...]
    action_codes: Tuple[str, ...]
    has_evidence_citations: bool
    prose: str


def _evaluate_student_bundle(student_ref: str, snapshot_id: str, bundle: Dict[str, Dict[str, Any]]) -> StudentOutcome:
    acad = bundle["academic"]
    lms = bundle["lms"]
    if acad["data_state"] != "present" or lms["data_state"] != "present":
        return StudentOutcome(student_ref, snapshot_id, f"blocked:{acad['data_state']}", 0, "low", ())
    if str(lms.get("observed_at", "")).startswith("2026-08-01"):
        return StudentOutcome(student_ref, snapshot_id, "blocked:stale_lms", 0, "low", ())

    score = 0
    signals: List[str] = []
    af, lf = acad["fields"], lms["fields"]
    if af.get("attendance_pct", 100) < 75:
        score += 20
        signals.append("ATTENDANCE_LOW")
    if af.get("gpa", 10.0) * 10.0 < 60:
        score += 20
        signals.append("MARK_LOW")
    if lf.get("inactivity_days", 0) >= 7:
        score += 20
        signals.append("LMS_INACTIVE")
    if lf.get("overdue_assignments", 0) >= 1:
        score += 10
        signals.append("ASSIGNMENT_OVERDUE")
    if bundle["internship"]["data_state"] == "present" and bundle["internship"]["fields"].get("missed_milestones", 0) >= 1:
        score += 15
        signals.append("INTERNSHIP_MILESTONE")
    if bundle["placement"]["data_state"] == "present" and bundle["placement"]["fields"].get("missed_required_activities", 0) >= 1:
        score += 15
        signals.append("PLACEMENT_ACTIVITY")

    band = "high" if score >= 50 else "medium" if score >= 20 else "low"
    status = "flagged" if score >= 20 else "not_flagged"
    return StudentOutcome(student_ref, snapshot_id, status, min(100, score), band, tuple(signals))


class ParallelCohortSwarm:
    """Runs deterministic snapshot reads either sequentially or via parallel fan-out/fan-in."""

    def __init__(self, cohort: Dict[str, Dict[str, Any]], source_delay_sec: float = SOURCE_IO_DELAY_SEC) -> None:
        self.cohort = cohort
        self.source_delay_sec = source_delay_sec

    def _export_snapshot_id(self) -> str:
        digest = hashlib.sha256(json.dumps(self.cohort, sort_keys=True).encode("utf-8")).hexdigest()[:12]
        return f"snap-{digest}"

    def _read_source(self, student_ref: str, source: str) -> Tuple[str, Dict[str, Any]]:
        if self.source_delay_sec > 0:
            time.sleep(self.source_delay_sec)
        return source, self.cohort[student_ref][source]

    def run_sequential(self) -> Tuple[List[StudentOutcome], float]:
        snap_id = self._export_snapshot_id()
        t0 = time.perf_counter()
        outcomes: List[StudentOutcome] = []
        for sid in sorted(self.cohort.keys()):
            bundle: Dict[str, Dict[str, Any]] = {}
            for src in ("academic", "lms", "internship", "placement"):
                name, payload = self._read_source(sid, src)
                bundle[name] = payload
            outcomes.append(_evaluate_student_bundle(sid, snap_id, bundle))
        return outcomes, (time.perf_counter() - t0) * 1000.0

    def run_parallel(self) -> Tuple[List[StudentOutcome], float]:
        snap_id = self._export_snapshot_id()
        t0 = time.perf_counter()

        def process_one(sid: str) -> StudentOutcome:
            with ThreadPoolExecutor(max_workers=4) as source_pool:
                futures = [source_pool.submit(self._read_source, sid, src) for src in ("academic", "lms", "internship", "placement")]
                bundle = dict(f.result() for f in futures)
            return _evaluate_student_bundle(sid, snap_id, bundle)

        with ThreadPoolExecutor(max_workers=len(self.cohort)) as student_pool:
            outcomes = list(student_pool.map(process_one, sorted(self.cohort.keys())))

        outcomes.sort(key=lambda o: o.student_ref)
        return outcomes, (time.perf_counter() - t0) * 1000.0


def score_plan_alignment(
    candidate: DraftCandidate,
    locked_student: str,
    required_triggers: Tuple[str, ...],
) -> Tuple[int, List[str]]:
    """Score candidate strictly by alignment to the locked plan and trigger coverage."""
    score = 0
    notes: List[str] = []
    if candidate.target_student == locked_student:
        score += 30
    else:
        notes.append("wrong_scope")

    req_set = set(required_triggers)
    covered = req_set & set(candidate.cited_triggers)
    if req_set and covered == req_set:
        score += 40
    else:
        score += int(40 * (len(covered) / max(1, len(req_set))))
        notes.append("incomplete_trigger_coverage")

    if candidate.action_codes and all(code in ACTION_CATALOGUE for code in candidate.action_codes):
        score += 20
    else:
        notes.append("invalid_catalogue_code")

    if candidate.has_evidence_citations:
        score += 10
    else:
        notes.append("missing_citations")

    return score, notes


def merge_by_plan_alignment(
    candidates: List[DraftCandidate],
    locked_student: str,
    required_triggers: Tuple[str, ...],
) -> Tuple[DraftCandidate, List[Tuple[str, int, List[str]]]]:
    """Deterministic fan-in selector picking highest plan-aligned candidate."""
    scored: List[Tuple[int, str, DraftCandidate, List[str]]] = []
    for cand in candidates:
        s, notes = score_plan_alignment(cand, locked_student, required_triggers)
        scored.append((s, cand.worker_id, cand, notes))
    scored.sort(key=lambda item: (-item[0], item[1]))
    winner = scored[0][2]
    scoreboard = [(item[1], item[0], item[3]) for item in scored]
    return winner, scoreboard


def run_demo() -> None:
    print("=== Lab 08: Parallel Swarm (Snapshot Fan-Out/Fan-In & Plan-Aligned Merge) ===")
    swarm = ParallelCohortSwarm(load_cohort())
    seq_res, seq_ms = swarm.run_sequential()
    par_res, par_ms = swarm.run_parallel()
    print(f"Benchmark across {len(par_res)} students (4 sources each): sequential={seq_ms:.1f}ms vs parallel={par_ms:.1f}ms")
    for item in par_res:
        print(f"  {item.student_ref} ({item.snapshot_id}): status={item.status} score={item.score} band={item.band}")

    candidates = [
        DraftCandidate(
            worker_id="worker-eloquent-decoy",
            target_student="SYN-0002",  # wrong scope when locked plan is SYN-0001
            cited_triggers=("ATTENDANCE_LOW",),
            action_codes=("faculty-check-in",),
            has_evidence_citations=False,
            prose="Highly polished narrative without citations targeting another student.",
        ),
        DraftCandidate(
            worker_id="worker-aligned",
            target_student="SYN-0001",
            cited_triggers=("ATTENDANCE_LOW", "ASSIGNMENT_OVERDUE"),
            action_codes=("attendance-review", "lms-catch-up"),
            has_evidence_citations=True,
            prose="Attendance is 72% (<75%) [ev-1] and 1 overdue LMS assignment (>=1) [ev-2].",
        ),
    ]
    winner, board = merge_by_plan_alignment(candidates, "SYN-0001", ("ATTENDANCE_LOW", "ASSIGNMENT_OVERDUE"))
    print(f"\nMerge selector winner: {winner.worker_id} | Scoreboard: {board}")


def run_self_tests() -> None:
    swarm = ParallelCohortSwarm(load_cohort())
    seq_res, seq_ms = swarm.run_sequential()
    par_res, par_ms = swarm.run_parallel()

    # 1. Sequential and parallel outcomes are byte-identical across all 6 cohort students
    assert seq_res == par_res
    assert len(par_res) == 6
    print("[PASS] Parallel fan-out produced identical StudentOutcome records across all 6 cohort students")

    # 2. Parallel execution completes strictly faster than sequential execution
    assert par_ms < seq_ms, f"Expected parallel ({par_ms:.1f}ms) < sequential ({seq_ms:.1f}ms)"
    print(f"[PASS] Parallel wall-clock ({par_ms:.1f}ms) beat sequential ({seq_ms:.1f}ms)")

    # 3. Plan-aligned merge rejects eloquent out-of-scope/uncited decoy
    decoy = DraftCandidate(
        worker_id="worker-decoy",
        target_student="SYN-0002",
        cited_triggers=("ATTENDANCE_LOW",),
        action_codes=("custom-unapproved",),
        has_evidence_citations=False,
        prose="Very eloquent prose with wrong scope and no citations.",
    )
    aligned = DraftCandidate(
        worker_id="worker-aligned",
        target_student="SYN-0001",
        cited_triggers=("ATTENDANCE_LOW", "ASSIGNMENT_OVERDUE"),
        action_codes=("attendance-review", "lms-catch-up"),
        has_evidence_citations=True,
        prose="Attendance 72% [ev-1] and 1 overdue task [ev-2].",
    )
    winner, _ = merge_by_plan_alignment([decoy, aligned], "SYN-0001", ("ATTENDANCE_LOW", "ASSIGNMENT_OVERDUE"))
    assert winner.worker_id == "worker-aligned"
    print("[PASS] merge_by_plan_alignment selected aligned grounded candidate over eloquent decoy")


if __name__ == "__main__":
    run_demo()
    print("\n--- Running Self-Tests ---")
    run_self_tests()
    print("All Lab 08 checks passed.")
