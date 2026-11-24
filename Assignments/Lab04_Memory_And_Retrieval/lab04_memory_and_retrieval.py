"""Lab 04: Memory & Retrieval — Short-Term Run State vs. Long-Term Lexical Archive.

Course: Agentic AI (26ECAC401) — Chapter 11: Student Success & Early Warning System (AURA)
Phase A · Foundations

Separates short-term per-run state from long-term retrieved guidance/history as
implemented in AURA's `engine.ts`, `connectors.ts`, and `streamlit_app/common.py`:
  1. Short-term run state:
       - Active `draft_packet` (isolated from archive).
       - `EvidenceBook` capped at 48 verified `ev-N` entries.
       - Stage checkpoints (`after_risk`, `after_recommend`, `after_publish`).
       - User-scoped 60-second read cache invalidated immediately on every write.
  2. Long-term knowledge store (`HistoryRetriever`):
       - Exact `sha256-lexical-128-v1` 128-dimensional SHA-256 lexical hash vector
         (zero cloud embedding cost, zero PII egress, 100% deterministic replay).
       - Filters by department scope, student scope, and tag intersection, then ranks
         top-k matches by cosine similarity.
       - Anonymizes prior approved student interventions via `anonymous_prior_reference()`
         to action codes and tags only (zero PII).
"""

from __future__ import annotations

import hashlib
import math
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

EMBEDDING_MODEL_ID = "sha256-lexical-128-v1"
MAX_EVIDENCE_ITEMS = 48
READ_CACHE_TTL_SECONDS = 60.0


def embed_lexical_128(text: str) -> List[float]:
    """Deterministic 128-dim SHA-256 lexical hash vector matching AURA engine.ts."""
    vector = [0.0] * 128
    for token in re.findall(r"[a-z0-9]+", text.lower()):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        vector[digest[0] % 128] += 1.0 if (digest[1] % 2) else -1.0
    norm = math.hypot(*vector) or 1.0
    return [val / norm for val in vector]


def cosine_similarity(vec_a: Sequence[float], vec_b: Sequence[float]) -> float:
    return sum(a * b for a, b in zip(vec_a, vec_b))


@dataclass
class EvidenceEntry:
    tag: str
    source: str
    metric: str
    value: Any


class EvidenceBook:
    """Short-term per-run evidence cache bounded to 48 entries."""

    def __init__(self, max_items: int = MAX_EVIDENCE_ITEMS) -> None:
        self.max_items = max_items
        self._items: Dict[str, EvidenceEntry] = {}

    def record(self, source: str, metric: str, value: Any) -> str:
        if len(self._items) >= self.max_items:
            raise MemoryError(f"EvidenceBook capacity ({self.max_items}) exceeded.")
        tag = f"ev-{len(self._items) + 1}"
        self._items[tag] = EvidenceEntry(tag=tag, source=source, metric=metric, value=value)
        return tag

    def all_entries(self) -> Dict[str, EvidenceEntry]:
        return dict(self._items)


class SessionReadCache:
    """User-scoped 60-second read cache invalidated atomically on writes."""

    def __init__(self, ttl_seconds: float = READ_CACHE_TTL_SECONDS) -> None:
        self.ttl_seconds = ttl_seconds
        self._store: Dict[Tuple[str, str], Tuple[float, Any]] = {}

    def get(self, user_id: str, key: str, now: Optional[float] = None) -> Optional[Any]:
        ts_now = time.monotonic() if now is None else now
        entry = self._store.get((user_id, key))
        if entry is None:
            return None
        expires_at, payload = entry
        if ts_now >= expires_at:
            del self._store[(user_id, key)]
            return None
        return payload

    def put(self, user_id: str, key: str, payload: Any, now: Optional[float] = None) -> None:
        ts_now = time.monotonic() if now is None else now
        self._store[(user_id, key)] = (ts_now + self.ttl_seconds, payload)

    def invalidate_user(self, user_id: str) -> None:
        for cache_key in [k for k in self._store if k[0] == user_id]:
            del self._store[cache_key]


@dataclass
class ShortTermRunState:
    """Isolated short-term execution memory for a single review job."""

    run_id: str
    case_alias: str
    draft_packet: Dict[str, Any] = field(default_factory=dict)
    evidence_book: EvidenceBook = field(default_factory=EvidenceBook)
    checkpoints: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    read_cache: SessionReadCache = field(default_factory=SessionReadCache)

    def save_checkpoint(self, stage: str, payload: Dict[str, Any]) -> None:
        self.checkpoints[stage] = dict(payload)

    def write_draft_mutation(self, user_id: str, updated_draft: Dict[str, Any]) -> None:
        self.draft_packet = dict(updated_draft)
        self.read_cache.invalidate_user(user_id)


