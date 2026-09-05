"""SQLite persistence for users, generation history, and versioned master
resumes - all scoped per-user.

Lives on a PersistentVolume in k8s (DB_PATH=/data/resume_builder.db) but
defaults to a relative path so local runs without a PVC still work, same
"sensible default" pattern the rest of this app uses (see LOKI_URL,
RESUME_EMAIL/PHONE in resume_contact.py).
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .config import DB_PATH


def _now():
    return datetime.now(timezone.utc).isoformat()


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _column_exists(conn, table, column):
    return any(r["name"] == column for r in conn.execute(f"PRAGMA table_info({table})").fetchall())


def init_db():
    """Create tables if missing, and migrate the two pre-multi-tenancy
    tables in place by adding a user_id column (defaulting existing rows
    to user 1 - see the Phase 3 runbook in the project's plan: the owner
    must log in first, before any public traffic, so their account
    deterministically claims id 1 and inherits this data).

    No seeding from app/master_resume.json happens here anymore - every
    user, including the owner post-migration, starts with an empty master
    resume and fills it in via the Edit Master Resume UI. Seeding a
    specific file at boot stopped making sense once "the DB" means many
    different people's data instead of one global resume.
    """
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = _connect()
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                oauth_provider TEXT NOT NULL,
                oauth_subject TEXT NOT NULL,
                email TEXT,
                display_name TEXT,
                avatar_url TEXT,
                anthropic_api_key_encrypted BLOB,
                UNIQUE (oauth_provider, oauth_subject)
            )"""
        )
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

        # One-time migration: SQLite has no "ADD COLUMN IF NOT EXISTS", so
        # guard with PRAGMA table_info. A constant DEFAULT lets one
        # ALTER TABLE both add the column and backfill every existing row.
        if not _column_exists(conn, "master_resume_versions", "user_id"):
            conn.execute(
                "ALTER TABLE master_resume_versions ADD COLUMN user_id INTEGER NOT NULL DEFAULT 1"
            )
        if not _column_exists(conn, "generation_history", "user_id"):
            conn.execute(
                "ALTER TABLE generation_history ADD COLUMN user_id INTEGER NOT NULL DEFAULT 1"
            )
        if not _column_exists(conn, "generation_history", "name"):
            # No DEFAULT needed (nullable) - existing rows just start
            # unnamed, same as any entry generated without ever renaming it.
            conn.execute("ALTER TABLE generation_history ADD COLUMN name TEXT")
        conn.commit()
    finally:
        conn.close()


# --- Users ---

