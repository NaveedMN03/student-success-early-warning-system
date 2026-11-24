"""Lab 10: Ops Resilience — Closed-Vocabulary Diagnosis, Targeted Patching & Failover.

Course: Agentic AI (26ECAC401) — Chapter 11: Student Success & Early Warning System (AURA)
Phase C · Applied Reliability

Models AURA's self-healing and provider resilience stack (`diagnosis.ts`,
`provider.ts`, `faults.ts`, `unavailable.ts`):
  - Closed-vocabulary `DIAGNOSIS_TEXT` mapped to exact failing JSON paths.
  - Targeted `apply_targeted_patch()`: repairs ONLY the offending rationale
    sentence or action item while keeping passing fields byte-identical.
  - Bounded `MAX_REPAIRS = 2` retry loop escalating persistent faults to `needs_human`.
  - `ProviderFailoverChain` (`groq/qwen3.8-27b` -> `gemini-3.1-flash-lite` ->
    `local-qwen`): on total quota exhaustion (`HTTP 429`), pauses safely in
    `ai_unavailable_retry` (`AI_QUOTA_WAIT`) with ZERO synthetic template fallback.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

MAX_REPAIRS = 2
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

DIAGNOSIS_TEXT: Dict[str, str] = {
    "CATALOGUE_OR_DOMAIN_MISMATCH": "Action outside the approved catalogue",
    "MISSING_TRIGGER_COVERAGE": "A triggering signal was not cited",
    "UNCITED_CLAIM": "A sentence without an evidence citation",
    "UNSUPPORTED_AUTHORITY_OR_DIAGNOSIS": "Unsafe or diagnostic wording",
    "UNSUPPORTED_NUMBER": "A number not found in the evidence",
    "JUDGE_GROUNDING_LOW": "Judge: claims not grounded in the cited evidence",
}


@dataclass(frozen=True)
class RepairDiagnosis:
    code: str
    path: str
    diagnosis: str
    instruction: str


@dataclass
class SelfHealResult:
    status: str  # "repaired" | "needs_human"
    attempts: int
    packet: Dict[str, Any]
    history: List[List[RepairDiagnosis]] = field(default_factory=list)


def _hash_obj(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode("utf-8")).hexdigest()


def diagnose_packet(packet: Dict[str, Any], evidence: Dict[str, Dict[str, Any]]) -> List[RepairDiagnosis]:
    """Deterministic closed-vocabulary diagnoser emitting targeted path fixes."""
    issues: List[RepairDiagnosis] = []

    for idx, sentence in enumerate(packet.get("rationale", [])):
        tags = re.findall(r"\b(ev-\d+)\b", sentence)
        if not tags:
            issues.append(
                RepairDiagnosis(
                    code="UNCITED_CLAIM",
                    path=f"rationale[{idx}]",
                    diagnosis=DIAGNOSIS_TEXT["UNCITED_CLAIM"],
                    instruction=f"Rewrite rationale[{idx}] to cite an authoritative ev-N tag from the snapshot.",
                )
            )
            continue

        allowed: List[float] = []
        for tag in tags:
            if tag in evidence:
                allowed.extend([float(evidence[tag]["value"]), float(evidence[tag]["threshold"])])

        stripped = re.sub(r"\[?\bev-\d+\b\]?", "", sentence)
        nums = [float(n) for n in re.findall(r"\b\d+(?:\.\d+)?\b", stripped)]
        if any((not allowed or min(abs(n - ref) for ref in allowed) > ROUNDING_TOLERANCE) for n in nums):
            issues.append(
                RepairDiagnosis(
                    code="UNSUPPORTED_NUMBER",
                    path=f"rationale[{idx}]",
                    diagnosis=DIAGNOSIS_TEXT["UNSUPPORTED_NUMBER"],
                    instruction=f"Replace unverified numbers in rationale[{idx}] with exact values from {tags}.",
                )
            )

        if re.search(r"\b(diagnosed|disorder|lazy|clinical)\b", sentence, re.I):
            issues.append(
                RepairDiagnosis(
                    code="UNSUPPORTED_AUTHORITY_OR_DIAGNOSIS",
                    path=f"rationale[{idx}]",
                    diagnosis=DIAGNOSIS_TEXT["UNSUPPORTED_AUTHORITY_OR_DIAGNOSIS"],
                    instruction=f"Remove diagnostic wording in rationale[{idx}]; state metrics neutrally.",
                )
            )

    for idx, action in enumerate(packet.get("actions", [])):
        if action.get("code") not in ACTION_CATALOGUE:
            issues.append(
                RepairDiagnosis(
                    code="CATALOGUE_OR_DOMAIN_MISMATCH",
                    path=f"actions[{idx}]",
                    diagnosis=DIAGNOSIS_TEXT["CATALOGUE_OR_DOMAIN_MISMATCH"],
                    instruction=f"Replace actions[{idx}].code with an approved 7-catalogue code.",
                )
            )

    return issues


def apply_targeted_patch(
    packet: Dict[str, Any],
    diagnoses: List[RepairDiagnosis],
    evidence: Dict[str, Dict[str, Any]],
    unfixable_paths: Optional[set] = None,
) -> Dict[str, Any]:
    """Repair ONLY paths named in diagnoses; leave all passing fields untouched."""
    patched = copy.deepcopy(packet)
    unfixable = unfixable_paths or set()

    for diag in diagnoses:
        if diag.path in unfixable:
            continue
        if diag.path.startswith("rationale["):
            idx = int(diag.path.split("[")[1].rstrip("]"))
            if diag.code == "UNSUPPORTED_NUMBER":
                tags = re.findall(r"\b(ev-\d+)\b", patched["rationale"][idx])
                ev_tag = tags[0] if tags else "ev-1"
                ev = evidence[ev_tag]
                patched["rationale"][idx] = (
                    f"{ev['label']} is {ev['value']} against policy threshold {ev['threshold']} [{ev_tag}]."
                )
            elif diag.code == "UNCITED_CLAIM":
                patched["rationale"][idx] = (
                    f"Overdue LMS count is {evidence['ev-2']['value']} against threshold {evidence['ev-2']['threshold']} [ev-2]."
                )
            elif diag.code == "UNSUPPORTED_AUTHORITY_OR_DIAGNOSIS":
                patched["rationale"][idx] = (
                    f"Attendance stands at {evidence['ev-1']['value']}% below {evidence['ev-1']['threshold']}% [ev-1]."
                )
        elif diag.path.startswith("actions["):
            idx = int(diag.path.split("[")[1].rstrip("]"))
            if diag.code == "CATALOGUE_OR_DOMAIN_MISMATCH":
                patched["actions"][idx]["code"] = "attendance-review"
    return patched


def run_self_healing_loop(
    initial_packet: Dict[str, Any],
    evidence: Dict[str, Dict[str, Any]],
    max_repairs: int = MAX_REPAIRS,
    unfixable_paths: Optional[set] = None,
) -> SelfHealResult:
    """Validate -> Diagnose -> Targeted Repair up to max_repairs, else needs_human."""
    current = copy.deepcopy(initial_packet)
    history: List[List[RepairDiagnosis]] = []
    attempts = 0

    while True:
        diags = diagnose_packet(current, evidence)
        if not diags:
            return SelfHealResult(status="repaired", attempts=attempts, packet=current, history=history)
        if attempts >= max_repairs:
            return SelfHealResult(status="needs_human", attempts=attempts, packet=current, history=history)
        history.append(diags)
        attempts += 1
        current = apply_targeted_patch(current, diags, evidence, unfixable_paths=unfixable_paths)


@dataclass(frozen=True)
class ProviderCallOutcome:
    status: str  # "ok" | "ai_unavailable_retry"
    provider: Optional[str]
    model: Optional[str]
    code: Optional[str]
    draft: Optional[Dict[str, Any]]
    attempts: List[Dict[str, Any]]


class ProviderFailoverChain:
    """Failover chain matching AURA provider.ts (Groq -> Gemini Flash-Lite -> Local Qwen)."""

    CHAIN = (
        ("groq", "qwen/qwen3.8-27b"),
        ("gemini", "gemini-3.1-flash-lite"),
        ("local", "qwen-local-fallback"),
    )

    def invoke(self, provider_responses: Dict[str, Callable[[], Dict[str, Any]]]) -> ProviderCallOutcome:
        attempts: List[Dict[str, Any]] = []
        for provider, model in self.CHAIN:
            fn = provider_responses.get(provider)
            if fn is None:
                attempts.append({"provider": provider, "model": model, "status": "unavailable"})
                continue
            try:
                draft = fn()
                attempts.append({"provider": provider, "model": model, "status": "ok"})
                return ProviderCallOutcome("ok", provider, model, None, draft, attempts)
            except RuntimeError as exc:
                attempts.append({"provider": provider, "model": model, "status": "failed", "reason": str(exc)})

        return ProviderCallOutcome(
            status="ai_unavailable_retry",
            provider=None,
            model=None,
            code="AI_QUOTA_WAIT",
            draft=None,  # Hard AURA invariant: zero fake template drafts on total AI outage
            attempts=attempts,
        )


DEFAULT_EVIDENCE: Dict[str, Dict[str, Any]] = {
    "ev-1": {"label": "Attendance", "value": 65, "threshold": 75},
    "ev-2": {"label": "Overdue assignments", "value": 3, "threshold": 1},
}


def run_demo() -> None:
    print("=== Lab 10: Ops Resilience (Targeted Self-Healing & Provider Failover) ===")
    faulty = {
        "rationale": [
            "Attendance dropped to 42% vs threshold 75% [ev-1].",  # injected UNSUPPORTED_NUMBER
            "Overdue assignments is 3 against policy threshold 1 [ev-2].",  # valid, untouched
        ],
        "actions": [{"code": "faculty-check-in", "evidence_ref": "ev-1"}],
    }
    res = run_self_healing_loop(faulty, DEFAULT_EVIDENCE)
    print(f"Targeted repair -> status={res.status} attempts={res.attempts} repaired_line='{res.packet['rationale'][0]}'")

    chain = ProviderFailoverChain()
    failover_ok = chain.invoke(
        {
            "groq": lambda: (_ for _ in ()).throw(RuntimeError("HTTP 429 TPM quota")),
            "gemini": lambda: {"summary": "Generated via Gemini 3.1 Flash-Lite backup"},
        }
    )
    print(f"Failover outcome -> status={failover_ok.status} provider={failover_ok.provider} model={failover_ok.model}")


def run_self_tests() -> None:
    # 1. Single injected UNSUPPORTED_NUMBER repairs in 1 attempt while untouched fields keep identical SHA-256 hash
    untouched_sentence = "Overdue assignments is 3 against policy threshold 1 [ev-2]."
    untouched_actions = [{"code": "faculty-check-in", "evidence_ref": "ev-1"}]
    pkt_1 = {
        "rationale": ["Attendance dropped to 42% vs threshold 75% [ev-1].", untouched_sentence],
        "actions": copy.deepcopy(untouched_actions),
    }
    res_1 = run_self_healing_loop(pkt_1, DEFAULT_EVIDENCE)
    assert res_1.status == "repaired" and res_1.attempts == 1
    assert _hash_obj(res_1.packet["rationale"][1]) == _hash_obj(untouched_sentence)
    assert _hash_obj(res_1.packet["actions"]) == _hash_obj(untouched_actions)
    print("[PASS] Single UNSUPPORTED_NUMBER repaired on attempt 1 with untouched fields byte-identical")

    # 2. Compound fault (CATALOGUE_OR_DOMAIN_MISMATCH + UNCITED_CLAIM) repairs cleanly within budget
    pkt_2 = {
        "rationale": [
            "Attendance is 65 against threshold 75 [ev-1].",
            "Student needs help right away.",
        ],
        "actions": [{"code": "expel-immediately", "evidence_ref": "ev-1"}],
    }
    res_2 = run_self_healing_loop(pkt_2, DEFAULT_EVIDENCE)
    assert res_2.status == "repaired" and res_2.attempts <= MAX_REPAIRS
    assert res_2.packet["actions"][0]["code"] in ACTION_CATALOGUE
    print("[PASS] Compound fault repaired inside MAX_REPAIRS=2 budget")

    # 3. Unfixable injected fault exhausts budget at 2 repairs and escalates cleanly to needs_human
    pkt_3 = {
        "rationale": ["Attendance dropped to 40% vs 75% [ev-1].", untouched_sentence],
        "actions": copy.deepcopy(untouched_actions),
    }
    res_3 = run_self_healing_loop(pkt_3, DEFAULT_EVIDENCE, unfixable_paths={"rationale[0]"})
    assert res_3.status == "needs_human" and res_3.attempts == MAX_REPAIRS
    print("[PASS] Persistent unfixable fault halted at MAX_REPAIRS=2 and escalated to needs_human")

    # 4. Total provider outage (429s) returns ai_unavailable_retry with ZERO fake template draft
    chain = ProviderFailoverChain()
    all_down = chain.invoke(
        {
            "groq": lambda: (_ for _ in ()).throw(RuntimeError("HTTP 429")),
            "gemini": lambda: (_ for _ in ()).throw(RuntimeError("HTTP 429")),
            "local": lambda: (_ for _ in ()).throw(RuntimeError("Connection refused")),
        }
    )
    assert all_down.status == "ai_unavailable_retry"
    assert all_down.code == "AI_QUOTA_WAIT"
    assert all_down.draft is None
    print("[PASS] All-providers-down returned ai_unavailable_retry (AI_QUOTA_WAIT) with draft=None")


if __name__ == "__main__":
    run_demo()
    print("\n--- Running Self-Tests ---")
    run_self_tests()
    print("All Lab 10 checks passed.")
