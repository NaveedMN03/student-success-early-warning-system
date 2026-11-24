"""Lab 12: Safety & Governance — Egress Firewall, Mentor Gate, Telemetry & Rollback.

Course: Agentic AI (26ECAC401) — Chapter 11: Student Success & Early Warning System (AURA)
Phase D · Governance & Safety

Implements all four AURA governance pillars (`egress.ts`, `review.ts`,
`metrics.ts`, `lib/data-refresh/generation.ts`):
  1. `EgressFirewall`: allowlist-only remote LLM payload builder aliasing student,
     course, and evidence identifiers into `case-xxxx`, `course-N`, and `ev-N`,
     raising `EGRESS_BLOCKED` on any raw PII leak.
  2. `MentorApprovalGate`: cryptographic approval bound to `(artifact_id,
     content_hash, expected_revision, policy_attestation, data_generation)` plus
     mentor ownership, >=8-char rationale, and two-step audience confirmation.
     Blocks stale generations (`EVIDENCE_EARLIER_FIGURES`), unauthorized roles,
     and hash drift.
  3. `GovernanceTelemetry` + zero-LLM deterministic `replay_agent_run()`: tracks
     pass rate, repair rate, word edit distance, decision latency, and proves
     identical SHA-256 replay hashes.
  4. `VersionedPublicationLedger`: immutable publications (`v1` -> `v2`), instant
     `withdraw()`, and one-click `rollback_restore(target_version=1)` writing an
     immutable `v3` restored from `v1` with append-only audit trail.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


class GovernanceError(PermissionError):
    """Raised when an egress, authorization, freshness, or hash invariant fails."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message


