"""
The Grid — FastAPI Backend v1.0.0
Team intelligence platform: employees, projects, standing review system, RBAC.
Auth: Supabase JWT (Google OAuth) replaces DSID/AppleConnect.
Org-scoped: every resource belongs to an org, owned by the authenticated user.
Demo mode: unauthenticated reads from read-only demo data.
"""

from __future__ import annotations

import csv
import io
import json
import os
import time
import logging
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from api.db import (
    get_supabase,
    get_or_create_org,
    get_all_employees, get_employee, get_employee_by_user_id,
    create_employee, update_employee, set_standing, confirm_standing,
    set_eligible, delete_employee,
    get_all_projects, get_project, upsert_project, delete_project,
    get_demo_employees, get_demo_projects,
    DEMO_ORG_ID,
)


# ── Structured JSON logger ────────────────────────────────────────────────────

class _JSONFormatter(logging.Formatter):
    def format(self, record):
        log = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%SZ"),
            "level":     record.levelname,
            "message":   record.getMessage(),
        }
        if hasattr(record, "extra"):
            log.update(record.extra)
        if record.exc_info:
            log["traceback"] = self.formatException(record.exc_info)
        return json.dumps(log)

_handler = logging.StreamHandler()
_handler.setFormatter(_JSONFormatter())
logger = logging.getLogger("the-grid")
logger.setLevel(logging.INFO)
logger.addHandler(_handler)
logger.propagate = False


# ── In-memory metrics ─────────────────────────────────────────────────────────

class _Metrics:
    def __init__(self):
        self.request_count    = defaultdict(int)
        self.error_count      = defaultdict(int)
        self.forbidden_count  = defaultdict(int)
        self.duration_totals  = defaultdict(float)
        self.duration_counts  = defaultdict(int)
        self.standing_confirms = 0
        self.started_at       = time.time()

    def record(self, route: str, duration_ms: float, status: int):
        self.request_count[route]   += 1
        self.duration_totals[route] += duration_ms
        self.duration_counts[route] += 1
        if status >= 500:
            self.error_count[route] += 1
        if status == 403:
            self.forbidden_count[route] += 1

    def summary(self):
        routes = {}
        for route in self.request_count:
            n = self.duration_counts[route]
            routes[route] = {
                "requests": self.request_count[route],
                "errors":   self.error_count[route],
                "avg_ms":   round(self.duration_totals[route] / n, 2) if n else 0,
            }
        return {
            "uptime_seconds":    round(time.time() - self.started_at, 1),
            "standing_confirms": self.standing_confirms,
            "routes":            routes,
            "auth": {
                "total_403s": sum(self.forbidden_count.values()),
                "by_route":   dict(self.forbidden_count),
            },
        }

metrics = _Metrics()


# ── Auth helpers ──────────────────────────────────────────────────────────────

def _get_user(request: Request) -> Optional[dict]:
    """
    Verify Supabase JWT from Authorization header.
    Returns user dict {id, email} or None.
    Dev: set DEV_USER_ID + DEV_USER_EMAIL env vars.
    """
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth.split(" ", 1)[1]
    try:
        sb = get_supabase()
        user = sb.auth.get_user(token)
        if user and user.user:
            return {"id": user.user.id, "email": user.user.email or ""}
    except Exception:
        pass
    return None


def _require_user(request: Request) -> dict:
    user = _get_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def _get_org(user: dict) -> dict:
    return get_or_create_org(user["id"], user["email"])


def _require_admin(request: Request) -> tuple[dict, dict]:
    """Returns (user, org). Raises 403 if user is not org owner (admin)."""
    user = _require_user(request)
    org  = _get_org(user)
    if org["owner_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Admin only")
    return user, org


def _is_project_lead(user: dict, org_id: str, project: dict) -> bool:
    emp = get_employee_by_user_id(user["id"], org_id)
    return emp is not None and emp["id"] == project.get("contact")


# ── App ───────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield

