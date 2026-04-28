"""
SQLite DB: schema, connection helper, seed runner.
Called from main.py on startup and every DB_RESET_INTERVAL seconds.
"""

import os
import sqlite3
from contextlib import contextmanager

from .seed_data import APPOINTMENTS, CAREGIVERS, LABS, NOTES, PATIENTS

DB_PATH = os.environ.get("DB_PATH", "/app/medimind.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS patients (
    id                INTEGER PRIMARY KEY,
    name              TEXT NOT NULL,
    dob               TEXT NOT NULL,
    email             TEXT,
    phone             TEXT,
    ssn_last4         TEXT,
    role              TEXT DEFAULT 'patient',
    condition_summary TEXT
);

CREATE TABLE IF NOT EXISTS labs (
    id          INTEGER PRIMARY KEY,
    patient_id  INTEGER REFERENCES patients(id),
    test_name   TEXT,
    value       REAL,
    unit        TEXT,
    taken_at    TEXT,
    flag        TEXT
);

CREATE TABLE IF NOT EXISTS notes (
    id          INTEGER PRIMARY KEY,
    patient_id  INTEGER REFERENCES patients(id),
    author      TEXT,
    content     TEXT,
    created_at  TEXT,
    doctor_only INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS appointments (
    id            INTEGER PRIMARY KEY,
    patient_id    INTEGER REFERENCES patients(id),
    provider      TEXT,
    scheduled_at  TEXT,
    status        TEXT
);

CREATE TABLE IF NOT EXISTS caregivers (
    patient_id            INTEGER REFERENCES patients(id),
    caregiver_patient_id  INTEGER REFERENCES patients(id),
    PRIMARY KEY (patient_id, caregiver_patient_id)
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id  TEXT PRIMARY KEY,
    patient_id  INTEGER REFERENCES patients(id),
    mode        TEXT,
    translator  TEXT,
    started_at  TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT,
    caller_id   INTEGER,
    tool        TEXT,
    args_json   TEXT,
    allowed     INTEGER,
    reason      TEXT,
    duration_ms REAL,
    ts          TEXT
);
"""

DROP_ALL = """
DROP TABLE IF EXISTS audit_log;
DROP TABLE IF EXISTS sessions;
DROP TABLE IF EXISTS caregivers;
DROP TABLE IF EXISTS appointments;
DROP TABLE IF EXISTS notes;
DROP TABLE IF EXISTS labs;
DROP TABLE IF EXISTS patients;
"""


@contextmanager
def conn():
    """Thread-safe SQLite connection. Row factory gives dict-like rows."""
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    try:
        yield c
    finally:
        c.close()


def init_and_seed() -> None:
    """Drop everything and reseed from seed_data.py constants."""
    with conn() as c:
        c.executescript(DROP_ALL)
        c.executescript(SCHEMA)
        c.executemany(
            "INSERT INTO patients VALUES (?,?,?,?,?,?,?,?)",
            PATIENTS,
        )
        c.executemany(
            "INSERT INTO labs VALUES (?,?,?,?,?,?,?)",
            LABS,
        )
        c.executemany(
            "INSERT INTO notes VALUES (?,?,?,?,?,?)",
            NOTES,
        )
        c.executemany(
            "INSERT INTO appointments VALUES (?,?,?,?,?)",
            APPOINTMENTS,
        )
        c.executemany(
            "INSERT INTO caregivers VALUES (?,?)",
            CAREGIVERS,
        )
        c.commit()


# ─────────────────────────────────────────────────────────────────────────────
# Summit demo: prompts / skills / routing / unified_log tables
# Separate from DEFCON schema. Additive only.
# ─────────────────────────────────────────────────────────────────────────────
SUMMIT_SCHEMA = """
CREATE TABLE IF NOT EXISTS summit_prompts (
  product_id TEXT PRIMARY KEY,
  version INTEGER NOT NULL,
  system_prompt TEXT NOT NULL,
  tool_ids TEXT NOT NULL,
  skill_ids TEXT NOT NULL,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS summit_skills (
  skill_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT,
  instructions TEXT NOT NULL,
  tags TEXT,
  dependencies TEXT,
  inject_full INTEGER DEFAULT 1,
  status TEXT DEFAULT 'active',
  version INTEGER DEFAULT 1,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS summit_routing (
  product_id TEXT PRIMARY KEY,
  model_id TEXT NOT NULL,
  inference_config TEXT NOT NULL,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS summit_unified_log (
  call_id TEXT PRIMARY KEY,
  tenant_id TEXT,
  user_id TEXT,
  session_id TEXT,
  product_id TEXT,
  prompt_id TEXT,
  prompt_version INTEGER,
  model_id TEXT,
  input_tokens INTEGER,
  output_tokens INTEGER,
  cost_usd REAL,
  latency_ms INTEGER,
  tools_called TEXT,
  skill_ids TEXT,
  guardrail_triggered INTEGER DEFAULT 0,
  error TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


def init_summit_tables():
    """Create summit tables and seed them (idempotent: reseeds every call)."""
    import json

    from .middleware.seed import PROMPTS, ROUTING, SKILLS

    with conn() as c:
        c.executescript(SUMMIT_SCHEMA)

        # Reseed prompts
        c.execute("DELETE FROM summit_prompts")
        c.executemany(
            "INSERT INTO summit_prompts (product_id, version, system_prompt, tool_ids, skill_ids) "
            "VALUES (?, ?, ?, ?, ?)",
            [(p[0], p[1], p[2], json.dumps(p[3]), json.dumps(p[4])) for p in PROMPTS],
        )

        # Reseed skills
        c.execute("DELETE FROM summit_skills")
        c.executemany(
            "INSERT INTO summit_skills "
            "(skill_id, name, description, instructions, tags, dependencies, "
            "inject_full, status, version) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    s[0], s[1], s[2], s[3],
                    json.dumps(s[4]), json.dumps(s[5]),
                    s[6], s[7], s[8],
                )
                for s in SKILLS
            ],
        )

        # Reseed routing
        c.execute("DELETE FROM summit_routing")
        c.executemany(
            "INSERT INTO summit_routing (product_id, model_id, inference_config) "
            "VALUES (?, ?, ?)",
            [(r[0], r[1], json.dumps(r[2])) for r in ROUTING],
        )

        c.commit()
