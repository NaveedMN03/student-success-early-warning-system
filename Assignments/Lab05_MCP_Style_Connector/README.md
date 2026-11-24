# Lab 05 — MCP-Style Connector (Unified JSON-RPC Boundary & RBAC)

- **Course:** Agentic AI (`26ECAC401`) — Chapter 11: Student Success & Early Warning System (AURA)
- **Phase:** A/B · Unified Connector Layer
- **AURA Engine Mapping:** `Course Project/Source-Code/platform/scripts/streamlit-worker.mts`, `connectors.ts`, and `streamlit_app/bridge.py`

## What This Lab Demonstrates
- Exposes heterogeneous data sources (`academic`, `lms`, `internship`, `placement`, and `policy`) through one JSON-RPC 2.0 `AuraMCPConnector` (`tools/list`, `tools/call`).
- Enforces strict actor RBAC at the protocol boundary: assigned mentors only, HoD aggregates only, and `403 FORBIDDEN` for Student/Parent access to raw source records.
- Swaps `JsonFixtureAcademicAdapter` for `SQLiteAcademicAdapter` (`:memory:`) with zero changes to `ConnectorAgentClient`.

## Run
```bash
python3 Assignments/Lab05_MCP_Style_Connector/lab05_mcp_style_connector.py
```
