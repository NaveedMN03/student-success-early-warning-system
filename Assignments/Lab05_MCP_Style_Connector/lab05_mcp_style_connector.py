"""Lab 05: MCP-Style Connector — Unified JSON-RPC Gateway with RBAC & Swappable Backends.

Course: Agentic AI (26ECAC401) — Chapter 11: Student Success & Early Warning System (AURA)
Phase A/B · Unified Data Access Boundary

Models AURA's single-boundary stdio JSON-RPC engine (`streamlit-worker.mts`,
`connectors.ts`, `bridge.py`):
  - Exposes all 4 college data sources (`academic`, `lms`, `internship`, `placement`)
    plus policy lookup behind one JSON-RPC 2.0 surface (`tools/list`, `tools/call`).
  - Enforces live actor RBAC (`mentor`, `hod`, `student`, `parent`) at the connector
    boundary — students and parents receive `403 FORBIDDEN` on raw sources, and
    mentors can inspect only their assigned mentees.
  - Supports hot-swapping backend adapters (JSON fixture store <-> in-memory SQLite)
    without changing a single line of calling agent code.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

ROSTER_ASSIGNMENTS: Dict[str, Dict[str, str]] = {
    "SYN-0001": {"mentor_id": "mentor-01", "department": "CSE-AI", "section": "A"},
    "SYN-0002": {"mentor_id": "mentor-01", "department": "CSE-AI", "section": "A"},
    "SYN-0003": {"mentor_id": "mentor-01", "department": "CSE-AI", "section": "A"},
    "SYN-0004": {"mentor_id": "mentor-02", "department": "CSE-AI", "section": "B"},
    "SYN-0005": {"mentor_id": "mentor-02", "department": "CSE-AI", "section": "B"},
    "SYN-0006": {"mentor_id": "mentor-02", "department": "CSE-AI", "section": "B"},
}

EMBEDDED_RECORDS: Dict[str, Dict[str, Any]] = {
    "SYN-0001": {
        "academic": {"source": "academic", "student_ref": "SYN-0001", "data_state": "present", "fields": {"attendance_pct": 72, "gpa": 7.2, "failed_courses": 0}},
        "lms": {"source": "lms", "student_ref": "SYN-0001", "data_state": "present", "fields": {"inactivity_days": 3, "overdue_assignments": 1, "missed_assessments": 0}},
        "internship": {"source": "internship", "student_ref": "SYN-0001", "data_state": "not_applicable", "fields": {"reason": "not enrolled in internship cohort"}},
        "placement": {"source": "placement", "student_ref": "SYN-0001", "data_state": "not_applicable", "fields": {"reason": "not enrolled in placement cohort"}},
    },
    "SYN-0002": {
        "academic": {"source": "academic", "student_ref": "SYN-0002", "data_state": "present", "fields": {"attendance_pct": 65, "gpa": 5.8, "failed_courses": 2}},
        "lms": {"source": "lms", "student_ref": "SYN-0002", "data_state": "present", "fields": {"inactivity_days": 10, "overdue_assignments": 3, "missed_assessments": 2}},
        "internship": {"source": "internship", "student_ref": "SYN-0002", "data_state": "present", "fields": {"missed_milestones": 1, "milestones_total": 4}},
        "placement": {"source": "placement", "student_ref": "SYN-0002", "data_state": "present", "fields": {"missed_required_activities": 2, "activities_total": 5}},
    },
    "SYN-0004": {
        "academic": {"source": "academic", "student_ref": "SYN-0004", "data_state": "present", "fields": {"attendance_pct": 81, "gpa": 7.8, "failed_courses": 0}},
        "lms": {"source": "lms", "student_ref": "SYN-0004", "data_state": "present", "fields": {"inactivity_days": 1, "overdue_assignments": 0, "missed_assessments": 0}},
        "internship": {"source": "internship", "student_ref": "SYN-0004", "data_state": "not_applicable", "fields": {"reason": "not enrolled in internship cohort"}},
        "placement": {"source": "placement", "student_ref": "SYN-0004", "data_state": "not_applicable", "fields": {"reason": "not enrolled in placement cohort"}},
    },
}


class AcademicSourceAdapter(Protocol):
    """Protocol allowing backend storage swaps without altering agent code."""

    backend_name: str

    def read_academic(self, student_ref: str) -> Dict[str, Any]:
        ...


class JsonFixtureAcademicAdapter:
    """Reads academic snapshots from Course Project synthetic fixtures or embedded copy."""

    backend_name = "json_fixtures"

    def __init__(self) -> None:
        self._records: Dict[str, Dict[str, Any]] = {
            sid: dict(sources["academic"]) for sid, sources in EMBEDDED_RECORDS.items()
        }
        here = Path(__file__).resolve()
        for parent in here.parents:
            base = parent / "Course Project" / "Source-Code" / "fixtures" / "synthetic-cohort-v1"
            if base.is_dir():
                for sid in ("SYN-0001", "SYN-0002", "SYN-0004"):
                    f = base / sid / "academic.json"
                    if f.is_file():
                        raw = json.loads(f.read_text(encoding="utf-8"))
                        self._records[sid] = {
                            "source": raw["source"],
                            "student_ref": raw["student_ref"],
                            "data_state": raw["data_state"],
                            "fields": dict(raw["fields"]),
                        }
                break

    def read_academic(self, student_ref: str) -> Dict[str, Any]:
        return dict(self._records[student_ref])


class SQLiteAcademicAdapter:
    """Drop-in in-memory SQLite adapter returning identical typed payloads."""

    backend_name = "sqlite_memory"

    def __init__(self, seed_records: Dict[str, Dict[str, Any]]) -> None:
        self._conn = sqlite3.connect(":memory:")
        self._conn.execute(
            "CREATE TABLE academic_snapshots ("
            "student_ref TEXT PRIMARY KEY, data_state TEXT NOT NULL, fields_json TEXT NOT NULL)"
        )
        for sid, rec in seed_records.items():
            self._conn.execute(
                "INSERT INTO academic_snapshots (student_ref, data_state, fields_json) VALUES (?, ?, ?)",
                (sid, rec["data_state"], json.dumps(rec["fields"], sort_keys=True)),
            )
        self._conn.commit()

    def read_academic(self, student_ref: str) -> Dict[str, Any]:
        row = self._conn.execute(
            "SELECT student_ref, data_state, fields_json FROM academic_snapshots WHERE student_ref = ?",
            (student_ref,),
        ).fetchone()
        if row is None:
            raise KeyError(f"Student '{student_ref}' not found in SQLite academic store.")
        return {
            "source": "academic",
            "student_ref": row[0],
            "data_state": row[1],
            "fields": json.loads(row[2]),
        }


class PolicyApiAdapter:
    """Mock internal Policy Service adapter."""

    def get_active_policy(self) -> Dict[str, Any]:
        return {
            "version": "CH11-DEMO-1",
            "attendanceMinimum": 75,
            "markMinimum": 60,
            "inactivityMaximum": 7,
            "freshnessDays": 30,
        }


@dataclass(frozen=True)
class ActorContext:
    actor_id: str
    role: str  # "mentor" | "hod" | "student" | "parent"
    department: str = "CSE-AI"
    linked_student_ref: Optional[str] = None


class AuraMCPConnector:
    """Single JSON-RPC 2.0 MCP-style connector enforcing uniform RBAC and schema."""

    def __init__(self, academic_adapter: AcademicSourceAdapter) -> None:
        self.academic_adapter = academic_adapter
        self.policy_api = PolicyApiAdapter()
        self._published_plans: Dict[str, Dict[str, Any]] = {
            "SYN-0001": {"status": "published", "summary": "Approved mentor support plan for SYN-0001."}
        }

    def swap_academic_adapter(self, new_adapter: AcademicSourceAdapter) -> None:
        self.academic_adapter = new_adapter

    def handle_rpc(self, request: Dict[str, Any], actor: ActorContext) -> Dict[str, Any]:
        req_id = request.get("id")
        method = request.get("method")
        params = request.get("params", {})

        if request.get("jsonrpc") != "2.0" or not isinstance(method, str):
            return self._err(req_id, -32600, 400, "INVALID_REQUEST", "Malformed JSON-RPC 2.0 envelope.")

        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "tools": [
                        {"name": "source.academic.read", "args": ["student_ref"]},
                        {"name": "source.lms.read", "args": ["student_ref"]},
                        {"name": "source.internship.read", "args": ["student_ref"]},
                        {"name": "source.placement.read", "args": ["student_ref"]},
                        {"name": "policy.get_active", "args": []},
                        {"name": "cohort.department_aggregates", "args": []},
                        {"name": "publication.get_student_plan", "args": ["student_ref"]},
                    ]
                },
            }

        if method != "tools/call":
            return self._err(req_id, -32601, 404, "METHOD_NOT_FOUND", f"Unsupported method '{method}'.")

        tool = params.get("name")
        args = params.get("arguments", {})

        if tool in {"source.academic.read", "source.lms.read", "source.internship.read", "source.placement.read"}:
            student_ref = str(args.get("student_ref", ""))
            if student_ref not in ROSTER_ASSIGNMENTS:
                return self._err(req_id, -32602, 404, "NOT_FOUND", f"Unknown student '{student_ref}'.")
            if actor.role in {"student", "parent", "hod"}:
                return self._err(
                    req_id,
                    -32003,
                    403,
                    "FORBIDDEN",
                    f"Role '{actor.role}' is forbidden from raw student source records (HTTP 403).",
                )
            if actor.role == "mentor" and ROSTER_ASSIGNMENTS[student_ref]["mentor_id"] != actor.actor_id:
                return self._err(
                    req_id,
                    -32003,
                    403,
                    "FORBIDDEN",
                    f"Mentor '{actor.actor_id}' is not assigned to '{student_ref}' (HTTP 403).",
                )

            if tool == "source.academic.read":
                payload = self.academic_adapter.read_academic(student_ref)
            else:
                src_key = tool.split(".")[1]
                payload = dict(EMBEDDED_RECORDS[student_ref][src_key])
            return {"jsonrpc": "2.0", "id": req_id, "result": {"backend": self.academic_adapter.backend_name, "data": payload}}

        if tool == "policy.get_active":
            return {"jsonrpc": "2.0", "id": req_id, "result": self.policy_api.get_active_policy()}

        if tool == "cohort.department_aggregates":
            if actor.role not in {"hod", "mentor"}:
                return self._err(req_id, -32003, 403, "FORBIDDEN", "Only faculty roles may read aggregates.")
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"department": actor.department, "total_students": len(ROSTER_ASSIGNMENTS), "flagged_estimate": 2},
            }

        if tool == "publication.get_student_plan":
            student_ref = str(args.get("student_ref", ""))
            if actor.role in {"student", "parent"} and actor.linked_student_ref != student_ref:
                return self._err(req_id, -32003, 403, "FORBIDDEN", "Cross-family publication access denied.")
            plan = self._published_plans.get(student_ref)
            if not plan:
                return self._err(req_id, -32004, 404, "NOT_PUBLISHED", "No approved publication exists for this student.")
            return {"jsonrpc": "2.0", "id": req_id, "result": plan}

        return self._err(req_id, -32601, 404, "UNKNOWN_TOOL", f"Unknown connector tool '{tool}'.")

    @staticmethod
    def _err(req_id: Any, code: int, http_status: int, reason: str, message: str) -> Dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": code, "http_status": http_status, "reason": reason, "message": message},
        }


class ConnectorAgentClient:
    """Agent client that speaks only JSON-RPC to AuraMCPConnector (zero direct source imports)."""

    def __init__(self, connector: AuraMCPConnector, actor: ActorContext) -> None:
        self.connector = connector
        self.actor = actor
        self._seq = 0

    def fetch_student_bundle(self, student_ref: str) -> Dict[str, Any]:
        bundle: Dict[str, Any] = {}
        for source in ("academic", "lms", "internship", "placement"):
            self._seq += 1
            resp = self.connector.handle_rpc(
                {
                    "jsonrpc": "2.0",
                    "id": self._seq,
                    "method": "tools/call",
                    "params": {"name": f"source.{source}.read", "arguments": {"student_ref": student_ref}},
                },
                self.actor,
            )
            if "error" in resp:
                raise PermissionError(f"Connector denied {source}: {resp['error']}")
            bundle[source] = resp["result"]["data"]
        return bundle


def run_demo() -> None:
    print("=== Lab 05: MCP-Style Connector (Unified JSON-RPC Boundary + RBAC) ===")
    json_adapter = JsonFixtureAcademicAdapter()
    connector = AuraMCPConnector(academic_adapter=json_adapter)

    mentor_1 = ActorContext(actor_id="mentor-01", role="mentor")
    client = ConnectorAgentClient(connector, mentor_1)

    bundle_json = client.fetch_student_bundle("SYN-0001")
    print(f"Mentor-01 fetched SYN-0001 via backend='{connector.academic_adapter.backend_name}': {bundle_json['academic']}")

    sqlite_adapter = SQLiteAcademicAdapter({sid: vals["academic"] for sid, vals in EMBEDDED_RECORDS.items()})
    connector.swap_academic_adapter(sqlite_adapter)
    bundle_sqlite = client.fetch_student_bundle("SYN-0001")
    print(f"Swapped backend='{connector.academic_adapter.backend_name}' (same agent code!): {bundle_sqlite['academic']}")

    student_actor = ActorContext(actor_id="student-01", role="student", linked_student_ref="SYN-0001")
    denied = connector.handle_rpc(
        {"jsonrpc": "2.0", "id": 99, "method": "tools/call", "params": {"name": "source.academic.read", "arguments": {"student_ref": "SYN-0001"}}},
        student_actor,
    )
    print(f"Student raw source check -> http_status={denied['error']['http_status']} reason={denied['error']['reason']}")


def run_self_tests() -> None:
    json_adapter = JsonFixtureAcademicAdapter()
    connector = AuraMCPConnector(academic_adapter=json_adapter)
    mentor_1 = ActorContext(actor_id="mentor-01", role="mentor")
    client = ConnectorAgentClient(connector, mentor_1)

    # 1. Mentor-01 reads assigned mentee SYN-0001
    from_json = client.fetch_student_bundle("SYN-0001")
    assert from_json["academic"]["fields"]["attendance_pct"] == 72
    assert from_json["lms"]["fields"]["overdue_assignments"] == 1
    print("[PASS] Assigned mentor read all 4 source snapshots through JSON-RPC connector")

    # 2. Mentor-01 denied unassigned student SYN-0004 (HTTP 403)
    unassigned = connector.handle_rpc(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "source.academic.read", "arguments": {"student_ref": "SYN-0004"}}},
        mentor_1,
    )
    assert unassigned["error"]["http_status"] == 403 and unassigned["error"]["reason"] == "FORBIDDEN"
    print("[PASS] Unassigned mentee read blocked with HTTP 403 FORBIDDEN")

    # 3. Student, Parent, and HoD denied raw student sources (HTTP 403); HoD allowed aggregates
    for role in ("student", "parent", "hod"):
        actor = ActorContext(actor_id=f"{role}-01", role=role, linked_student_ref="SYN-0001")
        res = connector.handle_rpc(
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "source.academic.read", "arguments": {"student_ref": "SYN-0001"}}},
            actor,
        )
        assert res["error"]["http_status"] == 403
    hod_agg = connector.handle_rpc(
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "cohort.department_aggregates", "arguments": {}}},
        ActorContext(actor_id="hod-01", role="hod"),
    )
    assert hod_agg["result"]["department"] == "CSE-AI"
    print("[PASS] Student/Parent/HoD raw source access denied (403); HoD aggregates permitted")

    # 4. Swapping adapter from JSON fixtures to SQLite yields identical payload with zero agent changes
    connector.swap_academic_adapter(SQLiteAcademicAdapter({sid: vals["academic"] for sid, vals in EMBEDDED_RECORDS.items()}))
    from_sqlite = client.fetch_student_bundle("SYN-0001")
    assert from_sqlite == from_json
    print("[PASS] Swapping JsonFixtureAcademicAdapter -> SQLiteAcademicAdapter returned identical payload")


if __name__ == "__main__":
    run_demo()
    print("\n--- Running Self-Tests ---")
    run_self_tests()
    print("All Lab 05 checks passed.")
