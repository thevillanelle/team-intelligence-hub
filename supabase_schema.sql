-- The Grid — Supabase Schema
-- Run in: Supabase Dashboard → SQL Editor → New Query

-- ── Orgs ──────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS orgs (
  id          UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  owner_id    UUID NOT NULL,
  owner_email TEXT NOT NULL,
  name        TEXT NOT NULL DEFAULT 'My Team',
  demo        BOOLEAN DEFAULT false,
  created_at  TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_orgs_owner ON orgs(owner_id);

-- ── Employees ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS employees (
  id                   UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  org_id               UUID NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  user_id              UUID,           -- links to auth.users when employee signs in
  name                 TEXT NOT NULL,
  email                TEXT DEFAULT '',
  office               TEXT DEFAULT '',
  manager              TEXT DEFAULT '',
  locations            JSONB DEFAULT '{}',
  work_skills          JSONB DEFAULT '[]',
  non_work             JSONB DEFAULT '[]',
  hobbies              JSONB DEFAULT '[]',
  note                 TEXT DEFAULT '',
  eligible             BOOLEAN DEFAULT true,
  standing             TEXT DEFAULT 'green',
  standing_note        TEXT DEFAULT '',
  standing_reviewed_at TIMESTAMPTZ DEFAULT now(),
  private_fields       JSONB DEFAULT '[]',
  languages            JSONB DEFAULT '[]',
  current_goal         TEXT DEFAULT '',
  demo                 BOOLEAN DEFAULT false,
  created_at           TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_employees_org    ON employees(org_id);
CREATE INDEX IF NOT EXISTS idx_employees_user   ON employees(user_id);
CREATE INDEX IF NOT EXISTS idx_employees_name   ON employees(name);

-- ── Projects ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS projects (
  id         UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  org_id     UUID NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  data       JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_projects_org ON projects(org_id);

-- ── Demo tables (read-only, shared across all unauthenticated visitors) ───────
CREATE TABLE IF NOT EXISTS demo_employees (
  id                   UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  name                 TEXT NOT NULL,
  email                TEXT DEFAULT '',
  office               TEXT DEFAULT '',
  manager              TEXT DEFAULT '',
  locations            JSONB DEFAULT '{}',
  work_skills          JSONB DEFAULT '[]',
  non_work             JSONB DEFAULT '[]',
  hobbies              JSONB DEFAULT '[]',
  note                 TEXT DEFAULT '',
  eligible             BOOLEAN DEFAULT true,
  standing             TEXT DEFAULT 'green',
  standing_note        TEXT DEFAULT '',
  standing_reviewed_at TIMESTAMPTZ DEFAULT now(),
  private_fields       JSONB DEFAULT '[]',
  languages            JSONB DEFAULT '[]',
  current_goal         TEXT DEFAULT '',
  demo                 BOOLEAN DEFAULT true
);

CREATE TABLE IF NOT EXISTS demo_projects (
  id   UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  data JSONB NOT NULL
);

-- ── RLS ───────────────────────────────────────────────────────────────────────
ALTER TABLE orgs       ENABLE ROW LEVEL SECURITY;
ALTER TABLE employees  ENABLE ROW LEVEL SECURITY;
ALTER TABLE projects   ENABLE ROW LEVEL SECURITY;

-- Service role (backend) bypasses RLS — all reads/writes go through FastAPI
-- which uses the service role key.

-- Demo tables are public read
ALTER TABLE demo_employees ENABLE ROW LEVEL SECURITY;
ALTER TABLE demo_projects  ENABLE ROW LEVEL SECURITY;
CREATE POLICY "public read demo_employees" ON demo_employees FOR SELECT USING (true);
CREATE POLICY "public read demo_projects"  ON demo_projects  FOR SELECT USING (true);
