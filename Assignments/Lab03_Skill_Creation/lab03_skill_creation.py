"""Lab 03: Skill Creation — Reusable AURA Blueprint & Packet-v2 Formatting Skills.

Course: Agentic AI (26ECAC401) — Chapter 11: Student Success & Early Warning System (AURA)
Phase A · Foundations

Packages repeatable AURA capabilities as reusable, case-agnostic skills with
strict input/output contracts modeled on `planning.ts`, `catalogue.ts`, and `packet-v2.ts`:
  1. `PlanBlueprintSkill`: converts validated mentor scope + policy inputs into an
     immutable locked blueprint (`plan_hash`).
  2. `PacketV2FormatSkill`: produces a grounded intervention draft packet constrained
     to AURA's 7 approved `ACTION_CATALOGUE` codes, `2..5` rationale sentences,
     `1..4` action steps, `due_in_days` in `1..14`, and server-locked
     `owner="assigned_faculty"`.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Dict, Generic, List, Protocol, Tuple, TypeVar

ACTION_CATALOGUE: Dict[str, str] = {
    "faculty-check-in": "Schedule a 20-minute academic check-in with the assigned mentor",
    "student-study-plan": "Agree a weekly study plan with the assigned mentor",
    "attendance-review": "Review attendance barriers and agree an attendance plan with the mentor",
    "lms-catch-up": "Agree a catch-up schedule for overdue learning activities",
    "internship-review": "Review missed internship milestones with the assigned mentor",
    "placement-review": "Review placement preparation activities with the assigned mentor",
    "wellbeing-referral": "Ask the mentor whether an optional support-service referral is appropriate",
}

SERVER_LOCKED_OWNER = "assigned_faculty"


class SkillValidationError(ValueError):
    """Raised when a skill input or output violates its typed AURA contract."""


I = TypeVar("I")
O = TypeVar("O")


class AuraSkill(Protocol, Generic[I, O]):
    """Reusable typed skill contract (instructions + schema + deterministic executor)."""

    name: str
    version: str

    def invoke(self, payload: I) -> O:
        ...


@dataclass(frozen=True)
class PlanBlueprintInput:
    mentor_id: str
    department: str
    goal: str
    case_aliases: Tuple[str, ...]
    policy_version: str


@dataclass(frozen=True)
class PlanBlueprintOutput:
    skill_name: str
    status: str
    mentor_id: str
    department: str
    case_aliases: Tuple[str, ...]
    policy_version: str
    plan_hash: str


class PlanBlueprintSkill:
    """Case-agnostic skill producing a locked SHA-256 plan blueprint."""

    name = "plan_blueprint_skill"
    version = "v1"

    def invoke(self, payload: PlanBlueprintInput) -> PlanBlueprintOutput:
        if not payload.mentor_id.strip():
            raise SkillValidationError("mentor_id must be non-empty.")
        if not payload.case_aliases:
            raise SkillValidationError("At least one aliased student must be in scope.")
        if not payload.policy_version.strip():
            raise SkillValidationError("policy_version is required.")

        canonical = json.dumps(asdict(payload), sort_keys=True)
        plan_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return PlanBlueprintOutput(
            skill_name=self.name,
            status="locked",
            mentor_id=payload.mentor_id,
            department=payload.department,
            case_aliases=payload.case_aliases,
            policy_version=payload.policy_version,
            plan_hash=plan_hash,
        )


@dataclass(frozen=True)
class ActionStepSpec:
    code: str
    talking_point: str
    due_in_days: int
    evidence_ref: str
    requested_owner: str = SERVER_LOCKED_OWNER


@dataclass(frozen=True)
class ActionStepOutput:
    code: str
    label: str
    talking_point: str
    due_in_days: int
    evidence_ref: str
    owner: str


@dataclass(frozen=True)
class PacketV2Input:
    case_alias: str
    plan_hash: str
    risk_band: str
    risk_score: int
    rationale_sentences: Tuple[str, ...]
    steps: Tuple[ActionStepSpec, ...]


@dataclass(frozen=True)
class PacketV2Output:
    skill_name: str
    schema_version: str
    case_alias: str
    plan_hash: str
    risk_band: str
    risk_score: int
    rationale_sentences: Tuple[str, ...]
    actions: Tuple[ActionStepOutput, ...]
    rendered_markdown: str


class PacketV2FormatSkill:
    """Formats and strictly validates a packet-v2 early-warning intervention draft."""

    name = "packet_v2_format_skill"
    version = "packet-v2"

    def invoke(self, payload: PacketV2Input) -> PacketV2Output:
        if len(payload.rationale_sentences) < 2 or len(payload.rationale_sentences) > 5:
            raise SkillValidationError(
                f"rationale_sentences must contain 2..5 sentences (got {len(payload.rationale_sentences)})."
            )
        for sentence in payload.rationale_sentences:
            if not (12 <= len(sentence) <= 320):
                raise SkillValidationError(f"Rationale sentence length out of 12..320 bounds: {len(sentence)}")

        if len(payload.steps) < 1 or len(payload.steps) > 4:
            raise SkillValidationError(f"steps must contain 1..4 actions (got {len(payload.steps)}).")

        formatted_steps: List[ActionStepOutput] = []
        for step in payload.steps:
            if step.code not in ACTION_CATALOGUE:
                raise SkillValidationError(
                    f"Action code '{step.code}' is outside the 7-action AURA catalogue."
                )
            if step.requested_owner != SERVER_LOCKED_OWNER:
                raise SkillValidationError(
                    f"Server locks owner to '{SERVER_LOCKED_OWNER}'; got '{step.requested_owner}'."
                )
            if not (1 <= step.due_in_days <= 14):
                raise SkillValidationError(
                    f"due_in_days must be in 1..14 (got {step.due_in_days})."
                )
            if not (4 <= len(step.talking_point) <= 200):
                raise SkillValidationError(
                    f"talking_point length must be in 4..200 chars (got {len(step.talking_point)})."
                )
            formatted_steps.append(
                ActionStepOutput(
                    code=step.code,
                    label=ACTION_CATALOGUE[step.code],
                    talking_point=step.talking_point,
                    due_in_days=step.due_in_days,
                    evidence_ref=step.evidence_ref,
                    owner=SERVER_LOCKED_OWNER,
                )
            )

        lines = [
            f"### Support Draft — {payload.case_alias} ({payload.risk_band.upper()} risk, score {payload.risk_score}/100)",
            f"Plan Lock: `{payload.plan_hash[:12]}...`",
            "",
            "**Evidence-Grounded Summary:**",
            *[f"- {s}" for s in payload.rationale_sentences],
            "",
            "**Mentor-Owned Support Actions:**",
            *[
                f"{idx}. `{a.code}` ({a.owner}, due in {a.due_in_days}d, ref {a.evidence_ref}): "
                f"{a.label} — {a.talking_point}"
                for idx, a in enumerate(formatted_steps, 1)
            ],
        ]
        return PacketV2Output(
            skill_name=self.name,
            schema_version=self.version,
            case_alias=payload.case_alias,
            plan_hash=payload.plan_hash,
            risk_band=payload.risk_band,
            risk_score=payload.risk_score,
            rationale_sentences=payload.rationale_sentences,
            actions=tuple(formatted_steps),
            rendered_markdown="\n".join(lines),
        )


def run_demo() -> None:
    print("=== Lab 03: Skill Creation (PlanBlueprintSkill & PacketV2FormatSkill) ===")
    plan_skill = PlanBlueprintSkill()
    format_skill = PacketV2FormatSkill()

    blueprint = plan_skill.invoke(
        PlanBlueprintInput(
            mentor_id="mentor-01",
            department="CSE-AI",
            goal="Draft evidence-backed early-warning support for flagged mentees.",
            case_aliases=("case-0001", "case-0002"),
            policy_version="CH11-DEMO-1",
        )
    )
    print(f"Locked blueprint hash: {blueprint.plan_hash[:16]}... | scope={blueprint.case_aliases}\n")

    syn1_draft = format_skill.invoke(
        PacketV2Input(
            case_alias="case-0001",
            plan_hash=blueprint.plan_hash,
            risk_band="medium",
            risk_score=30,
            rationale_sentences=(
                "Attendance stands at 72%, which is below the 75% policy threshold [ev-1].",
                "One LMS assignment is currently overdue against the 1-task threshold [ev-2].",
            ),
            steps=(
                ActionStepSpec("attendance-review", "Check morning lab schedule constraints.", 5, "ev-1"),
                ActionStepSpec("lms-catch-up", "Prioritize submitting the overdue task.", 7, "ev-2"),
            ),
        )
    )
    print(syn1_draft.rendered_markdown)


def run_self_tests() -> None:
    plan_skill = PlanBlueprintSkill()
    format_skill = PacketV2FormatSkill()

    # 1. Reuse the exact same skill instances across SYN-0001 (medium) and SYN-0002 (high)
    bp = plan_skill.invoke(
        PlanBlueprintInput("mentor-01", "CSE-AI", "Semester VI review", ("case-0001", "case-0002"), "CH11-DEMO-1")
    )
    out_1 = format_skill.invoke(
        PacketV2Input(
            case_alias="case-0001",
            plan_hash=bp.plan_hash,
            risk_band="medium",
            risk_score=30,
            rationale_sentences=(
                "Attendance is 72% against the 75% threshold [ev-1].",
                "One overdue LMS task triggers early support [ev-2].",
            ),
            steps=(ActionStepSpec("attendance-review", "Agree morning check-in routine.", 5, "ev-1"),),
        )
    )
    out_2 = format_skill.invoke(
        PacketV2Input(
            case_alias="case-0002",
            plan_hash=bp.plan_hash,
            risk_band="high",
            risk_score=100,
            rationale_sentences=(
                "Attendance dropped to 65% and marks average 58% with 2 failed courses [ev-1].",
                "LMS shows 10 days of inactivity and 3 overdue assignments [ev-2].",
                "Internship missed 1/4 milestones and placement missed 2/5 activities [ev-3, ev-4].",
            ),
            steps=(
                ActionStepSpec("faculty-check-in", "Hold an immediate 20-minute review.", 2, "ev-1"),
                ActionStepSpec("student-study-plan", "Break backlog recovery into weekly milestones.", 4, "ev-1"),
                ActionStepSpec("internship-review", "Clarify remaining internship deliverables.", 6, "ev-3"),
                ActionStepSpec("placement-review", "Schedule missed placement prep activities.", 10, "ev-4"),
            ),
        )
    )
    assert out_1.case_alias == "case-0001" and len(out_1.actions) == 1
    assert out_2.case_alias == "case-0002" and len(out_2.actions) == 4
    assert all(a.owner == SERVER_LOCKED_OWNER for a in out_1.actions + out_2.actions)
    print("[PASS] Reused PlanBlueprintSkill and PacketV2FormatSkill across SYN-0001 and SYN-0002 without code changes")

    # 2. Out-of-catalogue action rejected
    try:
        format_skill.invoke(
            PacketV2Input(
                case_alias="case-0001",
                plan_hash=bp.plan_hash,
                risk_band="medium",
                risk_score=30,
                rationale_sentences=("Sentence one is valid [ev-1].", "Sentence two is valid [ev-2]."),
                steps=(ActionStepSpec("detention-notice", "Not allowed.", 3, "ev-1"),),
            )
        )
        raise AssertionError("Expected SkillValidationError for out-of-catalogue action")
    except SkillValidationError:
        pass
    print("[PASS] Out-of-catalogue action code rejected by PacketV2FormatSkill")

    # 3. Attempting to override server-locked owner fails
    try:
        format_skill.invoke(
            PacketV2Input(
                case_alias="case-0001",
                plan_hash=bp.plan_hash,
                risk_band="medium",
                risk_score=30,
                rationale_sentences=("Sentence one is valid [ev-1].", "Sentence two is valid [ev-2]."),
                steps=(ActionStepSpec("faculty-check-in", "Discuss attendance.", 3, "ev-1", requested_owner="autonomous_bot"),),
            )
        )
        raise AssertionError("Expected SkillValidationError for non-faculty owner")
    except SkillValidationError:
        pass
    print("[PASS] Non-faculty action owner blocked by server-lock contract")

    # 4. Out-of-bounds due_in_days or rationale count fails
    try:
        format_skill.invoke(
            PacketV2Input(
                case_alias="case-0001",
                plan_hash=bp.plan_hash,
                risk_band="medium",
                risk_score=30,
                rationale_sentences=("Only one sentence provided [ev-1].",),
                steps=(ActionStepSpec("faculty-check-in", "Discuss attendance.", 21, "ev-1"),),
            )
        )
        raise AssertionError("Expected SkillValidationError for schema bounds")
    except SkillValidationError:
        pass
    print("[PASS] Schema bounds (2..5 sentences, due_in_days 1..14) enforced")


if __name__ == "__main__":
    run_demo()
    print("\n--- Running Self-Tests ---")
    run_self_tests()
    print("All Lab 03 checks passed.")
