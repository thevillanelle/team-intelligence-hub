# The Grid

Team intelligence platform — employee directory, project tracker, skills search, and a 90-day standing review system. Built for distributed teams.

## Live Demo

→ **[the-grid.vercel.app](https://the-grid.vercel.app)** — Demo mode, no login required. 95 employees, 10 projects, full standing system.

Sign in with Google to run it for your own team.

## What It Does

- **People directory** — skills, hobbies, availability, manager relationships
- **Project tracker** — status, team assignments, volunteer slots, links
- **Skills search** — find people by skill or interest across your org
- **Standing review system** — 90-day forcing function: every team member's standing automatically goes red if their lead hasn't confirmed them recently. Red requires a written note. Confirmations are auditable.
- **Privacy filtering** — employees can mark fields private; non-admins see scrubbed versions of others' cards
- **RBAC** — org owner is admin, project contacts are leads, everyone else is read-only on others
- **Audit CSV** — one-click export: all employees with standing, review timestamp, notes, and active project assignments

## Stack

| Layer | Tech |
|---|---|
| Backend | Python 3.12 · FastAPI · Uvicorn |
| Database | Supabase (PostgreSQL) |
| Auth | Supabase Auth (GitHub OAuth) |
| Hosting | Vercel |
| Observability | Structured JSON logging · `/api/metrics` endpoint |

## Demo vs. Authenticated

| | Demo | Authenticated |
|---|---|---|
| View employees | ✅ (read-only) | ✅ |
| View projects | ✅ (read-only) | ✅ |
| Edit your profile | ❌ | ✅ |
| Manage your team | ❌ | ✅ (org owner) |
| Standing reviews | ❌ | ✅ (org owner) |
| Audit CSV export | ❌ | ✅ (org owner) |

## API

```
GET  /api/health                          — Public
GET  /api/metrics                         — Authenticated
GET  /api/me                              — Authenticated
GET  /api/whoami                          — Authenticated
GET  /api/demo/employees                  — Public (demo data)
GET  /api/demo/projects                   — Public (demo data)
GET  /api/employees                       — Authenticated
POST /api/employees                       — Admin
GET  /api/employees/{id}                  — Authenticated
PATCH /api/employees/{id}                 — Admin
PATCH /api/employees/me/profile           — Self
PATCH /api/employees/{id}/eligible        — Admin
PATCH /api/employees/{id}/standing        — Admin (red requires note)
POST  /api/employees/{id}/standing/confirm — Admin
DELETE /api/employees/{id}                — Admin
GET  /api/projects                        — Authenticated
POST /api/projects                        — Admin
GET  /api/projects/{id}                   — Authenticated
PATCH /api/projects/{id}                  — Admin or project lead
POST  /api/projects/{id}/team             — Admin or project lead
DELETE /api/projects/{id}                 — Admin
GET  /api/audit                           — Admin
GET  /api/audit/csv                       — Admin
```

## Setup

### 1. Supabase

1. Create a new Supabase project
2. Run `supabase_schema.sql` in the SQL editor
3. Run `demo_seed.sql` to populate demo data
4. Enable GitHub OAuth in Auth → Providers → GitHub
5. Copy your project URL and service role key

### 2. Local Development

```bash
git clone https://github.com/thevillanelle/the-grid.git
cd the-grid
pip install -r requirements.txt
cp .env.example .env
# Fill in SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, DEV_USER_ID, DEV_USER_EMAIL
uvicorn api.main:app --reload --port 8080
```

### 3. Vercel

```bash
vercel
# Set environment variables:
# SUPABASE_URL → your project URL
# SUPABASE_SERVICE_ROLE_KEY → your service role key
```

## The Standing System

The 90-day review cycle is the most operationally significant feature.

Every employee has a `standing` field: `green` or `red`. `standing_reviewed_at` tracks when a lead last confirmed them. After 90 days without confirmation, effective standing becomes red — the system treats it as red even if the DB value is green.

Setting standing to red requires a written note. `POST /api/employees/{id}/standing/confirm` resets to green and updates the timestamp. The `/api/metrics` endpoint tracks `standing_confirms` as a behavioral metric — how often leads are actually doing reviews.

---

*Built by [@thevillanelle](https://github.com/thevillanelle)*
