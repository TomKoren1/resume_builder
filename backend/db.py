"""SQLite persistence for generation history and versioned master resumes.

Lives on a PersistentVolume in k8s (DB_PATH=/data/resume_builder.db) but
defaults to a relative path so local runs without a PVC still work, same
"sensible default" pattern the rest of this app uses (see LOKI_URL,
RESUME_EMAIL/PHONE in resume_contact.py).
"""

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = os.environ.get("DB_PATH", "app/resume_builder.db")


def _now():
    return datetime.now(timezone.utc).isoformat()


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(seed_path="app/master_resume.json"):
    """Create tables if missing, and seed the first master resume version
    from the committed JSON if the table is empty (first boot only - after
    that the DB is the live source of truth)."""
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = _connect()
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS master_resume_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                data TEXT NOT NULL,
                is_current INTEGER NOT NULL DEFAULT 0
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS generation_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                job_description TEXT NOT NULL,
                status TEXT NOT NULL,
                tailored_resume TEXT,
                pdf BLOB,
                error_message TEXT
            )"""
        )
        conn.commit()

        count = conn.execute("SELECT COUNT(*) AS c FROM master_resume_versions").fetchone()["c"]
        if count == 0 and Path(seed_path).exists():
            with open(seed_path, "r", encoding="utf-8") as f:
                seed_data = f.read()
            conn.execute(
                "INSERT INTO master_resume_versions (created_at, data, is_current) VALUES (?, ?, 1)",
                (_now(), seed_data),
            )
            conn.commit()
    finally:
        conn.close()


def get_current_master_resume():
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT data FROM master_resume_versions WHERE is_current = 1 ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return json.loads(row["data"]) if row else None
    finally:
        conn.close()


def save_master_resume_version(data):
    conn = _connect()
    try:
        conn.execute("UPDATE master_resume_versions SET is_current = 0")
        cur = conn.execute(
            "INSERT INTO master_resume_versions (created_at, data, is_current) VALUES (?, ?, 1)",
            (_now(), json.dumps(data)),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def list_master_resume_versions():
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT id, created_at, is_current FROM master_resume_versions ORDER BY id DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def restore_master_resume_version(version_id):
    """Rollback-as-new-version: copies an old version's data into a new
    current row, so history stays linear and nothing is lost."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT data FROM master_resume_versions WHERE id = ?", (version_id,)
        ).fetchone()
        if row is None:
            return None
        conn.execute("UPDATE master_resume_versions SET is_current = 0")
        cur = conn.execute(
            "INSERT INTO master_resume_versions (created_at, data, is_current) VALUES (?, ?, 1)",
            (_now(), row["data"]),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def insert_history(job_description, status, tailored_resume=None, pdf_bytes=None, error_message=None):
    conn = _connect()
    try:
        cur = conn.execute(
            """INSERT INTO generation_history
               (created_at, job_description, status, tailored_resume, pdf, error_message)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                _now(),
                job_description,
                status,
                json.dumps(tailored_resume) if tailored_resume is not None else None,
                pdf_bytes,
                error_message,
            ),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def list_history():
    conn = _connect()
    try:
        rows = conn.execute(
            """SELECT id, created_at, job_description, status,
                      (pdf IS NOT NULL) AS has_pdf, error_message
               FROM generation_history ORDER BY id DESC"""
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_history_pdf(history_id):
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT pdf FROM generation_history WHERE id = ?", (history_id,)
        ).fetchone()
        return row["pdf"] if row and row["pdf"] is not None else None
    finally:
        conn.close()