@dataclass(frozen=True)
class StoredReference:
    """Long-term archive entry (guidance note or historical approved intervention)."""

    ref_id: str
    kind: str  # "guidance" | "prior_intervention"
    text: str
    tags: Tuple[str, ...]
    department_id: Optional[str]  # None means global guidance
    student_ref: Optional[str]
    student_name: Optional[str]
    action_codes: Tuple[str, ...] = ()
    embedding: Optional[Tuple[float, ...]] = None


def anonymous_prior_reference(ref: StoredReference, similarity: float) -> Dict[str, Any]:
    """Strip all PII and raw text from prior student interventions before model/UI use."""
    return {
        "ref_id": ref.ref_id,
        "kind": ref.kind,
        "tags": list(ref.tags),
        "action_codes": list(ref.action_codes),
        "summary": ref.text if ref.kind == "guidance" else f"Anonymized prior intervention ({', '.join(ref.action_codes)})",
        "similarity": round(similarity, 4),
        "embedding_model": EMBEDDING_MODEL_ID,
    }


class LongTermKnowledgeStore:
    """Immutable-to-run-state archive supporting scoped tag + lexical similarity search."""

    def __init__(self, references: Sequence[StoredReference]) -> None:
        self._references: List[StoredReference] = []
        for ref in references:
            vec = ref.embedding if ref.embedding is not None else tuple(embed_lexical_128(ref.text))
            self._references.append(
                StoredReference(
                    ref_id=ref.ref_id,
                    kind=ref.kind,
                    text=ref.text,
                    tags=ref.tags,
                    department_id=ref.department_id,
                    student_ref=ref.student_ref,
                    student_name=ref.student_name,
                    action_codes=ref.action_codes,
                    embedding=vec,
                )
            )

    def count(self) -> int:
        return len(self._references)

    def retrieve(
        self,
        query: str,
        tags: Sequence[str],
        department_id: str,
        student_ref: Optional[str] = None,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        q_vec = embed_lexical_128(query)
        tag_set = set(tags)
        hits: List[Tuple[float, str, Dict[str, Any]]] = []
        for ref in self._references:
            if ref.department_id is not None and ref.department_id != department_id:
                continue
            if ref.student_ref is not None and student_ref is not None and ref.student_ref != student_ref and ref.kind != "prior_intervention":
                continue
            if not (tag_set & set(ref.tags)):
                continue
            sim = cosine_similarity(q_vec, ref.embedding or ())
            hits.append((sim, ref.ref_id, anonymous_prior_reference(ref, sim)))

        hits.sort(key=lambda item: (-item[0], item[1]))
        return [item[2] for item in hits[:top_k]]


def build_default_archive() -> LongTermKnowledgeStore:
    return LongTermKnowledgeStore(
        [
            StoredReference(
                ref_id="guide-att-01",
                kind="guidance",
                text="Attendance below 75% paired with overdue LMS assignments calls for an early attendance review and weekly catch-up plan.",
                tags=("ATTENDANCE_LOW", "ASSIGNMENT_OVERDUE"),
                department_id=None,
                student_ref=None,
                student_name=None,
                action_codes=("attendance-review", "lms-catch-up"),
            ),
            StoredReference(
                ref_id="guide-multi-02",
                kind="guidance",
                text="Multi-signal high risk across marks, inactivity, internship milestones, and placement requires immediate faculty check-in and study plan.",
                tags=("ATTENDANCE_LOW", "MARK_LOW", "LMS_INACTIVE", "INTERNSHIP_MILESTONE", "PLACEMENT_ACTIVITY"),
                department_id=None,
                student_ref=None,
                student_name=None,
                action_codes=("faculty-check-in", "student-study-plan", "internship-review", "placement-review"),
            ),
            StoredReference(
                ref_id="prior-cse-101",
                kind="prior_intervention",
                text="Past case with 71% attendance and 1 overdue assignment resolved via mentor attendance review.",
                tags=("ATTENDANCE_LOW", "ASSIGNMENT_OVERDUE"),
                department_id="CSE-AI",
                student_ref="SYN-HIST-09",
                student_name="Redacted Historical Student",
                action_codes=("attendance-review", "lms-catch-up"),
            ),
            StoredReference(
                ref_id="prior-mech-99",
                kind="prior_intervention",
                text="Other department attendance intervention that must stay hidden from CSE-AI scope.",
                tags=("ATTENDANCE_LOW",),
                department_id="MECH",
                student_ref="MECH-01",
                student_name="Mechanical Student",
                action_codes=("faculty-check-in",),
            ),
        ]
    )


def run_demo() -> None:
    print("=== Lab 04: Memory & Retrieval (Short-Term Run State vs. Long-Term Archive) ===")
    run_state = ShortTermRunState(run_id="run-001", case_alias="case-0001")
    ev1 = run_state.evidence_book.record("academic", "attendance_pct", 72)
    ev2 = run_state.evidence_book.record("lms", "overdue_assignments", 1)
    run_state.save_checkpoint("after_risk", {"score": 30, "band": "medium", "evidence_tags": [ev1, ev2]})
    run_state.write_draft_mutation("mentor-01", {"summary": f"Attendance 72% [{ev1}], 1 overdue task [{ev2}]."})

    archive = build_default_archive()
    results = archive.retrieve(
        query="attendance below 75 overdue lms assignment catch-up plan",
        tags=["ATTENDANCE_LOW", "ASSIGNMENT_OVERDUE"],
        department_id="CSE-AI",
        top_k=5,
    )
    print(f"Short-term checkpoints: {list(run_state.checkpoints.keys())} | EvidenceBook size: {len(run_state.evidence_book.all_entries())}")
    print(f"Long-term top-{len(results)} retrieved references (embedding={EMBEDDING_MODEL_ID}):")
    for hit in results:
        print(f"  - {hit['ref_id']} (sim={hit['similarity']:.4f}) actions={hit['action_codes']} summary={hit['summary']}")


def run_self_tests() -> None:
    archive = build_default_archive()
    initial_count = archive.count()
    run_state = ShortTermRunState(run_id="run-test", case_alias="case-0001")

    # 1. Short-term draft edits never mutate long-term archive
    run_state.write_draft_mutation("mentor-01", {"summary": "Temporary draft note"})
    assert archive.count() == initial_count
    print("[PASS] Short-term draft mutation left long-term archive untouched")

    # 2. 60-second read cache returns hit before TTL and invalidates on write
    run_state.read_cache.put("mentor-01", "queue_view", {"count": 3}, now=100.0)
    assert run_state.read_cache.get("mentor-01", "queue_view", now=120.0) == {"count": 3}
    assert run_state.read_cache.get("mentor-01", "queue_view", now=161.0) is None
    run_state.read_cache.put("mentor-01", "queue_view", {"count": 4}, now=200.0)
    run_state.write_draft_mutation("mentor-01", {"summary": "Updated draft triggers invalidation"})
    assert run_state.read_cache.get("mentor-01", "queue_view", now=205.0) is None
    print("[PASS] 60s SessionReadCache honored TTL and invalidated immediately on write")

    # 3. EvidenceBook enforces 48-entry cap
    book = EvidenceBook(max_items=48)
    for idx in range(48):
        book.record("academic", f"metric_{idx}", idx)
    try:
        book.record("academic", "overflow", 49)
        raise AssertionError("Expected MemoryError at 49th EvidenceBook entry")
    except MemoryError:
        pass
    print("[PASS] EvidenceBook enforced 48-entry per-run cap")

    # 4. Scoped retrieval returns deterministic top-k matches with zero PII
    hits_a = archive.retrieve("attendance 72 overdue assignment", ["ATTENDANCE_LOW", "ASSIGNMENT_OVERDUE"], "CSE-AI", top_k=5)
    hits_b = archive.retrieve("attendance 72 overdue assignment", ["ATTENDANCE_LOW", "ASSIGNMENT_OVERDUE"], "CSE-AI", top_k=5)
    assert hits_a == hits_b
    assert len(hits_a) == 3  # prior-mech-99 filtered out by department
    assert all(h["ref_id"] != "prior-mech-99" for h in hits_a)
    serialized = str(hits_a)
    assert "Redacted Historical Student" not in serialized and "SYN-HIST-09" not in serialized
    assert hits_a[0]["embedding_model"] == EMBEDDING_MODEL_ID
    print("[PASS] Lexical 128-dim retrieval deterministic, department-scoped, and PII-anonymized")


if __name__ == "__main__":
    run_demo()
    print("\n--- Running Self-Tests ---")
    run_self_tests()
    print("All Lab 04 checks passed.")
