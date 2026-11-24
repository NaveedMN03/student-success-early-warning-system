"""Lab 01: Agent vs. Chatbot — Stateful AURA Planner Loop.

Course: Agentic AI (26ECAC401) — Chapter 11: Student Success & Early Warning System (AURA)
Phase A · Foundations

Demonstrates why an agentic planner (Plan -> Act -> Observe -> Revise -> Lock)
differs from a stateless one-shot chatbot:
  - Clarifies ambiguous mentor requests instead of guessing.
  - Deduplicates questions using Jaccard similarity (>= 0.5) across turns.
  - Grounds filter criteria against mentor prompt text and faculty-set policy
    thresholds via `ground_criteria()`, stripping hallucinated numbers.
  - Treats the mentor's explicit `selected_students` scope as authoritative and
    surfaces explicit `scope_conflict` keep-vs-switch choices instead of silent drift.
  - Separates drafting from locking: only a mentor can lock the final plan with an
    immutable SHA-256 `plan_hash`.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

POLICY_DEFAULTS: Dict[str, Any] = {
    "version": "CH11-DEMO-1",
    "attendanceMinimum": 75,
    "markMinimum": 60,
    "inactivityMaximum": 7,
    "mediumScore": 20,
    "highScore": 50,
    "freshnessDays": 30,
}

EMBEDDED_ROSTER: List[Dict[str, str]] = [
    {"student_ref": "SYN-0001", "section": "A", "mentor_id": "mentor-01"},
    {"student_ref": "SYN-0002", "section": "A", "mentor_id": "mentor-01"},
    {"student_ref": "SYN-0003", "section": "A", "mentor_id": "mentor-01"},
    {"student_ref": "SYN-0004", "section": "B", "mentor_id": "mentor-02"},
    {"student_ref": "SYN-0005", "section": "B", "mentor_id": "mentor-02"},
    {"student_ref": "SYN-0006", "section": "B", "mentor_id": "mentor-02"},
]

CLARIFYING_TEMPLATES: Dict[str, str] = {
    "scope": "Which students should be in scope: your pre-selected list or your whole mentee section?",
    "focus": "Should the review focus on academic marks, attendance, LMS activity, or all risk signals?",
    "policy": "Confirm faculty policy CH11-DEMO-1 (attendance < 75%, marks < 60%) or specify a signed variant?",
}


def load_cohort_roster() -> List[Dict[str, str]]:
    """Load synthetic cohort roster from repo fixtures if present, else embedded copy."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        fixture_dir = parent / "Course Project" / "Source-Code" / "fixtures" / "synthetic-cohort-v1"
        if fixture_dir.is_dir():
            roster: List[Dict[str, str]] = []
            for entry in sorted(fixture_dir.iterdir()):
                if entry.is_dir() and entry.name.startswith("SYN-"):
                    idx = int(entry.name.split("-")[1])
                    roster.append(
                        {
                            "student_ref": entry.name,
                            "section": "A" if idx <= 3 else "B",
                            "mentor_id": "mentor-01" if idx <= 3 else "mentor-02",
                        }
                    )
            if roster:
                return roster
    return list(EMBEDDED_ROSTER)


class PlanStatus(str, Enum):
    CLARIFYING = "clarifying"
    READY = "ready"
    LOCKED = "locked"


@dataclass
class ScopeConflict:
    """Explicit conflict when prompt text disagrees with mentor's UI selection."""

    authoritative_selected: List[str]
    prompt_suggested: List[str]
    resolved: bool = False
    resolution: Optional[str] = None
    message: str = ""


@dataclass
class PlanDraft:
    """Structured review plan produced by the iterative AURA planner."""

    plan_id: str
    mentor_id: str
    raw_request: str
    status: PlanStatus
    selected_students: List[str]
    filters: Dict[str, Any]
    focus_signals: List[str]
    policy_version: str
    asked_questions: List[str] = field(default_factory=list)
    pending_questions: List[str] = field(default_factory=list)
    answered_history: List[Tuple[str, str]] = field(default_factory=list)
    stripped_hallucinations: List[str] = field(default_factory=list)
    scope_conflict: Optional[ScopeConflict] = None
    revision: int = 1
    plan_hash: Optional[str] = None


