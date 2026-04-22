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
    created_at  TEXT
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
            "INSERT INTO notes VALUES (?,?,?,?,?)",
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
