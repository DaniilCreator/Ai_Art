from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

UTC = timezone.utc


@dataclass(frozen=True)
class PromptRow:
    id: str
    topic: str
    subtopic: str
    base_idea: str
    last_used_at: str | None
    times_used: int


class DB:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    # ---------- prompts ----------
    def upsert_prompt(self, pid: str, topic: str, subtopic: str, base_idea: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO prompts(id, topic, subtopic, base_idea) VALUES (?,?,?,?)",
                (pid, topic, subtopic, base_idea),
            )

    def list_topics(self) -> list[str]:
        with self.connect() as conn:
            rows = conn.execute("SELECT DISTINCT topic FROM prompts ORDER BY topic").fetchall()
            return [r[0] for r in rows if r[0]]

    def get_recent_prompt_ids(self, limit: int) -> set[str]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT prompt_ids FROM generated_images WHERE status IN ('generated','posted') ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        recent: set[str] = set()
        for r in rows:
            try:
                arr = json.loads(r[0])
                if isinstance(arr, list):
                    for x in arr:
                        if isinstance(x, str):
                            recent.add(x)
            except Exception:
                continue
        return recent

    def pick_prompt_from_topic(self, topic: str, avoid_ids: set[str], limit_pool: int = 50) -> Optional[PromptRow]:
        """Pick a prompt from a topic, preferring least recently used.

        We do not use `used` flags anymore; `times_used/last_used_at` handle rotation.
        """
        with self.connect() as conn:
            params: list[Any] = [topic]
            not_in = ""
            if avoid_ids:
                not_in = " AND id NOT IN (%s)" % ",".join(["?"] * len(avoid_ids))
                params.extend(sorted(avoid_ids))

            rows = conn.execute(
                f"""
                SELECT id, topic, subtopic, base_idea, last_used_at, times_used
                FROM prompts
                WHERE topic=? {not_in}
                ORDER BY (last_used_at IS NOT NULL) ASC, last_used_at ASC, times_used ASC
                LIMIT ?
                """,
                (*params, limit_pool),
            ).fetchall()

            if not rows:
                # fallback: ignore avoid list
                rows = conn.execute(
                    """
                    SELECT id, topic, subtopic, base_idea, last_used_at, times_used
                    FROM prompts
                    WHERE topic=?
                    ORDER BY (last_used_at IS NOT NULL) ASC, last_used_at ASC, times_used ASC
                    LIMIT ?
                    """,
                    (topic, limit_pool),
                ).fetchall()

            if not rows:
                return None

            # choose randomly among the best pool to add variety
            import random

            row = random.choice(rows)
            return PromptRow(
                id=row["id"],
                topic=row["topic"],
                subtopic=row["subtopic"],
                base_idea=row["base_idea"],
                last_used_at=row["last_used_at"],
                times_used=int(row["times_used"]),
            )

    def mark_prompts_used(self, prompt_ids: Iterable[str]) -> None:
        now = datetime.now(UTC).isoformat()
        with self.connect() as conn:
            for pid in prompt_ids:
                conn.execute(
                    "UPDATE prompts SET last_used_at=?, times_used=times_used+1 WHERE id=?",
                    (now, pid),
                )

    # ---------- generated_images ----------
    def insert_generated(self, **kwargs: Any) -> int:
        with self.connect() as conn:
            cols = ",".join(kwargs.keys())
            qs = ",".join(["?"] * len(kwargs))
            cur = conn.cursor()
            cur.execute(f"INSERT INTO generated_images({cols}) VALUES ({qs})", tuple(kwargs.values()))
            return int(cur.lastrowid)

    def update_generated_status(self, gen_id: int, status: str, posted_at: str | None = None,
                               reject_reason: str | None = None, error_text: str | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE generated_images
                SET status=?,
                    posted_at=COALESCE(?, posted_at),
                    reject_reason=COALESCE(?, reject_reason),
                    error_text=COALESCE(?, error_text)
                WHERE id=?
                """,
                (status, posted_at, reject_reason, error_text, gen_id),
            )

    def get_oldest_pending_generated(self) -> Optional[sqlite3.Row]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM generated_images WHERE status='generated' ORDER BY id ASC LIMIT 1"
            ).fetchone()
            return row

    def sha256_exists(self, sha256: str) -> bool:
        with self.connect() as conn:
            row = conn.execute("SELECT 1 FROM generated_images WHERE sha256=? LIMIT 1", (sha256,)).fetchone()
            return row is not None

    # ---------- settings ----------
    def get_setting(self, key: str, default: str | None = None) -> str | None:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            return row[0] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO settings(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def count_generated_statuses(self) -> dict[str, int]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS c FROM generated_images GROUP BY status"
            ).fetchall()
            return {r[0]: int(r[1]) for r in rows}

    def get_last_errors(self, limit: int = 5) -> list[tuple[int, str, str]]:
        """Returns [(id, status, error_text_or_reason)]."""
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, status, COALESCE(error_text, reject_reason, '') AS msg
                FROM generated_images
                WHERE status IN ('error', 'rejected')
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [(int(r[0]), str(r[1]), str(r[2])) for r in rows]