class OneShotChatbot:
    """Anti-pattern baseline: single-turn stateless response with ungrounded guesses."""

    def respond(self, mentor_request: str) -> Dict[str, Any]:
        return {
            "mode": "chatbot_one_shot",
            "warning": "Does not clarify ambiguity, verify scope, or lock a reproducible plan.",
            "reply": (
                f"Auto-drafted alerts for '{mentor_request}': flagged students below 68% "
                "attendance and scheduled emails directly."
            ),
            "asked_questions": [],
            "scope_verified": False,
        }


def tokenize(text: str) -> Set[str]:
    """Lowercase alphanumeric tokenization for Jaccard similarity checks."""
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def jaccard_similarity(text_a: str, text_b: str) -> float:
    """Compute token-level Jaccard similarity in [0.0, 1.0]."""
    tokens_a = tokenize(text_a)
    tokens_b = tokenize(text_b)
    if not tokens_a and not tokens_b:
        return 1.0
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


def extract_numbers(text: str) -> Set[float]:
    """Extract numeric literals stated explicitly in mentor or answer text."""
    return {float(match) for match in re.findall(r"\b\d+(?:\.\d+)?\b", text)}


def ground_criteria(
    mentor_and_answers_text: str,
    proposed_filters: Dict[str, Any],
    policy: Dict[str, Any],
) -> Tuple[Dict[str, Any], List[str]]:
    """Strip numeric filter thresholds not grounded in mentor text or signed policy.

    Prevents an LLM planner from inventing arbitrary cutoffs (for example
    `attendanceBelowPct=68` when policy sets 75 and the mentor never wrote 68).
    """
    explicit_numbers = extract_numbers(mentor_and_answers_text)
    policy_numbers = {
        float(v)
        for v in policy.values()
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    }
    allowed_numbers = explicit_numbers | policy_numbers

    grounded: Dict[str, Any] = {}
    stripped: List[str] = []
    for key, value in proposed_filters.items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if float(value) in allowed_numbers:
                grounded[key] = value
            else:
                stripped.append(f"{key}={value} (ungrounded numeric filter)")
        else:
            grounded[key] = value
    return grounded, stripped