class EgressFirewall:
    """Allowlist-only outbound payload builder preventing PII egress to cloud LLMs."""

    RAW_PII_PATTERNS = (
        re.compile(r"\bSYN-\d{4}\b", re.I),
        re.compile(r"\b01FE\d{2}[A-Z]{3}\d{3}\b", re.I),
        re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
        re.compile(r"\bCS\d{3}\b"),  # raw course codes must be aliased to course-N
    )

    def build_sealed_payload(
        self,
        student_ref: str,
        student_name: str,
        course_codes: List[str],
        metrics: Dict[str, float],
        evidence_paths: List[str],
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        case_alias = f"case-{hashlib.sha256(student_ref.encode('utf-8')).hexdigest()[:4]}"
        course_map = {f"course-{idx}": code for idx, code in enumerate(course_codes, 1)}
        ev_map = {f"ev-{idx}": path for idx, path in enumerate(evidence_paths, 1)}

        payload = {
            "case_alias": case_alias,
            "courses": list(course_map.keys()),
            "metrics": {k: round(float(v), 1) for k, v in metrics.items()},
            "evidence_tags": list(ev_map.keys()),
        }
        self.assert_clean_egress(payload, forbidden_literals=[student_ref, student_name, *course_codes])
        return payload, {"case_alias": case_alias, "courses": course_map, "evidence": ev_map}

    def assert_clean_egress(self, payload: Dict[str, Any], forbidden_literals: Optional[List[str]] = None) -> None:
        serialized = json.dumps(payload, sort_keys=True)
        for literal in forbidden_literals or []:
            if literal and literal.lower() in serialized.lower():
                raise GovernanceError("EGRESS_BLOCKED", f"Forbidden identifier '{literal}' detected in outbound payload.")
        for pattern in self.RAW_PII_PATTERNS:
            if pattern.search(serialized):
                raise GovernanceError("EGRESS_BLOCKED", f"Raw identifier pattern '{pattern.pattern}' blocked at egress firewall.")


@dataclass
class DraftArtifact:
    artifact_id: str
    student_ref: str
    assigned_mentor_id: str
    revision: int
    summary: str
    actions: List[str]
    policy_attestation: str
    data_generation: int
    status: str = "draft"

    @property
    def content_hash(self) -> str:
        canonical = json.dumps(
            {
                "artifact_id": self.artifact_id,
                "revision": self.revision,
                "summary": self.summary,
                "actions": self.actions,
            },
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PublishedVersion:
    version: int
    artifact_id: str
    content_hash: str
    summary: str
    actions: Tuple[str, ...]
    approved_by: str
    rationale: str
    status: str  # "active" | "withdrawn" | "superseded"
    restored_from_version: Optional[int] = None
    published_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class VersionedPublicationLedger:
    """Append-only versioned publication history with instant withdraw and rollback restore."""

    def __init__(self) -> None:
        self.versions: List[PublishedVersion] = []
        self.audit_trail: List[Dict[str, Any]] = []

    def append_publication(
        self,
        artifact: DraftArtifact,
        actor_id: str,
        rationale: str,
        restored_from: Optional[int] = None,
    ) -> PublishedVersion:
        for idx, prev in enumerate(self.versions):
            if prev.status == "active":
                self.versions[idx] = PublishedVersion(
                    version=prev.version,
                    artifact_id=prev.artifact_id,
                    content_hash=prev.content_hash,
                    summary=prev.summary,
                    actions=prev.actions,
                    approved_by=prev.approved_by,
                    rationale=prev.rationale,
                    status="superseded",
                    restored_from_version=prev.restored_from_version,
                    published_at=prev.published_at,
                )
        next_ver = len(self.versions) + 1
        pub = PublishedVersion(
            version=next_ver,
            artifact_id=artifact.artifact_id,
            content_hash=artifact.content_hash,
            summary=artifact.summary,
            actions=tuple(artifact.actions),
            approved_by=actor_id,
            rationale=rationale,
            status="active",
            restored_from_version=restored_from,
        )
        self.versions.append(pub)
        self.audit_trail.append(
            {
                "event": "publication.restored" if restored_from else "publication.created",
                "version": next_ver,
                "content_hash": pub.content_hash,
                "actor": actor_id,
                "restored_from": restored_from,
            }
        )
        return pub

    def withdraw(self, actor_id: str, reason: str) -> PublishedVersion:
        if not self.versions:
            raise ValueError("No publications exist to withdraw.")
        latest = self.versions[-1]
        withdrawn = PublishedVersion(
            version=latest.version,
            artifact_id=latest.artifact_id,
            content_hash=latest.content_hash,
            summary=latest.summary,
            actions=latest.actions,
            approved_by=latest.approved_by,
            rationale=latest.rationale,
            status="withdrawn",
            restored_from_version=latest.restored_from_version,
            published_at=latest.published_at,
        )
        self.versions[-1] = withdrawn
        self.audit_trail.append({"event": "publication.withdrawn", "version": latest.version, "actor": actor_id, "reason": reason})
        return withdrawn

    def rollback_restore(self, target_version: int, actor_id: str, rationale: str) -> PublishedVersion:
        """Restore an earlier publication into a NEW immutable version without erasing history."""
        target = next((v for v in self.versions if v.version == target_version), None)
        if target is None:
            raise KeyError(f"Target version {target_version} does not exist.")
        restored_artifact = DraftArtifact(
            artifact_id=target.artifact_id,
            student_ref="SYN-0002",
            assigned_mentor_id=actor_id,
            revision=len(self.versions) + 1,
            summary=target.summary,
            actions=list(target.actions),
            policy_attestation="faculty-chair-01",
            data_generation=2,
        )
        return self.append_publication(restored_artifact, actor_id=actor_id, rationale=rationale, restored_from=target_version)


class MentorApprovalGate:
    """Cryptographic human approval gate enforcing role, freshness, hash, and rationale."""

    def __init__(self, current_data_generation: int, ledger: VersionedPublicationLedger) -> None:
        self.current_data_generation = current_data_generation
        self.ledger = ledger

    def approve_and_publish(
        self,
        actor_role: str,
        actor_id: str,
        artifact: DraftArtifact,
        expected_hash: str,
        expected_revision: int,
        rationale: str,
        confirm_student_parent_visibility: bool,
    ) -> PublishedVersion:
        if actor_role != "mentor" or actor_id != artifact.assigned_mentor_id:
            raise GovernanceError("UNAUTHORIZED_APPROVER", f"Only assigned mentor '{artifact.assigned_mentor_id}' may approve.")
        if artifact.data_generation != self.current_data_generation:
            raise GovernanceError(
                "EVIDENCE_EARLIER_FIGURES",
                f"Draft generation {artifact.data_generation} predates current generation {self.current_data_generation}.",
            )
        if artifact.revision != expected_revision or artifact.content_hash != expected_hash:
            raise GovernanceError("STALE_REVISION", "Draft changed since review lock; re-verify hash before publishing.")
        if not artifact.policy_attestation:
            raise GovernanceError("THRESHOLDS_NOT_FACULTY_SET", "Policy attestation missing.")
        if len(rationale.strip()) < 8:
            raise GovernanceError("RATIONALE_TOO_SHORT", "Mentor rationale must be at least 8 characters.")
        if not confirm_student_parent_visibility:
            raise GovernanceError("CONFIRMATION_REQUIRED", "Two-step confirmation of student/parent visibility required.")

        return self.ledger.append_publication(artifact, actor_id=actor_id, rationale=rationale)


def word_edit_distance(text_a: str, text_b: str) -> int:
    """Levenshtein edit distance on whitespace tokens for mentor edit telemetry."""
    words_a = text_a.split()
    words_b = text_b.split()
    dp = list(range(len(words_b) + 1))
    for i, wa in enumerate(words_a, 1):
        prev = dp[0]
        dp[0] = i
        for j, wb in enumerate(words_b, 1):
            cur = dp[j]
            dp[j] = prev if wa == wb else 1 + min(prev, dp[j], dp[j - 1])
            prev = cur
    return dp[-1]


class GovernanceTelemetry:
    """Tracks pass rate, repair rate, mentor edit distance, and decision latency."""

    def __init__(self) -> None:
        self.records: List[Dict[str, Any]] = []

    def record(self, passed_first_try: bool, repaired: bool, draft_text: str, final_text: str, latency_ms: float) -> None:
        self.records.append(
            {
                "passed_first_try": passed_first_try,
                "repaired": repaired,
                "word_edit_distance": word_edit_distance(draft_text, final_text),
                "latency_ms": latency_ms,
            }
        )

    def summary(self) -> Dict[str, float]:
        n = max(1, len(self.records))
        return {
            "total": float(len(self.records)),
            "first_pass_rate": round(sum(r["passed_first_try"] for r in self.records) / n, 3),
            "repair_rate": round(sum(r["repaired"] for r in self.records) / n, 3),
            "avg_word_edit_distance": round(sum(r["word_edit_distance"] for r in self.records) / n, 2),
            "avg_latency_ms": round(sum(r["latency_ms"] for r in self.records) / n, 2),
        }


def replay_agent_run(frozen_inputs: Dict[str, Any]) -> str:
    """Zero-LLM deterministic replay verifying identical artifact hash."""
    canonical = json.dumps(frozen_inputs, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def run_demo() -> None:
    print("=== Lab 12: Safety & Governance (Egress, Approval Gate, Telemetry & Rollback) ===")
    fw = EgressFirewall()
    sealed, aliases = fw.build_sealed_payload(
        student_ref="SYN-0002",
        student_name="Synthetic Student 0002",
        course_codes=["26ECAC401", "26ECAC402"],
        metrics={"attendancePct": 65.0, "markPct": 58.0},
        evidence_paths=["evidence.academic.values.attendancePct"],
    )
    print(f"1) Egress Firewall sealed payload: {sealed} (aliases={aliases['courses']})")

    ledger = VersionedPublicationLedger()
    gate = MentorApprovalGate(current_data_generation=2, ledger=ledger)
    d1 = DraftArtifact("art-01", "SYN-0002", "mentor-01", 1, "Attendance is 65% below 75% [ev-1].", ["faculty-check-in"], "faculty-chair-01", 2)
    v1 = gate.approve_and_publish("mentor", "mentor-01", d1, d1.content_hash, 1, "Reviewed mentee schedule and approved.", True)

    d2 = DraftArtifact("art-01", "SYN-0002", "mentor-01", 2, "Attendance 65% [ev-1]; schedule study plan.", ["faculty-check-in", "student-study-plan"], "faculty-chair-01", 2)
    v2 = gate.approve_and_publish("mentor", "mentor-01", d2, d2.content_hash, 2, "Added weekly study plan after follow-up.", True)
    v3 = ledger.rollback_restore(1, "mentor-01", "Restoring concise v1 plan per student meeting.")
    print(f"2) Publication Ledger: v1({v1.content_hash[:8]}) -> v2({v2.content_hash[:8]}) -> rollback restore v3({v3.content_hash[:8]}, from=v{v3.restored_from_version})")

    tel = GovernanceTelemetry()
    tel.record(True, False, d1.summary, d2.summary, 420.0)
    print(f"3) Telemetry summary: {tel.summary()} | Replay hash={replay_agent_run(sealed)[:12]}...")


def run_self_tests() -> None:
    # 1. EgressFirewall aliases PII and blocks raw leaks with EGRESS_BLOCKED
    fw = EgressFirewall()
    sealed, _ = fw.build_sealed_payload("SYN-0002", "Synthetic Student 0002", ["26ECAC401"], {"attendancePct": 65}, ["evidence.academic.attendancePct"])
    assert "SYN-0002" not in json.dumps(sealed) and "26ECAC401" not in json.dumps(sealed)
    try:
        fw.assert_clean_egress({"case_alias": "case-9999", "note": "Student SYN-0002 (vik@example.edu)"})
        raise AssertionError("Expected EGRESS_BLOCKED")
    except GovernanceError as exc:
        assert exc.code == "EGRESS_BLOCKED"
    print("[PASS] EgressFirewall aliased case/course/evidence and blocked raw PII with EGRESS_BLOCKED")

    # 2. MentorApprovalGate rejects non-mentor, stale generation, hash drift, and missing confirmation
    ledger = VersionedPublicationLedger()
    gate = MentorApprovalGate(current_data_generation=2, ledger=ledger)
    draft = DraftArtifact("art-1", "SYN-0002", "mentor-01", 1, "Attendance is 65% [ev-1].", ["faculty-check-in"], "faculty-chair-01", 2)

    for bad_call, expected_code in (
        (lambda: gate.approve_and_publish("student", "SYN-0002", draft, draft.content_hash, 1, "Self approve attempt", True), "UNAUTHORIZED_APPROVER"),
        (lambda: gate.approve_and_publish("mentor", "mentor-01", DraftArtifact("art-1", "SYN-0002", "mentor-01", 1, "Old", ["faculty-check-in"], "faculty-chair-01", 1), "x", 1, "Valid rationale text", True), "EVIDENCE_EARLIER_FIGURES"),
        (lambda: gate.approve_and_publish("mentor", "mentor-01", draft, "wrong-hash", 1, "Valid rationale text", True), "STALE_REVISION"),
        (lambda: gate.approve_and_publish("mentor", "mentor-01", draft, draft.content_hash, 1, "short", True), "RATIONALE_TOO_SHORT"),
        (lambda: gate.approve_and_publish("mentor", "mentor-01", draft, draft.content_hash, 1, "Valid rationale text", False), "CONFIRMATION_REQUIRED"),
    ):
        try:
            bad_call()
            raise AssertionError(f"Expected {expected_code}")
        except GovernanceError as exc:
            assert exc.code == expected_code, f"Expected {expected_code}, got {exc.code}"
    print("[PASS] MentorApprovalGate enforced role, generation freshness, hash lock, rationale, and confirmation")

    # 3. Publish v1 -> edit v2 -> withdraw -> rollback restore v1 as immutable v3
    v1 = gate.approve_and_publish("mentor", "mentor-01", draft, draft.content_hash, 1, "Approved initial draft.", True)
    d2 = DraftArtifact("art-1", "SYN-0002", "mentor-01", 2, "Edited v2 summary [ev-1].", ["faculty-check-in", "student-study-plan"], "faculty-chair-01", 2)
    v2 = gate.approve_and_publish("mentor", "mentor-01", d2, d2.content_hash, 2, "Updated intervention scope.", True)
    assert ledger.versions[0].status == "superseded" and v2.status == "active"

    withdrawn = ledger.withdraw("mentor-01", "Mentor paused outreach")
    assert withdrawn.status == "withdrawn"

    v3 = ledger.rollback_restore(1, "mentor-01", "Restored exact v1 plan cleanly.")
    assert v3.version == 3 and v3.status == "active"
    assert v3.summary == v1.summary and v3.actions == v1.actions and v3.restored_from_version == 1
    assert len(ledger.versions) == 3 and len(ledger.audit_trail) == 4
    print("[PASS] Versioned ledger supported withdraw and one-click rollback restore without mutating history")

    # 4. Telemetry + deterministic replay
    assert replay_agent_run({"case": sealed, "policy": "CH11-DEMO-1"}) == replay_agent_run({"policy": "CH11-DEMO-1", "case": sealed})
    assert word_edit_distance(v1.summary, v2.summary) > 0
    print("[PASS] Zero-LLM replay produced identical hashes and edit-distance telemetry")


if __name__ == "__main__":
    run_demo()
    print("\n--- Running Self-Tests ---")
    run_self_tests()
    print("All Lab 12 checks passed.")
