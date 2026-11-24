"""Lab 09: Deep Research & Grounding — EvidenceBook, Citation Verifier & Tolerance Guard.

Course: Agentic AI (26ECAC401) — Chapter 11: Student Success & Early Warning System (AURA)
Phase C · Applied Reliability

Models AURA's evidence synthesis and deterministic verification (`investigator.ts`,
`packet-v2.ts`, `engine.ts`):
  - `DeepResearchInvestigator` gathers verified source records (`academic`, `lms`,
    `internship`, `placement`) into a tagged `EvidenceBook` (`ev-1..ev-N`).
  - Every rationale sentence and intervention step must cite an in-scope `ev-N` tag.
  - `validate_packet_v2()` enforces `ROUNDING_TOLERANCE = 0.5`, rejects uncited
    claims (`UNCITED_CLAIM`), unknown/out-of-scope citations (`UNSUPPORTED_CITATION`,
    `PRIVACY_SCOPE_MISMATCH`), hallucinated numbers (`UNSUPPORTED_NUMBER`), and
    unaddressed triggered signals (`MISSING_TRIGGER_COVERAGE`).
  - Prints a student-level Evidence Table tying claims directly to provenance IDs.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROUNDING_TOLERANCE = 0.5
IN_SCOPE_SOURCES = {"academic", "lms", "internship", "placement"}

EMBEDDED_SYN_0002: Dict[str, Any] = {
    "academic": {
        "source": "academic",
        "student_ref": "SYN-0002",
        "data_state": "present",
        "fields": {"attendance_pct": 65.0, "gpa": 5.8, "failed_courses": 2},
        "provenance": {"record_ids": ["a-0002"]},
    },
    "lms": {
        "source": "lms",
        "student_ref": "SYN-0002",
        "data_state": "present",
        "fields": {"inactivity_days": 10, "overdue_assignments": 3, "missed_assessments": 2},
        "provenance": {"record_ids": ["l-0002"]},
    },
    "internship": {
        "source": "internship",
        "student_ref": "SYN-0002",
        "data_state": "present",
        "fields": {"missed_milestones": 1, "milestones_total": 4},
        "provenance": {"record_ids": ["i-0002"]},
    },
    "placement": {
        "source": "placement",
        "student_ref": "SYN-0002",
        "data_state": "present",
        "fields": {"missed_required_activities": 2, "activities_total": 5},
        "provenance": {"record_ids": ["p-0002"]},
    },
}


def load_syn_0002() -> Dict[str, Any]:
    here = Path(__file__).resolve()
    for parent in here.parents:
        sdir = parent / "Course Project" / "Source-Code" / "fixtures" / "synthetic-cohort-v1" / "SYN-0002"
        if sdir.is_dir():
            return {
                src: json.loads((sdir / f"{src}.json").read_text(encoding="utf-8"))
                for src in ("academic", "lms", "internship", "placement")
            }
    return dict(EMBEDDED_SYN_0002)


@dataclass(frozen=True)
class EvidenceItem:
    tag: str
    student_ref: str
    source: str
    metric: str
    value: float
    threshold: float
    signal_code: str
    record_id: str
    in_scope: bool = True


class EvidenceBook:
    """Authoritative per-case evidence registry indexed by `ev-N` tags."""

    def __init__(self, target_student: str) -> None:
        self.target_student = target_student
        self.items: Dict[str, EvidenceItem] = {}

    def add(
        self,
        student_ref: str,
        source: str,
        metric: str,
        value: float,
        threshold: float,
        signal_code: str,
        record_id: str,
    ) -> str:
        tag = f"ev-{len(self.items) + 1}"
        in_scope = student_ref == self.target_student and source in IN_SCOPE_SOURCES
        self.items[tag] = EvidenceItem(
            tag=tag,
            student_ref=student_ref,
            source=source,
            metric=metric,
            value=float(value),
            threshold=float(threshold),
            signal_code=signal_code,
            record_id=record_id,
            in_scope=in_scope,
        )
        return tag


class DeepResearchInvestigator:
    """Investigates all 4 sources and constructs a verified EvidenceBook."""

    def investigate(self, student_ref: str, records: Dict[str, Any]) -> Tuple[EvidenceBook, List[str]]:
        book = EvidenceBook(target_student=student_ref)
        triggered: List[str] = []

        af = records["academic"]["fields"]
        a_id = records["academic"]["provenance"]["record_ids"][0]
        if af.get("attendance_pct", 100) < 75:
            book.add(student_ref, "academic", "attendance_pct", af["attendance_pct"], 75, "ATTENDANCE_LOW", a_id)
            triggered.append("ATTENDANCE_LOW")
        if af.get("gpa", 10.0) * 10.0 < 60:
            book.add(student_ref, "academic", "mark_pct", round(af["gpa"] * 10.0, 1), 60, "MARK_LOW", a_id)
            triggered.append("MARK_LOW")

        lf = records["lms"]["fields"]
        l_id = records["lms"]["provenance"]["record_ids"][0]
        if lf.get("inactivity_days", 0) >= 7:
            book.add(student_ref, "lms", "inactivity_days", lf["inactivity_days"], 7, "LMS_INACTIVE", l_id)
            triggered.append("LMS_INACTIVE")
        if lf.get("overdue_assignments", 0) >= 1:
            book.add(student_ref, "lms", "overdue_assignments", lf["overdue_assignments"], 1, "ASSIGNMENT_OVERDUE", l_id)
            triggered.append("ASSIGNMENT_OVERDUE")

        inf = records["internship"]["fields"]
        i_id = records["internship"]["provenance"]["record_ids"][0]
        if inf.get("missed_milestones", 0) >= 1:
            book.add(student_ref, "internship", "missed_milestones", inf["missed_milestones"], 1, "INTERNSHIP_MILESTONE", i_id)
            triggered.append("INTERNSHIP_MILESTONE")

        pf = records["placement"]["fields"]
        p_id = records["placement"]["provenance"]["record_ids"][0]
        if pf.get("missed_required_activities", 0) >= 1:
            book.add(student_ref, "placement", "missed_required_activities", pf["missed_required_activities"], 1, "PLACEMENT_ACTIVITY", p_id)
            triggered.append("PLACEMENT_ACTIVITY")

        return book, triggered


@dataclass
class ValidationFinding:
    code: str
    path: str
    detail: str


@dataclass
class GroundingReport:
    passed: bool
    findings: List[ValidationFinding] = field(default_factory=list)


def validate_packet_v2(
    packet: Dict[str, Any],
    book: EvidenceBook,
    triggered_signals: List[str],
    tolerance: float = ROUNDING_TOLERANCE,
) -> GroundingReport:
    """Verify citations, scope boundaries, trigger coverage, and <=0.5 numeric fidelity."""
    findings: List[ValidationFinding] = []
    cited_signals = set()

    for idx, sentence in enumerate(packet.get("rationale", [])):
        tags = re.findall(r"\b(ev-\d+)\b", sentence)
        if not tags:
            findings.append(ValidationFinding("UNCITED_CLAIM", f"rationale[{idx}]", "Sentence carries no [ev-N] citation."))
            continue

        allowed_numbers: List[float] = []
        for tag in tags:
            item = book.items.get(tag)
            if item is None:
                findings.append(ValidationFinding("UNSUPPORTED_CITATION", f"rationale[{idx}]", f"Citation '{tag}' not in EvidenceBook."))
                continue
            if not item.in_scope:
                findings.append(
                    ValidationFinding("PRIVACY_SCOPE_MISMATCH", f"rationale[{idx}]", f"Citation '{tag}' references out-of-scope data.")
                )
                continue
            cited_signals.add(item.signal_code)
            allowed_numbers.extend([item.value, item.threshold])

        stripped = re.sub(r"\[?\bev-\d+\b\]?", "", sentence)
        claimed_nums = [float(n) for n in re.findall(r"\b\d+(?:\.\d+)?\b", stripped)]
        for num in claimed_nums:
            if not allowed_numbers or min(abs(num - ref) for ref in allowed_numbers) > tolerance:
                findings.append(
                    ValidationFinding(
                        "UNSUPPORTED_NUMBER",
                        f"rationale[{idx}]",
                        f"Number {num} exceeds tolerance {tolerance} against cited evidence {allowed_numbers}.",
                    )
                )

    for step_idx, step in enumerate(packet.get("actions", [])):
        ref = step.get("evidence_ref", "")
        item = book.items.get(ref)
        if item is None:
            findings.append(ValidationFinding("UNSUPPORTED_CITATION", f"actions[{step_idx}]", f"Action ref '{ref}' missing from EvidenceBook."))
        elif not item.in_scope:
            findings.append(ValidationFinding("PRIVACY_SCOPE_MISMATCH", f"actions[{step_idx}]", f"Action ref '{ref}' is out of scope."))

    for sig in triggered_signals:
        if sig not in cited_signals:
            findings.append(ValidationFinding("MISSING_TRIGGER_COVERAGE", "rationale", f"Triggered signal '{sig}' was never cited."))

    return GroundingReport(passed=len(findings) == 0, findings=findings)


def format_evidence_table(book: EvidenceBook) -> str:
    header = f"{'Tag':<6} | {'Source':<10} | {'Metric':<26} | {'Value':<7} | {'Policy':<7} | {'Record ID':<10} | {'Scope'}"
    sep = "-" * len(header)
    rows = [header, sep]
    for item in book.items.values():
        rows.append(
            f"{item.tag:<6} | {item.source:<10} | {item.metric:<26} | {item.value:<7.1f} | {item.threshold:<7.1f} | {item.record_id:<10} | {item.in_scope}"
        )
    return "\n".join(rows)


def build_valid_syn0002_packet() -> Dict[str, Any]:
    return {
        "rationale": [
            "Attendance is 65% against the 75% threshold [ev-1], and marks average 58% vs the 60% floor [ev-2].",
            "LMS logs show 10 inactive days vs limit 7 [ev-3] and 3 overdue assignments vs limit 1 [ev-4].",
            "Internship missed 1 milestone [ev-5] and placement missed 2 required activities [ev-6].",
        ],
        "actions": [
            {"code": "faculty-check-in", "evidence_ref": "ev-1"},
            {"code": "student-study-plan", "evidence_ref": "ev-2"},
            {"code": "internship-review", "evidence_ref": "ev-5"},
            {"code": "placement-review", "evidence_ref": "ev-6"},
        ],
    }


def run_demo() -> None:
    print("=== Lab 09: Deep Research & Grounding (EvidenceBook + Tolerance Verifier) ===")
    book, triggered = DeepResearchInvestigator().investigate("SYN-0002", load_syn_0002())
    print("\nPrimary Evidence Table for SYN-0002:")
    print(format_evidence_table(book))
    report = validate_packet_v2(build_valid_syn0002_packet(), book, triggered)
    print(f"\nGrounding check passed={report.passed} | triggered={len(triggered)} | findings={len(report.findings)}")


def run_self_tests() -> None:
    book, triggered = DeepResearchInvestigator().investigate("SYN-0002", load_syn_0002())

    # 1. Valid packet (including rounded values within <= 0.5) passes cleanly
    valid_pkt = build_valid_syn0002_packet()
    valid_pkt["rationale"][0] = "Attendance is 65.4% against the 75% threshold [ev-1], and marks average 58% vs the 60% floor [ev-2]."
    res_ok = validate_packet_v2(valid_pkt, book, triggered)
    assert res_ok.passed, f"Expected pass within 0.5 tolerance, got {res_ok.findings}"
    print("[PASS] Grounded packet with <=0.5 numeric rounding passed all grounding gates")

    # 2. Hallucinated number (50% instead of 65%) rejected with UNSUPPORTED_NUMBER
    halluc_pkt = build_valid_syn0002_packet()
    halluc_pkt["rationale"][0] = "Attendance fell to 50% against 75% [ev-1], and marks average 58% vs 60% [ev-2]."
    res_num = validate_packet_v2(halluc_pkt, book, triggered)
    assert not res_num.passed and any(f.code == "UNSUPPORTED_NUMBER" for f in res_num.findings)
    print("[PASS] Hallucinated number (50% vs stored 65%) rejected with UNSUPPORTED_NUMBER")

    # 3. Uncited sentence rejected with UNCITED_CLAIM
    uncited_pkt = build_valid_syn0002_packet()
    uncited_pkt["rationale"].append("Student appears disengaged across coursework.")
    res_uncited = validate_packet_v2(uncited_pkt, book, triggered)
    assert not res_uncited.passed and any(f.code == "UNCITED_CLAIM" for f in res_uncited.findings)
    print("[PASS] Uncited rationale claim rejected with UNCITED_CLAIM")

    # 4. Out-of-scope citation (another student / external source) rejected with PRIVACY_SCOPE_MISMATCH
    book.add("SYN-0001", "academic", "attendance_pct", 72, 75, "ATTENDANCE_LOW", "a-0001")  # ev-7 out of scope
    scope_pkt = build_valid_syn0002_packet()
    scope_pkt["actions"][0]["evidence_ref"] = "ev-7"
    res_scope = validate_packet_v2(scope_pkt, book, triggered)
    assert not res_scope.passed and any(f.code == "PRIVACY_SCOPE_MISMATCH" for f in res_scope.findings)
    print("[PASS] Out-of-scope citation rejected with PRIVACY_SCOPE_MISMATCH")


if __name__ == "__main__":
    run_demo()
    print("\n--- Running Self-Tests ---")
    run_self_tests()
    print("All Lab 09 checks passed.")