def get_user(user_id):
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def upsert_user(provider, subject, email, display_name, avatar_url):
    """Insert a new user on first login via this OAuth identity, or
    refresh their profile fields (a provider can return a different
    display name/avatar on each login) on subsequent ones. The
    (provider, subject) identity itself never changes once set."""
    conn = _connect()
    try:
        existing = conn.execute(
            "SELECT id FROM users WHERE oauth_provider = ? AND oauth_subject = ?",
            (provider, subject),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE users SET email = ?, display_name = ?, avatar_url = ? WHERE id = ?",
                (email, display_name, avatar_url, existing["id"]),
            )
            conn.commit()
            return existing["id"]
        cur = conn.execute(
            """INSERT INTO users (created_at, oauth_provider, oauth_subject, email, display_name, avatar_url)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (_now(), provider, subject, email, display_name, avatar_url),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_user_api_key_encrypted(user_id):
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT anthropic_api_key_encrypted FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        return row["anthropic_api_key_encrypted"] if row else None
    finally:
        conn.close()


def set_user_api_key(user_id, encrypted_key):
    conn = _connect()
    try:
        conn.execute(
            "UPDATE users SET anthropic_api_key_encrypted = ? WHERE id = ?",
            (encrypted_key, user_id),
        )
        conn.commit()
    finally:
        conn.close()


def clear_user_api_key(user_id):
    conn = _connect()
    try:
        conn.execute("UPDATE users SET anthropic_api_key_encrypted = NULL WHERE id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()


# --- Master resume (per-user) ---

def get_current_master_resume(user_id):
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT data FROM master_resume_versions WHERE user_id = ? AND is_current = 1 ORDER BY id DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        return json.loads(row["data"]) if row else None
    finally:
        conn.close()


def save_master_resume_version(user_id, data):
    conn = _connect()
    try:
        # Scoped to this user only - an unscoped UPDATE here would clear
        # is_current for every other user's rows too.
        conn.execute("UPDATE master_resume_versions SET is_current = 0 WHERE user_id = ?", (user_id,))
        cur = conn.execute(
            "INSERT INTO master_resume_versions (user_id, created_at, data, is_current) VALUES (?, ?, ?, 1)",
            (user_id, _now(), json.dumps(data)),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def list_master_resume_versions(user_id):
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT id, created_at, is_current FROM master_resume_versions WHERE user_id = ? ORDER BY id DESC",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def restore_master_resume_version(user_id, version_id):
    """Rollback-as-new-version: copies an old version's data into a new
    current row, so history stays linear and nothing is lost. The
    user_id filter on the SELECT is the ownership check - without it any
    logged-in user could restore any other user's version by guessing an
    id (a real IDOR risk once this app is multi-tenant)."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT data FROM master_resume_versions WHERE id = ? AND user_id = ?",
            (version_id, user_id),
        ).fetchone()
        if row is None:
            return None
        conn.execute("UPDATE master_resume_versions SET is_current = 0 WHERE user_id = ?", (user_id,))
        cur = conn.execute(
            "INSERT INTO master_resume_versions (user_id, created_at, data, is_current) VALUES (?, ?, ?, 1)",
            (user_id, _now(), row["data"]),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


# --- Generation history (per-user) ---

def insert_history(user_id, job_description, status, tailored_resume=None, pdf_bytes=None, error_message=None):
    conn = _connect()
    try:
        cur = conn.execute(
            """INSERT INTO generation_history
               (user_id, created_at, job_description, status, tailored_resume, pdf, error_message)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                user_id,
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


def list_history(user_id):
    conn = _connect()
    try:
        rows = conn.execute(
            """SELECT id, created_at, job_description, status,
                      (pdf IS NOT NULL) AS has_pdf, error_message, name
               FROM generation_history WHERE user_id = ? ORDER BY id DESC""",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_history_pdf(user_id, history_id):
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT pdf FROM generation_history WHERE id = ? AND user_id = ?",
            (history_id, user_id),
        ).fetchone()
        return row["pdf"] if row and row["pdf"] is not None else None
    finally:
        conn.close()


def get_history_entry(user_id, history_id):
    """Full row (unlike list_history()'s lighter list-view projection),
    for opening a specific past generation in the editor. The user_id
    filter is the ownership check (see restore_master_resume_version)."""
    conn = _connect()
    try:
        row = conn.execute(
            """SELECT id, created_at, job_description, status,
                      (pdf IS NOT NULL) AS has_pdf, error_message, name, tailored_resume
               FROM generation_history WHERE id = ? AND user_id = ?""",
            (history_id, user_id),
        ).fetchone()
        if row is None:
            return None
        entry = dict(row)
        entry["data"] = json.loads(entry.pop("tailored_resume")) if entry["tailored_resume"] else None
        return entry
    finally:
        conn.close()


def update_history(user_id, history_id, tailored_resume, pdf_bytes):
    """Overwrite an existing entry's content/PDF in place (the "Save" path
    for editing a past generation - as opposed to insert_history(), which
    always creates a new row, used for "Save As")."""
    conn = _connect()
    try:
        cur = conn.execute(
            """UPDATE generation_history SET tailored_resume = ?, pdf = ?, status = 'success', error_message = NULL
               WHERE id = ? AND user_id = ?""",
            (json.dumps(tailored_resume), pdf_bytes, history_id, user_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def rename_history(user_id, history_id, name):
    """name=None clears back to the default job_description display. The
    user_id filter is the ownership check (see restore_master_resume_version) -
    rowcount 0 means either no such id or it belongs to someone else,
    which the router turns into a 404 either way."""
    conn = _connect()
    try:
        cur = conn.execute(
            "UPDATE generation_history SET name = ? WHERE id = ? AND user_id = ?",
            (name, history_id, user_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def delete_history(user_id, history_id):
    conn = _connect()
    try:
        cur = conn.execute(
            "DELETE FROM generation_history WHERE id = ? AND user_id = ?",
            (history_id, user_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()