app = FastAPI(title="The Grid API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def observability(request: Request, call_next):
    start  = time.perf_counter()
    route  = request.url.path
    method = request.method
    status = 500
    try:
        response = await call_next(request)
        status   = response.status_code
        return response
    except Exception as exc:
        logger.error(f"Unhandled exception on {method} {route}", exc_info=exc)
        return JSONResponse(status_code=500, content={"error": "internal server error"})
    finally:
        ms = round((time.perf_counter() - start) * 1000, 2)
        metrics.record(route, ms, status)
        level = logging.ERROR if status >= 500 else logging.WARNING if status == 403 else logging.INFO
        logger.log(level, f"{method} {route} {status} {ms}ms", extra={"extra": {
            "route": route, "method": method, "status": status, "duration_ms": ms,
        }})


# ── Pydantic models ───────────────────────────────────────────────────────────

class EmployeeCreate(BaseModel):
    name: str
    email: str = ""
    office: str = ""
    manager: str = ""
    workSkills: list[str] = []
    nonWorkSkills: list[str] = []
    hobbies: list[str] = []
    languages: list[dict] = []
    current_goal: str = ""

class EmployeeUpdate(BaseModel):
    name: str | None = None
    email: str | None = None
    office: str | None = None
    manager: str | None = None
    locations: dict | None = None
    workSkills: list[str] | None = None
    nonWorkSkills: list[str] | None = None
    hobbies: list[str] | None = None
    note: str | None = None
    private_fields: list[str] | None = None
    languages: list[dict] | None = None
    current_goal: str | None = None

class EligibleUpdate(BaseModel):
    eligible: bool

class StandingUpdate(BaseModel):
    standing: str
    note: str = ""

class ProjectCreate(BaseModel):
    name: str
    status: str = "planning"
    contact: str = ""
    objective: str = ""
    tasks: list[str] = []
    endDate: str | None = None
    tools: list[str] = []
    link: str | None = None
    team: list[str] = []
    roles: dict = {}

class ProjectUpdate(BaseModel):
    name: str | None = None
    status: str | None = None
    contact: str | None = None
    objective: str | None = None
    tasks: list[str] | None = None
    endDate: str | None = None
    tools: list[str] | None = None
    link: str | None = None
    team: list[str] | None = None
    roles: dict | None = None

class TeamAction(BaseModel):
    employee_id: str
    action: str  # "add" | "remove"


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"status": "ok", "service": "the-grid", "version": "1.0.0"}

@app.get("/api/metrics")
def api_metrics():
    return metrics.summary()


# ── Demo (no auth required) ───────────────────────────────────────────────────

@app.get("/api/demo/employees")
def demo_employees():
    """Read-only demo team — no auth required."""
    emps = get_demo_employees()
    # Scrub standing_note from demo data
    for e in emps:
        e.pop("standing_note", None)
    return emps

@app.get("/api/demo/projects")
def demo_projects():
    """Read-only demo projects — no auth required."""
    return get_demo_projects()


# ── Auth / identity ───────────────────────────────────────────────────────────

@app.get("/api/me")
def me(request: Request):
    user = _require_user(request)
    org  = _get_org(user)
    is_admin = org["owner_id"] == user["id"]
    my_emp = get_employee_by_user_id(user["id"], org["id"])

    review_needed = []
    if is_admin and my_emp:
        all_emps = get_all_employees(org["id"])
        review_needed = [
            {"id": e["id"], "name": e["name"], "standing": e["standing"],
             "standing_overdue": e.get("standing_overdue", False)}
            for e in all_emps
            if e.get("manager") == my_emp["name"]
            and (e["standing"] == "red" or e.get("standing_overdue"))
        ]

    return {
        "user_id":       user["id"],
        "email":         user["email"],
        "is_admin":      is_admin,
        "org_id":        org["id"],
        "org_name":      org["name"],
        "employee_id":   my_emp["id"] if my_emp else None,
        "review_needed": review_needed,
    }

@app.get("/api/whoami")
def whoami(request: Request):
    user = _require_user(request)
    org  = _get_org(user)
    emp  = get_employee_by_user_id(user["id"], org["id"])
    if not emp:
        raise HTTPException(status_code=404, detail="No matching employee record")
    return emp


# ── Employees ─────────────────────────────────────────────────────────────────

@app.get("/api/employees")
def api_list_employees(request: Request):
    user    = _require_user(request)
    org     = _get_org(user)
    is_admin = org["owner_id"] == user["id"]
    my_emp  = get_employee_by_user_id(user["id"], org["id"])
    my_id   = my_emp["id"] if my_emp else None
    emps    = get_all_employees(org["id"])

    if not is_admin:
        for e in emps:
            if e["id"] != my_id:
                for field in e.get("private_fields", []):
                    if field in e.get("locations", {}):
                        e["locations"][field] = None
                    elif field in e:
                        e[field] = None
            e.pop("standing_note", None)
    return emps

@app.post("/api/employees", status_code=201)
def api_create_employee(body: EmployeeCreate, request: Request):
    _, org = _require_admin(request)
    return create_employee(org["id"], body.model_dump())

@app.get("/api/employees/{employee_id}")
def api_get_employee(employee_id: str, request: Request):
    user = _require_user(request)
    org  = _get_org(user)
    emp  = get_employee(employee_id, org["id"])
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    return emp

@app.patch("/api/employees/{employee_id}")
def api_update_employee(employee_id: str, body: EmployeeUpdate, request: Request):
    _, org = _require_admin(request)
    emp = update_employee(employee_id, org["id"], body.model_dump(exclude_none=True))
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    return emp

@app.patch("/api/employees/me/profile")
def api_update_my_profile(body: EmployeeUpdate, request: Request):
    user = _require_user(request)
    org  = _get_org(user)
    me_emp = get_employee_by_user_id(user["id"], org["id"])
    if not me_emp:
        raise HTTPException(status_code=404, detail="No employee record found")
    emp = update_employee(me_emp["id"], org["id"], body.model_dump(exclude_none=True))
    return emp

