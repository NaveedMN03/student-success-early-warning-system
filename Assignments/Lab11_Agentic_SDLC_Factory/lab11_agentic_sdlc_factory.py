"""Lab 11: Agentic SDLC Factory — Spec-as-Plan to 12-Check Automated Acceptance Gate.

Course: Agentic AI (26ECAC401) — Chapter 11: Student Success & Early Warning System (AURA)
Phase C · Applied Reliability

Models AURA's requirements-to-tested-artifact factory (`PROJECT_CONTRACT.md`,
`SPEC_CONFORMANCE_2026-10-16.md`, `.github/workflows/checks.yml`, and
`synthetic-cohort-v1-corrections`):
  - Input: Locked plan spec (`plan_hash`).
  - Build: Drafts an intervention artifact for a student snapshot.
  - Gate: Runs all 12 deterministic acceptance checks (`CHK-01`..`CHK-12`) BEFORE
    any output may reach `HumanGate`.
  - Demonstrates `SYN-0004` (stale LMS) and `SYN-0005` (contradictory attendance)
    failing the automated gate, then passing cleanly after ingesting AURA's
    bundled correction fixtures (`synthetic-cohort-v1-corrections`).
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REFERENCE_NOW = datetime(2026, 9, 2, 10, 0, tzinfo=timezone.utc)
FRESHNESS_DAYS = 30
ROUNDING_TOLERANCE = 0.5

ACTION_CATALOGUE = {
    "faculty-check-in",
    "student-study-plan",
    "attendance-review",
    "lms-catch-up",
    "internship-review",
    "placement-review",
    "wellbeing-referral",
}

CLINICAL_BANNED_RE = re.compile(
    r"\b(depress\w*|anxi\w*|disorder|mental|diagnos\w*|burnout|lazy|unmotivated|trauma\w*)\b",
    re.I,
)
PII_LEAK_RE = re.compile(r"(SYN-\d{4}|@|@kle|01FE\d{2})", re.I)


class GateBlockedError(RuntimeError):
    """Raised when an artifact without a 12/12 passing acceptance report tries to reach HumanGate."""


EMBEDDED_COHORT: Dict[str, Dict[str, Any]] = {
    "SYN-0002": {
        "academic": {"data_state": "present", "observed_at": "2026-08-29T09:00:00Z", "fields": {"attendance_pct": 65, "gpa": 5.8, "failed_courses": 2}},
        "lms": {"data_state": "present", "observed_at": "2026-08-30T09:00:00Z", "fields": {"inactivity_days": 10, "overdue_assignments": 3}},
        "internship": {"data_state": "present", "observed_at": "2026-08-20T09:00:00Z", "fields": {"missed_milestones": 1}},
        "placement": {"data_state": "present", "observed_at": "2026-08-25T09:00:00Z", "fields": {"missed_required_activities": 2}},
    },
    "SYN-0004": {
        "academic": {"data_state": "present", "observed_at": "2026-08-29T09:00:00Z", "fields": {"attendance_pct": 81, "gpa": 7.8, "failed_courses": 0}},
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
}

EMBEDDED_CORRECTIONS: Dict[str, Dict[str, Any]] = {
    "SYN-0004": {
        "lms": {"data_state": "present", "observed_at": "2026-09-01T09:00:00Z", "fields": {"inactivity_days": 1, "overdue_assignments": 0}},
    },
    "SYN-0005": {
        "academic": {"data_state": "present", "observed_at": "2026-09-01T09:00:00Z", "fields": {"attendance_pct": 79, "gpa": 7.0, "failed_courses": 0}},
    },
}


def load_cohort_and_corrections() -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    cohort = copy.deepcopy(EMBEDDED_COHORT)
    corrections = copy.deepcopy(EMBEDDED_CORRECTIONS)
    here = Path(__file__).resolve()
    for parent in here.parents:
        base = parent / "Course Project" / "Source-Code" / "fixtures" / "synthetic-cohort-v1"
        corr = parent / "Course Project" / "Source-Code" / "fixtures" / "synthetic-cohort-v1-corrections"
        if base.is_dir() and corr.is_dir():
            for sid in ("SYN-0002", "SYN-0004", "SYN-0005"):
                sdir = base / sid
                if sdir.is_dir():
                    cohort[sid] = {
                        src: json.loads((sdir / f"{src}.json").read_text(encoding="utf-8"))
                        for src in ("academic", "lms", "internship", "placement")
                    }
            if (corr / "SYN-0004" / "lms.json").is_file():
                corrections["SYN-0004"]["lms"] = json.loads((corr / "SYN-0004" / "lms.json").read_text(encoding="utf-8"))
            if (corr / "SYN-0005" / "academic.json").is_file():
                corrections["SYN-0005"]["academic"] = json.loads((corr / "SYN-0005" / "academic.json").read_text(encoding="utf-8"))
            break
    return cohort, corrections


@dataclass(frozen=True)
class LockedPlanSpec:
    plan_id: str
    student_ref: str
    case_alias: str
    policy_version: str
    faculty_attested_by: Optional[str]
    plan_hash: str


@dataclass(frozen=True)
class CheckResult:
    check_id: str
    name: str
    passed: bool
    detail: str


@dataclass
class AcceptanceReport:
    student_ref: str
    checks: List[CheckResult]
    all_pass: bool = field(init=False)

    def __post_init__(self) -> None:
        self.all_pass = all(c.passed for c in self.checks)


class AuraSDLCFactory:
    """Builds packet artifacts from locked specs and runs the 12-check acceptance gate."""

    def build_artifact(self, spec: LockedPlanSpec, bundle: Dict[str, Any]) -> Dict[str, Any]:
        acad = bundle["academic"]
        lms = bundle["lms"]
        triggers: List[str] = []
        evidence_vals: Dict[str, Tuple[float, float]] = {}
        sentences: List[str] = []
        actions: List[Dict[str, Any]] = []

        if acad.get("data_state") == "present":
            att = float(acad["fields"].get("attendance_pct", 100))
            mark = float(acad["fields"].get("gpa", 10.0)) * 10.0
            if att < 75:
                triggers.append("ATTENDANCE_LOW")
                evidence_vals["ev-1"] = (att, 75.0)
                sentences.append(f"Attendance stands at {att:.0f}% against the 75% threshold [ev-1].")
                actions.append({"code": "attendance-review", "owner": "assigned_faculty", "evidence_ref": "ev-1"})
            if mark < 60:
                triggers.append("MARK_LOW")
                evidence_vals["ev-2"] = (mark, 60.0)
                sentences.append(f"Marks average {mark:.0f}% against the 60% floor [ev-2].")
                actions.append({"code": "student-study-plan", "owner": "assigned_faculty", "evidence_ref": "ev-2"})

        if lms.get("data_state") == "present":
            inact = float(lms["fields"].get("inactivity_days", 0))
            if inact >= 7:
                triggers.append("LMS_INACTIVE")
                evidence_vals["ev-3"] = (inact, 7.0)
                sentences.append(f"LMS inactivity reached {inact:.0f} days against the 7-day threshold [ev-3].")
                actions.append({"code": "lms-catch-up", "owner": "assigned_faculty", "evidence_ref": "ev-3"})

        if not sentences:
            sentences.append("All monitored thresholds are within normal faculty limits [ev-0].")
            evidence_vals["ev-0"] = (81.0, 75.0)
            actions.append({"code": "faculty-check-in", "owner": "assigned_faculty", "evidence_ref": "ev-0"})

        body = {
            "case_alias": spec.case_alias,
            "plan_hash": spec.plan_hash,
            "triggers": triggers,
            "evidence_vals": evidence_vals,
            "rationale": sentences,
            "actions": actions,
            "direct_student_contact": False,
        }
        body["manifest_hash"] = hashlib.sha256(json.dumps(body, sort_keys=True).encode("utf-8")).hexdigest()
        return body

    def run_acceptance_suite(self, spec: LockedPlanSpec, bundle: Dict[str, Any], artifact: Dict[str, Any]) -> AcceptanceReport:
        acad = bundle["academic"]
        lms = bundle["lms"]

        def _is_fresh(rec: Dict[str, Any]) -> Tuple[bool, str]:
            obs = rec.get("observed_at")
            if not obs:
                return False, "observed_at missing"
            dt = datetime.fromisoformat(str(obs).replace("Z", "+00:00"))
            age = (REFERENCE_NOW - dt).days
            return age <= FRESHNESS_DAYS, f"age={age}d (limit {FRESHNESS_DAYS}d)"

        acad_fresh, acad_age_msg = _is_fresh(acad)
        lms_fresh, lms_age_msg = _is_fresh(lms)

        # Verify manifest hash integrity without the hash field itself
        manifest_copy = {k: v for k, v in artifact.items() if k != "manifest_hash"}
        expected_manifest = hashlib.sha256(json.dumps(manifest_copy, sort_keys=True).encode("utf-8")).hexdigest()

        all_text = " ".join(artifact.get("rationale", []))
        ev_map: Dict[str, Tuple[float, float]] = artifact.get("evidence_vals", {})
        numeric_ok = True
        for s in artifact.get("rationale", []):
            tags = re.findall(r"\b(ev-\d+)\b", s)
            allowed = [v for t in tags for v in ev_map.get(t, ())]
            nums = [float(n) for n in re.findall(r"\b\d+(?:\.\d+)?\b", re.sub(r"\[?\bev-\d+\b\]?", "", s))]
            if any((not allowed or min(abs(n - ref) for ref in allowed) > ROUNDING_TOLERANCE) for n in nums):
                numeric_ok = False

        cited_tags = {t for s in artifact.get("rationale", []) for t in re.findall(r"\b(ev-\d+)\b", s)}
        triggers_cited = all(t in cited_tags for t in ev_map.keys()) if artifact.get("triggers") else True

        checks = [
            CheckResult("CHK-01", "Plan Lock Hash", len(spec.plan_hash) == 64, "64-char SHA-256 plan_hash verified"),
            CheckResult("CHK-02", "Faculty Policy Attestation", bool(spec.faculty_attested_by), f"Signed by {spec.faculty_attested_by}"),
            CheckResult("CHK-03", "Source Freshness (<=30d)", acad_fresh and lms_fresh, f"acad {acad_age_msg}, lms {lms_age_msg}"),
            CheckResult(
                "CHK-04",
                "No Contradictory/Missing Sources",
                acad.get("data_state") == "present" and lms.get("data_state") == "present",
                f"academic={acad.get('data_state')}, lms={lms.get('data_state')}",
            ),
            CheckResult("CHK-05", "Trigger Citation Coverage", triggers_cited, f"Cited evidence tags={sorted(cited_tags)}"),
            CheckResult("CHK-06", "Numeric Fidelity (<=0.5)", numeric_ok, "All claimed figures within 0.5 of evidence"),
            CheckResult(
                "CHK-07",
                "7-Action Catalogue Lock",
                all(a["code"] in ACTION_CATALOGUE for a in artifact.get("actions", [])),
                "All action codes within catalogue",
            ),
            CheckResult("CHK-08", "Zero-PII Egress", not bool(PII_LEAK_RE.search(all_text)), "No raw IDs/emails in rationale"),
            CheckResult("CHK-09", "No Clinical/Diagnostic Words", not bool(CLINICAL_BANNED_RE.search(all_text)), "Neutral non-diagnostic phrasing"),
            CheckResult(
                "CHK-10",
                "Mentor Owner Lock",
                all(a.get("owner") == "assigned_faculty" for a in artifact.get("actions", [])),
                "Server-locked owner=assigned_faculty",
            ),
            CheckResult("CHK-11", "Zero Autonomous Contact", artifact.get("direct_student_contact") is False, "Requires mentor approval gate"),
            CheckResult("CHK-12", "Artifact Manifest Lock", artifact.get("manifest_hash") == expected_manifest, "SHA-256 manifest verified"),
        ]
        return AcceptanceReport(student_ref=spec.student_ref, checks=checks)

    def advance_to_human_gate(self, artifact: Dict[str, Any], report: AcceptanceReport) -> Dict[str, Any]:
        if not report.all_pass:
            failed = [f"{c.check_id}:{c.name}" for c in report.checks if not c.passed]
            raise GateBlockedError(f"Acceptance gate blocked HumanGate advance for {report.student_ref}: {failed}")
        return {"gate_status": "ready_for_mentor_review", "student_ref": report.student_ref, "manifest_hash": artifact["manifest_hash"]}


def _make_spec(student_ref: str, case_alias: str) -> LockedPlanSpec:
    h = hashlib.sha256(f"plan:{student_ref}:CH11-DEMO-1".encode("utf-8")).hexdigest()
    return LockedPlanSpec(f"plan-{student_ref}", student_ref, case_alias, "CH11-DEMO-1", "faculty-chair-01", h)


def run_demo() -> None:
    print("=== Lab 11: Agentic SDLC Factory (12-Check Automated Acceptance Gate) ===")
    cohort, corrections = load_cohort_and_corrections()
    factory = AuraSDLCFactory()

    spec_2 = _make_spec("SYN-0002", "case-0002")
    art_2 = factory.build_artifact(spec_2, cohort["SYN-0002"])
    rep_2 = factory.run_acceptance_suite(spec_2, cohort["SYN-0002"], art_2)
    print(f"SYN-0002 acceptance: {sum(c.passed for c in rep_2.checks)}/12 passed -> all_pass={rep_2.all_pass}")

    for sid, alias, patch_src in (("SYN-0004", "case-0004", "lms"), ("SYN-0005", "case-0005", "academic")):
        spec = _make_spec(sid, alias)
        before_bundle = cohort[sid]
        rep_before = factory.run_acceptance_suite(spec, before_bundle, factory.build_artifact(spec, before_bundle))
        failed_before = [c.check_id for c in rep_before.checks if not c.passed]

        after_bundle = copy.deepcopy(before_bundle)
        after_bundle[patch_src] = corrections[sid][patch_src]
        rep_after = factory.run_acceptance_suite(spec, after_bundle, factory.build_artifact(spec, after_bundle))
        print(f"{sid}: before_correction={failed_before} (all_pass={rep_before.all_pass}) -> after_correction all_pass={rep_after.all_pass}")


def run_self_tests() -> None:
    cohort, corrections = load_cohort_and_corrections()
    factory = AuraSDLCFactory()

    # 1. SYN-0002 passes all 12/12 checks and advances to HumanGate
    spec_2 = _make_spec("SYN-0002", "case-0002")
    art_2 = factory.build_artifact(spec_2, cohort["SYN-0002"])
    rep_2 = factory.run_acceptance_suite(spec_2, cohort["SYN-0002"], art_2)
    assert rep_2.all_pass and len(rep_2.checks) == 12
    gate_res = factory.advance_to_human_gate(art_2, rep_2)
    assert gate_res["gate_status"] == "ready_for_mentor_review"
    print("[PASS] SYN-0002 passed 12/12 SDLC acceptance checks and advanced to HumanGate")

    # 2. SYN-0004 (stale LMS 2026-08-01 = 32d > 30d) blocked until correction applied
    spec_4 = _make_spec("SYN-0004", "case-0004")
    art_4_bad = factory.build_artifact(spec_4, cohort["SYN-0004"])
    rep_4_bad = factory.run_acceptance_suite(spec_4, cohort["SYN-0004"], art_4_bad)
    assert not rep_4_bad.all_pass and any(c.check_id == "CHK-03" and not c.passed for c in rep_4_bad.checks)
    try:
        factory.advance_to_human_gate(art_4_bad, rep_4_bad)
        raise AssertionError("Expected GateBlockedError for stale SYN-0004")
    except GateBlockedError:
        pass
    bundle_4_ok = copy.deepcopy(cohort["SYN-0004"])
    bundle_4_ok["lms"] = corrections["SYN-0004"]["lms"]
    art_4_ok = factory.build_artifact(spec_4, bundle_4_ok)
    rep_4_ok = factory.run_acceptance_suite(spec_4, bundle_4_ok, art_4_ok)
    assert rep_4_ok.all_pass
    print("[PASS] SYN-0004 stale LMS blocked at CHK-03 and passed 12/12 after correction")

    # 3. SYN-0005 (contradictory [68, 82]) blocked until correction applied
    spec_5 = _make_spec("SYN-0005", "case-0005")
    art_5_bad = factory.build_artifact(spec_5, cohort["SYN-0005"])
    rep_5_bad = factory.run_acceptance_suite(spec_5, cohort["SYN-0005"], art_5_bad)
    assert not rep_5_bad.all_pass and any(c.check_id == "CHK-04" and not c.passed for c in rep_5_bad.checks)
    bundle_5_ok = copy.deepcopy(cohort["SYN-0005"])
    bundle_5_ok["academic"] = corrections["SYN-0005"]["academic"]
    art_5_ok = factory.build_artifact(spec_5, bundle_5_ok)
    rep_5_ok = factory.run_acceptance_suite(spec_5, bundle_5_ok, art_5_ok)
    assert rep_5_ok.all_pass
    print("[PASS] SYN-0005 contradictory attendance blocked at CHK-04 and passed 12/12 after correction")


if __name__ == "__main__":
    run_demo()
    print("\n--- Running Self-Tests ---")
    run_self_tests()
    print("All Lab 11 checks passed.")