class AuraPlannerAgent:
    """Stateful Plan -> Act -> Observe -> Revise agent modeled on AURA planner.ts."""

    def __init__(
        self,
        roster: Optional[List[Dict[str, str]]] = None,
        policy: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.roster = roster if roster is not None else load_cohort_roster()
        self.policy = policy if policy is not None else dict(POLICY_DEFAULTS)

    def _mentees_for(self, mentor_id: str) -> List[str]:
        return [row["student_ref"] for row in self.roster if row["mentor_id"] == mentor_id]

    def _infer_prompt_students(self, text: str, mentor_id: str) -> List[str]:
        explicit_ids = sorted(set(re.findall(r"SYN-\d{4}", text.upper())))
        if explicit_ids:
            return explicit_ids
        lowered = text.lower()
        if "all my" in lowered or "whole cohort" in lowered or "all section" in lowered or "everyone" in lowered:
            return self._mentees_for(mentor_id)
        return []

    def _infer_focus(self, text: str) -> List[str]:
        lowered = text.lower()
        focus: List[str] = []
        if any(word in lowered for word in ("attendance", "absent", "shortage")):
            focus.append("attendance")
        if any(word in lowered for word in ("mark", "gpa", "academic", "grade", "exam")):
            focus.append("academic")
        if any(word in lowered for word in ("lms", "assignment", "overdue", "inactiv")):
            focus.append("lms")
        if "all" in lowered and ("signal" in lowered or "risk" in lowered):
            return ["academic", "attendance", "lms", "internship", "placement"]
        return focus

    def _deduplicate_questions(
        self,
        candidates: List[str],
        asked_history: List[str],
        threshold: float = 0.5,
    ) -> List[str]:
        fresh: List[str] = []
        for candidate in candidates:
            if any(jaccard_similarity(candidate, prev) >= threshold for prev in asked_history):
                continue
            fresh.append(candidate)
        return fresh

    def start_plan(
        self,
        plan_id: str,
        mentor_id: str,
        raw_request: str,
        selected_students: Optional[List[str]] = None,
        proposed_filters: Optional[Dict[str, Any]] = None,
    ) -> PlanDraft:
        """Create an initial plan draft; clarify missing scope, focus, or policy."""
        mentees = set(self._mentees_for(mentor_id))
        selected = [s for s in (selected_students or []) if s in mentees]
        prompt_students = [s for s in self._infer_prompt_students(raw_request, mentor_id) if s in mentees]

        scope_conflict: Optional[ScopeConflict] = None
        if selected and prompt_students and set(selected) != set(prompt_students):
            scope_conflict = ScopeConflict(
                authoritative_selected=list(selected),
                prompt_suggested=list(prompt_students),
                resolved=False,
                message=(
                    f"Selected students {selected} stay authoritative; prompt mentioned "
                    f"{prompt_students}. Keep selected scope or explicitly switch?"
                ),
            )

        effective_scope = list(selected) if selected else list(prompt_students)
        focus = self._infer_focus(raw_request)
        grounded_filters, stripped = ground_criteria(
            raw_request, proposed_filters or {}, self.policy
        )

        candidate_questions: List[str] = []
        if not effective_scope:
            candidate_questions.append(CLARIFYING_TEMPLATES["scope"])
        if not focus:
            candidate_questions.append(CLARIFYING_TEMPLATES["focus"])
        if not grounded_filters and "ch11-demo-1" not in raw_request.lower():
            candidate_questions.append(CLARIFYING_TEMPLATES["policy"])

        pending = self._deduplicate_questions(candidate_questions, [])
        status = PlanStatus.CLARIFYING if (pending or (scope_conflict and not scope_conflict.resolved)) else PlanStatus.READY

        return PlanDraft(
            plan_id=plan_id,
            mentor_id=mentor_id,
            raw_request=raw_request,
            status=status,
            selected_students=effective_scope,
            filters=grounded_filters,
            focus_signals=focus,
            policy_version=self.policy["version"],
            asked_questions=list(pending),
            pending_questions=pending,
            stripped_hallucinations=stripped,
            scope_conflict=scope_conflict,
        )

    def revise_plan(
        self,
        draft: PlanDraft,
        question: str,
        answer: str,
        proposed_filters: Optional[Dict[str, Any]] = None,
        resolve_conflict: Optional[str] = None,
    ) -> PlanDraft:
        """Observe mentor feedback, deduplicate questions, and update plan state."""
        if draft.status == PlanStatus.LOCKED:
            raise ValueError("Cannot revise an already locked plan; create a new revision.")

        combined_text = f"{draft.raw_request}\n" + "\n".join(
            f"{q}: {a}" for q, a in draft.answered_history
        ) + f"\n{question}: {answer}"

        mentees = set(self._mentees_for(draft.mentor_id))
        updated_scope = list(draft.selected_students)
        conflict = draft.scope_conflict

        if conflict and not conflict.resolved and resolve_conflict in {"keep_selected", "switch_to_prompt"}:
            if resolve_conflict == "switch_to_prompt":
                updated_scope = list(conflict.prompt_suggested)
            conflict = ScopeConflict(
                authoritative_selected=conflict.authoritative_selected,
                prompt_suggested=conflict.prompt_suggested,
                resolved=True,
                resolution=resolve_conflict,
                message=f"Conflict resolved via '{resolve_conflict}'.",
            )
        elif not updated_scope:
            inferred = [s for s in self._infer_prompt_students(answer, draft.mentor_id) if s in mentees]
            if inferred:
                updated_scope = inferred

        focus = list(dict.fromkeys(draft.focus_signals + self._infer_focus(answer)))
        merged_filters = dict(draft.filters)
        if proposed_filters:
            merged_filters.update(proposed_filters)
        grounded_filters, newly_stripped = ground_criteria(combined_text, merged_filters, self.policy)

        answered_history = list(draft.answered_history) + [(question, answer)]
        asked_history = list(draft.asked_questions)
        if not any(jaccard_similarity(question, prev) >= 0.5 for prev in asked_history):
            asked_history.append(question)

        # Also record the answer text as covered context for Jaccard deduplication checks
        remaining_candidates: List[str] = []
        if not updated_scope:
            remaining_candidates.append(CLARIFYING_TEMPLATES["scope"])
        if not focus:
            remaining_candidates.append(CLARIFYING_TEMPLATES["focus"])

        # Do not re-ask questions already answered (>= 0.5 Jaccard similarity with asked/answered text)
        dedup_corpus = asked_history + [q for q, _ in answered_history]
        pending = self._deduplicate_questions(remaining_candidates, dedup_corpus, threshold=0.5)

        if "ch11-demo-1" in answer.lower() or grounded_filters:
            pass
        elif not any(jaccard_similarity(CLARIFYING_TEMPLATES["policy"], prev) >= 0.5 for prev in dedup_corpus):
            pending.append(CLARIFYING_TEMPLATES["policy"])

        conflict_open = bool(conflict and not conflict.resolved)
        status = PlanStatus.CLARIFYING if (pending or conflict_open) else PlanStatus.READY

        return PlanDraft(
            plan_id=draft.plan_id,
            mentor_id=draft.mentor_id,
            raw_request=draft.raw_request,
            status=status,
            selected_students=updated_scope,
            filters=grounded_filters,
            focus_signals=focus,
            policy_version=draft.policy_version,
            asked_questions=asked_history + [q for q in pending if q not in asked_history],
            pending_questions=pending,
            answered_history=answered_history,
            stripped_hallucinations=draft.stripped_hallucinations + newly_stripped,
            scope_conflict=conflict,
            revision=draft.revision + 1,
        )

    def lock_plan(self, draft: PlanDraft, actor_role: str, actor_id: str) -> PlanDraft:
        """Lock a READY plan; only the owning mentor may lock (planner never self-locks)."""
        if actor_role != "mentor" or actor_id != draft.mentor_id:
            raise PermissionError(
                f"Only owning mentor '{draft.mentor_id}' can lock this plan (got {actor_role}:{actor_id})."
            )
        if draft.status != PlanStatus.READY:
            raise ValueError(f"Plan must be READY before locking (current status: {draft.status.value}).")

        canonical_payload = json.dumps(
            {
                "plan_id": draft.plan_id,
                "mentor_id": draft.mentor_id,
                "selected_students": sorted(draft.selected_students),
                "filters": draft.filters,
                "focus_signals": sorted(draft.focus_signals),
                "policy_version": draft.policy_version,
                "revision": draft.revision,
            },
            sort_keys=True,
        )
        plan_hash = hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()
        locked = PlanDraft(**asdict(draft))
        locked.status = PlanStatus.LOCKED
        locked.plan_hash = plan_hash
        return locked


def run_demo() -> None:
    print("=== Lab 01: Agent vs. Chatbot (AURA Planner Loop) ===")
    chatbot = OneShotChatbot()
    print("\n1) Baseline One-Shot Chatbot on vague request:")
    print(json.dumps(chatbot.respond("Review my struggling students"), indent=2))

    planner = AuraPlannerAgent()
    print("\n2) Stateful AuraPlannerAgent — Turn 1 (Vague Request):")
    draft = planner.start_plan(
        plan_id="plan-lab01-demo",
        mentor_id="mentor-01",
        raw_request="Check my struggling students",
        proposed_filters={"attendanceBelowPct": 68},  # hallucinated cutoff
    )
    print(f"   Status: {draft.status.value} | Questions asked ({len(draft.pending_questions)}):")
    for idx, q in enumerate(draft.pending_questions, 1):
        print(f"     Q{idx}: {q}")
    print(f"   Stripped ungrounded filters: {draft.stripped_hallucinations}")

    print("\n3) Turn 2 — Mentor clarifies scope, focus, and signed policy CH11-DEMO-1:")
    draft = planner.revise_plan(
        draft,
        question=draft.pending_questions[0],
        answer="Check all my mentees for attendance and academic marks under CH11-DEMO-1.",
        proposed_filters={"attendanceBelowPct": 75, "markBelowPct": 60},
    )
    print(f"   Status: {draft.status.value} | Scope: {draft.selected_students} | Filters: {draft.filters}")

    locked = planner.lock_plan(draft, actor_role="mentor", actor_id="mentor-01")
    print(f"   Locked by mentor-01 -> hash={locked.plan_hash[:16]}... revision={locked.revision}")


def run_self_tests() -> None:
    planner = AuraPlannerAgent()

    # 1. Vague request asks >= 2 clarifying questions
    d1 = planner.start_plan("p-1", "mentor-01", "Help me review students")
    assert d1.status == PlanStatus.CLARIFYING
    assert len(d1.pending_questions) >= 2, f"Expected >=2 questions, got {len(d1.pending_questions)}"
    print("[PASS] Vague request prompts >= 2 clarifying questions instead of one-shot reply")

    # 2. Hallucinated numeric filter (68) not in prompt or policy is stripped by ground_criteria()
    d_halluc = planner.start_plan(
        "p-2",
        "mentor-01",
        "Review SYN-0001 attendance",
        selected_students=["SYN-0001"],
        proposed_filters={"attendanceBelowPct": 68, "markBelowPct": 60},
    )
    assert "attendanceBelowPct" not in d_halluc.filters
    assert d_halluc.filters["markBelowPct"] == 60
    assert any("68" in item for item in d_halluc.stripped_hallucinations)
    print("[PASS] ground_criteria() stripped hallucinated filter 68 while preserving policy threshold 60")

    # 3. Answered question is deduplicated via Jaccard >= 0.5 and never re-asked
    d2 = planner.revise_plan(
        d1,
        question=CLARIFYING_TEMPLATES["scope"],
        answer="Use SYN-0001 and SYN-0002 with attendance and academic focus under CH11-DEMO-1.",
        proposed_filters={"attendanceBelowPct": 75},
    )
    assert not any(jaccard_similarity(q, CLARIFYING_TEMPLATES["scope"]) >= 0.5 for q in d2.pending_questions)
    assert d2.status == PlanStatus.READY
    print("[PASS] Jaccard (>= 0.5) deduplication prevented re-asking answered scope question")

    # 4. Authoritative selected_students cannot be silently widened by prompt text
    d_conflict = planner.start_plan(
        "p-3",
        "mentor-01",
        "Review all my mentees for attendance and marks under CH11-DEMO-1",
        selected_students=["SYN-0001"],
        proposed_filters={"attendanceBelowPct": 75},
    )
    assert d_conflict.selected_students == ["SYN-0001"]
    assert d_conflict.scope_conflict is not None and not d_conflict.scope_conflict.resolved
    assert d_conflict.status == PlanStatus.CLARIFYING
    d_kept = planner.revise_plan(
        d_conflict,
        question="Keep selected scope?",
        answer="Keep selected student only.",
        resolve_conflict="keep_selected",
    )
    assert d_kept.selected_students == ["SYN-0001"]
    assert d_kept.status == PlanStatus.READY
    print("[PASS] Explicit mentor selection stayed authoritative until scope_conflict was resolved")

    # 5. Planner agent cannot self-lock; only owning mentor locks with SHA-256 plan_hash
    try:
        planner.lock_plan(d_kept, actor_role="planner_agent", actor_id="agent")
        raise AssertionError("Expected PermissionError for planner self-lock")
    except PermissionError:
        pass
    locked = planner.lock_plan(d_kept, actor_role="mentor", actor_id="mentor-01")
    assert locked.status == PlanStatus.LOCKED
    assert locked.plan_hash is not None and len(locked.plan_hash) == 64
    print("[PASS] Mentor-only lock produced immutable 64-char SHA-256 plan_hash")


if __name__ == "__main__":
    run_demo()
    print("\n--- Running Self-Tests ---")
    run_self_tests()
    print("All Lab 01 checks passed.")
