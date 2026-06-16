"""
The Grid — Supabase database layer
Replaces SQLite/WAL with PostgreSQL via Supabase.
Auth: Supabase JWT replaces DSID/AppleConnect header injection.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from supabase import create_client, Client

STANDING_REVIEW_DAYS = 90

_supabase: Optional[Client] = None

def get_supabase() -> Client:
    global _supabase
    if _supabase is None:
        url = os.environ["SUPABASE_URL"]
        key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
        _supabase = create_client(url, key)
    return _supabase


# ── Standing helpers ──────────────────────────────────────────────────────────

def _compute_effective_standing(standing: str, reviewed_at: Optional[str]) -> tuple[bool, str]:
    """Returns (overdue, effective_standing)."""
    overdue = False
    if reviewed_at:
        try:
            rev_dt = datetime.fromisoformat(reviewed_at)
            if rev_dt.tzinfo is None:
                rev_dt = rev_dt.replace(tzinfo=timezone.utc)
            overdue = datetime.now(timezone.utc) - rev_dt >= timedelta(days=STANDING_REVIEW_DAYS)
        except Exception:
            pass
    effective = "red" if (standing == "red" or overdue) else "green"
    return overdue, effective


def _shape_employee(row: dict) -> dict:
    overdue, effective = _compute_effective_standing(
        row.get("standing", "green"),
        row.get("standing_reviewed_at")
    )
    return {
        "id":                   row["id"],
        "name":                 row["name"],
        "office":               row.get("office", ""),
        "email":                row.get("email", ""),
        "manager":              row.get("manager", ""),
        "locations":            row.get("locations") or {},
        "workSkills":           row.get("work_skills") or [],
        "nonWorkSkills":        row.get("non_work") or [],
        "hobbies":              row.get("hobbies") or [],
        "note":                 row.get("note", ""),
        "eligible":             bool(row.get("eligible", True)),
        "standing":             effective,
        "standing_manual":      row.get("standing", "green"),
        "standing_overdue":     overdue,
        "standing_reviewed_at": row.get("standing_reviewed_at"),
        "standing_note":        row.get("standing_note", ""),
        "private_fields":       row.get("private_fields") or [],
        "languages":            row.get("languages") or [],
        "current_goal":         row.get("current_goal", ""),
        "demo":                 bool(row.get("demo", False)),
    }


# ── Employees ─────────────────────────────────────────────────────────────────

def get_all_employees(org_id: str) -> list[dict]:
    sb = get_supabase()
    res = sb.table("employees").select("*").eq("org_id", org_id).order("name").execute()
    return [_shape_employee(r) for r in res.data]


def get_employee(employee_id: str, org_id: str) -> Optional[dict]:
    sb = get_supabase()
    res = sb.table("employees").select("*").eq("id", employee_id).eq("org_id", org_id).execute()
    return _shape_employee(res.data[0]) if res.data else None


def get_employee_by_user_id(user_id: str, org_id: str) -> Optional[dict]:
    sb = get_supabase()
    res = sb.table("employees").select("*").eq("user_id", user_id).eq("org_id", org_id).execute()
    return _shape_employee(res.data[0]) if res.data else None


def create_employee(org_id: str, data: dict) -> dict:
    sb = get_supabase()
    now = datetime.now(timezone.utc).isoformat()
    row = {
        "org_id":               org_id,
        "name":                 data["name"],
        "email":                data.get("email", ""),
        "office":               data.get("office", ""),
        "manager":              data.get("manager", ""),
        "user_id":              data.get("user_id"),
        "locations":            data.get("locations", {}),
        "work_skills":          data.get("workSkills", []),
        "non_work":             data.get("nonWorkSkills", []),
        "hobbies":              data.get("hobbies", []),
        "note":                 "",
        "eligible":             True,
        "standing":             "green",
        "standing_reviewed_at": now,
        "standing_note":        "",
        "private_fields":       [],
        "languages":            data.get("languages", []),
        "current_goal":         data.get("current_goal", ""),
        "demo":                 data.get("demo", False),
    }
    res = sb.table("employees").insert(row).execute()
    return _shape_employee(res.data[0])


def update_employee(employee_id: str, org_id: str, updates: dict) -> Optional[dict]:
    sb = get_supabase()
    db_updates = {}
    field_map = {
        "workSkills":    "work_skills",
        "nonWorkSkills": "non_work",
    }
    for k, v in updates.items():
        db_updates[field_map.get(k, k)] = v
    res = sb.table("employees").update(db_updates).eq("id", employee_id).eq("org_id", org_id).execute()
    return _shape_employee(res.data[0]) if res.data else None


def set_standing(employee_id: str, org_id: str, standing: str, note: str) -> Optional[dict]:
    sb = get_supabase()
    res = sb.table("employees").update({
        "standing": standing,
        "standing_note": note,
    }).eq("id", employee_id).eq("org_id", org_id).execute()
    return _shape_employee(res.data[0]) if res.data else None


def confirm_standing(employee_id: str, org_id: str) -> Optional[dict]:
    sb = get_supabase()
    now = datetime.now(timezone.utc).isoformat()
    res = sb.table("employees").update({
        "standing": "green",
        "standing_note": "",
        "standing_reviewed_at": now,
    }).eq("id", employee_id).eq("org_id", org_id).execute()
    return _shape_employee(res.data[0]) if res.data else None


def set_eligible(employee_id: str, org_id: str, eligible: bool) -> Optional[dict]:
    sb = get_supabase()
    res = sb.table("employees").update({"eligible": eligible}).eq("id", employee_id).eq("org_id", org_id).execute()
    return _shape_employee(res.data[0]) if res.data else None


def delete_employee(employee_id: str, org_id: str) -> bool:
    sb = get_supabase()
    res = sb.table("employees").delete().eq("id", employee_id).eq("org_id", org_id).execute()
    return len(res.data) > 0


# ── Projects ──────────────────────────────────────────────────────────────────

def get_all_projects(org_id: str) -> list[dict]:
    sb = get_supabase()
    res = sb.table("projects").select("*").eq("org_id", org_id).execute()
    return [r["data"] | {"id": r["id"]} for r in res.data]


def get_project(project_id: str, org_id: str) -> Optional[dict]:
    sb = get_supabase()
    res = sb.table("projects").select("*").eq("id", project_id).eq("org_id", org_id).execute()
    if not res.data:
        return None
    return res.data[0]["data"] | {"id": res.data[0]["id"]}


def upsert_project(project: dict, org_id: str) -> dict:
    sb = get_supabase()
    pid = project.get("id")
    row = {"org_id": org_id, "data": project}
    if pid:
        row["id"] = pid
        res = sb.table("projects").upsert(row).execute()
    else:
        res = sb.table("projects").insert(row).execute()
    return res.data[0]["data"] | {"id": res.data[0]["id"]}


def delete_project(project_id: str, org_id: str) -> bool:
    sb = get_supabase()
    res = sb.table("projects").delete().eq("id", project_id).eq("org_id", org_id).execute()
    return len(res.data) > 0


# ── Orgs ──────────────────────────────────────────────────────────────────────

def get_or_create_org(user_id: str, user_email: str) -> dict:
    """Get the org for this user, or create one if first sign-in."""
    sb = get_supabase()
    res = sb.table("orgs").select("*").eq("owner_id", user_id).execute()
    if res.data:
        return res.data[0]
    # Create new org
    org_row = {
        "owner_id": user_id,
        "owner_email": user_email,
        "name": f"{user_email.split('@')[0]}'s Team",
        "demo": False,
    }
    res = sb.table("orgs").insert(org_row).execute()
    return res.data[0]


DEMO_ORG_ID = "demo"  # Special sentinel — reads from demo_employees / demo_projects tables

def get_demo_employees() -> list[dict]:
    sb = get_supabase()
    res = sb.table("demo_employees").select("*").order("name").execute()
    return [_shape_employee(r) for r in res.data]

def get_demo_projects() -> list[dict]:
    sb = get_supabase()
    res = sb.table("demo_projects").select("*").execute()
    return [r["data"] | {"id": r["id"]} for r in res.data]