@app.patch("/api/employees/{employee_id}/eligible")
def api_set_eligible(employee_id: str, body: EligibleUpdate, request: Request):
    _, org = _require_admin(request)
    emp = set_eligible(employee_id, org["id"], body.eligible)
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    return emp

@app.patch("/api/employees/{employee_id}/standing")
def api_set_standing(employee_id: str, body: StandingUpdate, request: Request):
    _, org = _require_admin(request)
    if body.standing == "red" and not body.note.strip():
        raise HTTPException(status_code=400, detail="A note is required when setting standing to red")
    emp = set_standing(employee_id, org["id"], body.standing, body.note)
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    return emp

@app.post("/api/employees/{employee_id}/standing/confirm")
def api_confirm_standing(employee_id: str, request: Request):
    _, org = _require_admin(request)
    emp = confirm_standing(employee_id, org["id"])
    if emp:
        metrics.standing_confirms += 1
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    return emp

@app.delete("/api/employees/{employee_id}", status_code=204)
def api_delete_employee(employee_id: str, request: Request):
    _, org = _require_admin(request)
    if not delete_employee(employee_id, org["id"]):
        raise HTTPException(status_code=404, detail="Employee not found")


# ── Projects ──────────────────────────────────────────────────────────────────

@app.get("/api/projects")
def api_list_projects(request: Request):
    user = _require_user(request)
    org  = _get_org(user)
    return get_all_projects(org["id"])

@app.get("/api/projects/{project_id}")
def api_get_project(project_id: str, request: Request):
    user = _require_user(request)
    org  = _get_org(user)
    proj = get_project(project_id, org["id"])
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    return proj

@app.post("/api/projects", status_code=201)
def api_create_project(body: ProjectCreate, request: Request):
    user, org = _require_admin(request)
    return upsert_project(body.model_dump(), org["id"])

@app.patch("/api/projects/{project_id}")
def api_update_project(project_id: str, body: ProjectUpdate, request: Request):
    user = _require_user(request)
    org  = _get_org(user)
    proj = get_project(project_id, org["id"])
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    is_admin = org["owner_id"] == user["id"]
    if not is_admin and not _is_project_lead(user, org["id"], proj):
        raise HTTPException(status_code=403, detail="Admin or project lead only")
    proj.update(body.model_dump(exclude_none=True))
    return upsert_project(proj, org["id"])

@app.post("/api/projects/{project_id}/team")
def api_update_team(project_id: str, body: TeamAction, request: Request):
    user = _require_user(request)
    org  = _get_org(user)
    proj = get_project(project_id, org["id"])
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    is_admin = org["owner_id"] == user["id"]
    if not is_admin and not _is_project_lead(user, org["id"], proj):
        raise HTTPException(status_code=403, detail="Admin or project lead only")
    team: list = proj.get("team", [])
    if body.action == "add":
        if body.employee_id not in team:
            team.append(body.employee_id)
    elif body.action == "remove":
        team = [m for m in team if m != body.employee_id]
    else:
        raise HTTPException(status_code=400, detail="action must be 'add' or 'remove'")
    proj["team"] = team
    return upsert_project(proj, org["id"])

@app.delete("/api/projects/{project_id}", status_code=204)
def api_delete_project(project_id: str, request: Request):
    _, org = _require_admin(request)
    if not delete_project(project_id, org["id"]):
        raise HTTPException(status_code=404, detail="Project not found")


# ── Audit ─────────────────────────────────────────────────────────────────────

@app.get("/api/audit")
def api_audit(request: Request):
    _, org = _require_admin(request)
    employees = get_all_employees(org["id"])
    projects  = get_all_projects(org["id"])

    proj_map: dict[str, list[str]] = {}
    for p in projects:
        if p.get("status") not in ("complete", "cancelled"):
            for tid in p.get("team", []):
                proj_map.setdefault(tid, []).append(p["name"])

    return [{
        "id":                   e["id"],
        "name":                 e["name"],
        "office":               e["office"],
        "manager":              e.get("manager", ""),
        "email":                e["email"],
        "eligible":             e["eligible"],
        "standing":             e["standing"],
        "standing_overdue":     e.get("standing_overdue", False),
        "standing_reviewed_at": e.get("standing_reviewed_at"),
        "standing_note":        e.get("standing_note", ""),
        "active_projects":      proj_map.get(e["id"], []),
        "project_count":        len(proj_map.get(e["id"], [])),
    } for e in employees]

@app.get("/api/audit/csv")
def api_audit_csv(request: Request):
    _, org = _require_admin(request)
    data   = api_audit(request)
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=[
        "name","office","manager","email","eligible",
        "standing","standing_overdue","standing_reviewed_at",
        "standing_note","active_projects","project_count"
    ])
    writer.writeheader()
    for row in data:
        row["active_projects"] = "; ".join(row["active_projects"])
        writer.writerow({k: row.get(k, "") for k in writer.fieldnames})
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit.csv"}
    )


# ── Static — mounted last ─────────────────────────────────────────────────────

from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
app.mount("/", StaticFiles(directory=str(BASE_DIR / "public"), html=True), name="static")
