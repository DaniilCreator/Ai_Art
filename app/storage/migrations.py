from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone

UTC = timezone.utc

SCHEMA_VERSION = 2


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return bool(row)


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def run_migrations(db_path: str) -> None:
    """Create or migrate DB schema.

    This project started with a schema that had a `category` column. MVP v2 removes categories
    and stores prompt ideas as (topic, subtopic, base_idea).

    If an old schema is detected, we perform a best-effort migration.
    """
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")

        # If no version is set, it'll be 0.
        user_ver = int(conn.execute("PRAGMA user_version").fetchone()[0])

        # Fresh install OR unknown: create v2 schema.
        if user_ver == 0 and not _table_exists(conn, "prompts"):
            _create_v2(conn)
            conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            conn.commit()
            return

        # Detect old schema (category-based) and migrate.
        if _table_exists(conn, "prompts"):
            cols = _columns(conn, "prompts")
            if "category" in cols and "topic" not in cols:
                _migrate_v1_to_v2(conn)
                conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                conn.commit()
                return

        # Ensure v2 tables exist (idempotent).
        _create_v2(conn)
        conn.execute(f"PRAGMA user_version={max(user_ver, SCHEMA_VERSION)}")
        conn.commit()

    finally:
        conn.close()


def _create_v2(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS prompts (
            id TEXT PRIMARY KEY,
            topic TEXT NOT NULL,
            subtopic TEXT NOT NULL,
            base_idea TEXT NOT NULL,
            last_used_at TEXT,
            times_used INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_prompts_topic ON prompts(topic);

        CREATE TABLE IF NOT EXISTS generated_images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prompt_ids TEXT NOT NULL,      -- JSON array of prompt id(s)
            prompt_text TEXT NOT NULL,
            negative_prompt TEXT,
            model_id TEXT NOT NULL,
            params_json TEXT NOT NULL,
            file_path TEXT NOT NULL,
            status TEXT NOT NULL,          -- generated|rejected|posted|error
            created_at TEXT NOT NULL,
            posted_at TEXT,
            sha256 TEXT NOT NULL UNIQUE,
            reject_reason TEXT,
            error_text TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_generated_status ON generated_images(status);

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
    )


def _migrate_v1_to_v2(conn: sqlite3.Connection) -> None:
    """Best-effort migration from old schema.

    Old prompts: (id INTEGER, section, name, category, base_idea, used, last_used_at)
    New prompts: (id TEXT, topic, subtopic, base_idea, last_used_at, times_used)

    Old generated_images had category & prompt_id FK. New stores prompt_ids JSON.
    """
    now = datetime.now(UTC).isoformat()

    # Backup old tables
    conn.execute("ALTER TABLE prompts RENAME TO prompts_v1")
    if _table_exists(conn, "generated_images"):
        conn.execute("ALTER TABLE generated_images RENAME TO generated_images_v1")

    _create_v2(conn)

    # Migrate prompts
    rows = conn.execute(
        "SELECT section, name, base_idea, last_used_at, used FROM prompts_v1"
    ).fetchall()

    for section, name, base_idea, last_used_at, used in rows:
        topic = str(section or "").strip() or "Unknown"
        subtopic = str(name or "").strip() or "Unknown"
        base_idea = str(base_idea or "").strip()
        if not base_idea:
            continue
        pid = _sha1(f"{topic}||{subtopic}||{base_idea}")

        times_used = 1 if int(used or 0) else 0
        conn.execute(
            "INSERT OR IGNORE INTO prompts(id, topic, subtopic, base_idea, last_used_at, times_used)"
            " VALUES(?,?,?,?,?,?)",
            (pid, topic, subtopic, base_idea, last_used_at, times_used),
        )

    # Migrate generated images (if exists)
    if _table_exists(conn, "generated_images_v1"):
        rows = conn.execute(
            "SELECT prompt_id, prompt_text, negative_prompt, model_id, params_json, file_path, status, created_at, posted_at, sha256, error_text "
            "FROM generated_images_v1"
        ).fetchall()

        # Map old numeric prompt_id -> new sha1 id by matching base_idea/prompt_text if possible
        # We'll do a naive approach: prompt_text may contain base_idea; fallback to empty list.
        for prompt_id, prompt_text, negative_prompt, model_id, params_json, file_path, status, created_at, posted_at, sha256, error_text in rows:
            prompt_ids: list[str] = []
            if prompt_id is not None:
                # Try to locate in old prompts_v1
                pr = conn.execute(
                    "SELECT section, name, base_idea FROM prompts_v1 WHERE id=?",
                    (prompt_id,),
                ).fetchone()
                if pr:
                    topic, subtopic, base_idea = pr
                    pid = _sha1(f"{topic}||{subtopic}||{base_idea}")
                    prompt_ids = [pid]

            conn.execute(
                "INSERT OR IGNORE INTO generated_images(prompt_ids,prompt_text,negative_prompt,model_id,params_json,file_path,status,created_at,posted_at,sha256,error_text)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    json.dumps(prompt_ids, ensure_ascii=False),
                    prompt_text,
                    negative_prompt,
                    model_id,
                    params_json,
                    file_path,
                    status,
                    created_at or now,
                    posted_at,
                    sha256,
                    error_text,
                ),
            )

    conn.commit()
