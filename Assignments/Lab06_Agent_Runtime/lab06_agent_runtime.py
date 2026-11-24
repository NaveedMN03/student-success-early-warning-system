"""Lab 06: Agent Runtime — Leases, Idempotency Keys, Checkpoints & Append-Only Audit.

Course: Agentic AI (26ECAC401) — Chapter 11: Student Success & Early Warning System (AURA)
Phase A/B · Durable Runtime Layer

Models AURA's runtime engine (`service.ts`, `lease.ts`, `001_core.sql`, `004_chapter11.sql`):
  - Enforces step budget + human approval gate before publication.
  - Manages 180-second worker leases (`lease_token`, `lease_until`) with
    dead-lease sweeps (`LEASE_EXPIRED`) and bounded crash retries (`max_retries=3`).
  - Deduplicates mutations via UUID `Idempotency-Key` in `command_receipts`.
  - Checkpoints after completed stages so crash recovery resumes cleanly without
    re-executing completed work.
  - Enforces `persist_then_audit()` and SQLite triggers (`reject_audit_update`,
    `reject_audit_delete`) guaranteeing append-only tamper resistance.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

LEASE_SECONDS = 180
MAX_RETRIES = 3


class SimulatedWorkerCrash(RuntimeError):
    """Injected crash used to verify checkpoint resume and lease expiration."""


class BudgetExceededError(RuntimeError):
    """Raised when a job exceeds its allowed runtime step budget."""


@dataclass
class JobState:
    run_id: str
    student_ref: str
    status: str
    current_stage_idx: int
    retries: int
    checkpoint: Dict[str, Any]
    lease_token: Optional[str]
    lease_until: Optional[float]


STAGES = ["collect_sources", "score_risk", "draft_packet", "human_gate", "publish_plan"]


class AuraRuntime:
    """In-memory SQLite durable agent runtime with triggers, leases, and receipts."""

    def __init__(self, step_budget: int = 10) -> None:
        self.step_budget = step_budget
        self.conn = sqlite3.connect(":memory:")
        self._init_schema()
        self.executed_stages: List[str] = []

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE runtime_jobs (
                run_id TEXT PRIMARY KEY,
                student_ref TEXT NOT NULL,
                status TEXT NOT NULL,
                current_stage_idx INTEGER NOT NULL,
                retries INTEGER NOT NULL DEFAULT 0,
                checkpoint_json TEXT NOT NULL,
                lease_token TEXT,
                lease_until REAL
            );
            CREATE TABLE command_receipts (
                idempotency_key TEXT PRIMARY KEY,
                command_name TEXT NOT NULL,
                response_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE audit_events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                stage TEXT NOT NULL,
                intent TEXT NOT NULL,
                input_json TEXT NOT NULL,
                output_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TRIGGER reject_audit_update
            BEFORE UPDATE ON audit_events
            BEGIN
                SELECT RAISE(ABORT, 'append-only audit_events cannot be modified');
            END;
            CREATE TRIGGER reject_audit_delete
            BEFORE DELETE ON audit_events
            BEGIN
                SELECT RAISE(ABORT, 'append-only audit_events cannot be deleted');
            END;
            """
        )
        self.conn.commit()

    def create_job(self, run_id: str, student_ref: str, idempotency_key: str) -> Dict[str, Any]:
        """Idempotently enqueue a review job using command_receipts."""
        existing = self.conn.execute(
            "SELECT response_json FROM command_receipts WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        if existing is not None:
            cached = json.loads(existing[0])
            cached["replayed_from_receipt"] = True
            return cached

        with self.conn:
            self.conn.execute(
                "INSERT INTO runtime_jobs (run_id, student_ref, status, current_stage_idx, retries, checkpoint_json) "
                "VALUES (?, ?, 'queued', 0, 0, '{}')",
                (run_id, student_ref),
            )
            response = {"run_id": run_id, "student_ref": student_ref, "status": "queued", "replayed_from_receipt": False}
            self.conn.execute(
                "INSERT INTO command_receipts (idempotency_key, command_name, response_json, created_at) "
                "VALUES (?, 'create_job', ?, ?)",
                (idempotency_key, json.dumps(response), datetime.now(timezone.utc).isoformat()),
            )
            self.conn.execute(
                "INSERT INTO audit_events (run_id, stage, intent, input_json, output_json, created_at) "
                "VALUES (?, 'enqueue', 'create_job', ?, ?, ?)",
                (run_id, json.dumps({"student_ref": student_ref}), json.dumps(response), datetime.now(timezone.utc).isoformat()),
            )
        return response

    def acquire_lease(self, run_id: str, worker_id: str, now: float) -> str:
        row = self.conn.execute(
            "SELECT lease_token, lease_until, status FROM runtime_jobs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"Unknown run_id '{run_id}'.")
        active_token, lease_until, _ = row
        if active_token is not None and lease_until is not None and lease_until > now:
            raise RuntimeError(f"Job '{run_id}' already leased until {lease_until}.")

        token = f"lease-{worker_id}-{uuid.uuid4().hex[:8]}"
        with self.conn:
            self.conn.execute(
                "UPDATE runtime_jobs SET lease_token = ?, lease_until = ?, status = 'running' WHERE run_id = ?",
                (token, now + LEASE_SECONDS, run_id),
            )
        return token

    def sweep_expired_leases(self, now: float) -> List[Dict[str, Any]]:
        """Reclaim crashed/expired worker leases up to MAX_RETRIES."""
        swept: List[Dict[str, Any]] = []
        rows = self.conn.execute(
            "SELECT run_id, retries, lease_until FROM runtime_jobs "
            "WHERE status = 'running' AND lease_token IS NOT NULL AND lease_until <= ?",
            (now,),
        ).fetchall()
        for run_id, retries, lease_until in rows:
            next_retries = retries + 1
            new_status = "failed_exhausted" if next_retries > MAX_RETRIES else "queued"
            with self.conn:
                self.conn.execute(
                    "UPDATE runtime_jobs SET lease_token = NULL, lease_until = NULL, retries = ?, status = ? WHERE run_id = ?",
                    (next_retries, new_status, run_id),
                )
                event_out = {"event": "LEASE_EXPIRED", "retries": next_retries, "new_status": new_status}
                self.conn.execute(
                    "INSERT INTO audit_events (run_id, stage, intent, input_json, output_json, created_at) "
                    "VALUES (?, 'lease_sweep', 'reclaim_expired_lease', ?, ?, ?)",
                    (run_id, json.dumps({"expired_at": lease_until, "swept_at": now}), json.dumps(event_out), datetime.now(timezone.utc).isoformat()),
                )
            swept.append({"run_id": run_id, **event_out})
        return swept

    def get_job(self, run_id: str) -> JobState:
        row = self.conn.execute(
            "SELECT run_id, student_ref, status, current_stage_idx, retries, checkpoint_json, lease_token, lease_until "
            "FROM runtime_jobs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"Unknown run_id '{run_id}'.")
        return JobState(
            run_id=row[0],
            student_ref=row[1],
            status=row[2],
            current_stage_idx=row[3],
            retries=row[4],
            checkpoint=json.loads(row[5]),
            lease_token=row[6],
            lease_until=row[7],
        )

    def _persist_then_audit(
        self,
        run_id: str,
        next_stage_idx: int,
        new_status: str,
        checkpoint: Dict[str, Any],
        stage_name: str,
        step_input: Dict[str, Any],
        step_output: Dict[str, Any],
    ) -> None:
        """Persist durable checkpoint BEFORE writing audit event in one atomic commit."""
        with self.conn:
            self.conn.execute(
                "UPDATE runtime_jobs SET current_stage_idx = ?, status = ?, checkpoint_json = ? WHERE run_id = ?",
                (next_stage_idx, new_status, json.dumps(checkpoint, sort_keys=True), run_id),
            )
            self.conn.execute(
                "INSERT INTO audit_events (run_id, stage, intent, input_json, output_json, created_at) "
                "VALUES (?, ?, 'execute_stage', ?, ?, ?)",
                (
                    run_id,
                    stage_name,
                    json.dumps(step_input, sort_keys=True),
                    json.dumps(step_output, sort_keys=True),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def run_until_gate(
        self,
        run_id: str,
        worker_id: str,
        now: float,
        crash_on_stage: Optional[str] = None,
        mentor_approved: bool = False,
    ) -> JobState:
        """Execute remaining pipeline stages from saved checkpoint inside lease + budget."""
        lease_token = self.acquire_lease(run_id, worker_id, now=now)
        steps_used = 0

        while True:
            job = self.get_job(run_id)
            if job.current_stage_idx >= len(STAGES):
                break
            stage = STAGES[job.current_stage_idx]
            if steps_used >= self.step_budget:
                raise BudgetExceededError(f"Exceeded step_budget={self.step_budget} at stage '{stage}'.")

            if stage == "human_gate" and not mentor_approved:
                self._persist_then_audit(
                    run_id=run_id,
                    next_stage_idx=job.current_stage_idx,
                    new_status="awaiting_mentor",
                    checkpoint=job.checkpoint,
                    stage_name=stage,
                    step_input={"lease_token": lease_token, "mentor_approved": False},
                    step_output={"gate_action": "paused_for_human_approval"},
                )
                with self.conn:
                    self.conn.execute(
                        "UPDATE runtime_jobs SET lease_token = NULL, lease_until = NULL WHERE run_id = ?",
                        (run_id,),
                    )
                return self.get_job(run_id)

            if crash_on_stage == stage:
                raise SimulatedWorkerCrash(f"Worker '{worker_id}' crashed before committing '{stage}'.")

            steps_used += 1
            self.executed_stages.append(stage)
            checkpoint = dict(job.checkpoint)
            step_input = {"student_ref": job.student_ref, "prior_stages": list(checkpoint.keys())}
            if stage == "collect_sources":
                step_output = {"academic": {"attendance_pct": 65}, "lms": {"inactivity_days": 10}}
            elif stage == "score_risk":
                step_output = {"score": 100, "band": "high"}
            elif stage == "draft_packet":
                step_output = {"actions": ["faculty-check-in", "student-study-plan"]}
            elif stage == "human_gate":
                step_output = {"mentor_approved": True}
            else:
                step_output = {"published_version": 1}

            checkpoint[stage] = step_output
            next_idx = job.current_stage_idx + 1
            next_status = "completed" if next_idx >= len(STAGES) else "running"
            self._persist_then_audit(
                run_id=run_id,
                next_stage_idx=next_idx,
                new_status=next_status,
                checkpoint=checkpoint,
                stage_name=stage,
                step_input=step_input,
                step_output=step_output,
            )

        with self.conn:
            self.conn.execute(
                "UPDATE runtime_jobs SET lease_token = NULL, lease_until = NULL WHERE run_id = ?",
                (run_id,),
            )
        return self.get_job(run_id)

    def fetch_audit_log(self, run_id: str) -> List[Tuple[int, str, str, str, str]]:
        return self.conn.execute(
            "SELECT seq, stage, intent, input_json, output_json FROM audit_events WHERE run_id = ? ORDER BY seq ASC",
            (run_id,),
        ).fetchall()


def run_demo() -> None:
    print("=== Lab 06: Agent Runtime (Leases, Checkpoints, Idempotency & Append-Only Audit) ===")
    rt = AuraRuntime(step_budget=10)
    key = str(uuid.uuid4())
    receipt = rt.create_job("run-demo-01", "SYN-0002", idempotency_key=key)
    print(f"Created job: {receipt}")

    try:
        rt.run_until_gate("run-demo-01", worker_id="worker-1", now=1000.0, crash_on_stage="draft_packet")
    except SimulatedWorkerCrash as exc:
        print(f"Simulated mid-run crash: {exc}")

    swept = rt.sweep_expired_leases(now=1200.0)
    print(f"Lease sweep after 200s (>180s lease): {swept}")

    resumed = rt.run_until_gate("run-demo-01", worker_id="worker-2", now=1205.0, mentor_approved=False)
    print(f"Resumed by worker-2 -> status={resumed.status} | executed_stages={rt.executed_stages}")
    print(f"Audit log rows recorded: {len(rt.fetch_audit_log('run-demo-01'))}")


def run_self_tests() -> None:
    rt = AuraRuntime(step_budget=10)
    idem_key = str(uuid.uuid4())

    # 1. Idempotency-Key deduplicates duplicate job creation
    first = rt.create_job("run-001", "SYN-0002", idempotency_key=idem_key)
    second = rt.create_job("run-001", "SYN-0002", idempotency_key=idem_key)
    assert first["replayed_from_receipt"] is False
    assert second["replayed_from_receipt"] is True
    assert rt.conn.execute("SELECT COUNT(*) FROM runtime_jobs").fetchone()[0] == 1
    print("[PASS] Duplicate Idempotency-Key returned cached command receipt without duplicate job")

    # 2. Mid-run crash at draft_packet -> expired lease swept -> resumes from checkpoint without repeating prior stages
    try:
        rt.run_until_gate("run-001", worker_id="worker-a", now=100.0, crash_on_stage="draft_packet")
        raise AssertionError("Expected SimulatedWorkerCrash")
    except SimulatedWorkerCrash:
        pass
    assert rt.executed_stages == ["collect_sources", "score_risk"]

    swept = rt.sweep_expired_leases(now=100.0 + LEASE_SECONDS + 1.0)
    assert len(swept) == 1 and swept[0]["event"] == "LEASE_EXPIRED" and swept[0]["new_status"] == "queued"

    paused = rt.run_until_gate("run-001", worker_id="worker-b", now=300.0, mentor_approved=False)
    assert paused.status == "awaiting_mentor"
    assert rt.executed_stages == ["collect_sources", "score_risk", "draft_packet"]
    print("[PASS] Dead 180s lease reclaimed (LEASE_EXPIRED) and resumed cleanly from checkpoint")

    # 3. Completing approval gate publishes cleanly
    done = rt.run_until_gate("run-001", worker_id="worker-b", now=310.0, mentor_approved=True)
    assert done.status == "completed" and "publish_plan" in done.checkpoint
    print("[PASS] Approval gate unblocked publication and recorded structured inputs/outputs")

    # 4. SQLite triggers physically reject UPDATE and DELETE on audit_events
    for stmt in (
        "UPDATE audit_events SET stage = 'tampered' WHERE seq = 1",
        "DELETE FROM audit_events WHERE seq = 1",
    ):
        try:
            rt.conn.execute(stmt)
            raise AssertionError(f"Expected sqlite3.IntegrityError for: {stmt}")
        except sqlite3.IntegrityError:
            pass
    print("[PASS] SQLite triggers reject_audit_update/reject_audit_delete blocked tampering")


if __name__ == "__main__":
    run_demo()
    print("\n--- Running Self-Tests ---")
    run_self_tests()
    print("All Lab 06 checks passed.")
