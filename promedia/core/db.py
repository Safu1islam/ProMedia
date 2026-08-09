"""SQLite access layer (DR-003).

All database access goes through here so the store stays replaceable. Pragmas
are applied per connection, not once at creation: SQLite scopes foreign_keys
and busy_timeout to the connection, so setting them at schema time would leave
later connections silently unprotected.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from ..errors import EntityLocked

SCHEMA_VERSION = 1
_SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(moment: datetime | None = None) -> str:
    return (moment or now()).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def canonical_json(payload: Any) -> str:
    """Stable serialisation.

    Determinism (C-20) and integrity hashing (F-8) both depend on identical
    input producing identical bytes, so key order and separators are fixed.
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def connect(db_path: Path, *, busy_timeout_ms: int = 5000) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
    # WAL is a persistent database property, but setting it per connection is
    # harmless and guarantees it even on a database created elsewhere.
    # In-memory databases do not support WAL; ignore the failure there.
    try:
        conn.execute("PRAGMA journal_mode = WAL")
    except sqlite3.DatabaseError:  # pragma: no cover
        pass
    return conn


def apply_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
    row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
    if row is None or row["v"] is None:
        conn.execute(
            "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
            (SCHEMA_VERSION, iso()),
        )


def schema_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
    return int(row["v"]) if row and row["v"] is not None else 0


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Explicit transaction.

    isolation_level=None means autocommit, so transactions are stated rather
    than implied. IMMEDIATE takes the write lock up front, which is what makes
    the publish claim in posts.py safe against a concurrent tick (DR-009).
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except Exception:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


# --- entity locks (C-19) ------------------------------------------------------


def acquire_lock(
    conn: sqlite3.Connection,
    entity_type: str,
    entity_id: str,
    *,
    task_id: str,
    agent: str,
    model: str,
    ttl_minutes: int,
) -> None:
    """Take exclusive ownership of an entity.

    Raises EntityLocked naming the current owner. Expired locks are reclaimable
    — a crashed agent must not block an entity forever.
    """
    moment = now()
    with transaction(conn):
        row = conn.execute(
            "SELECT agent, task_id, expires_at FROM entity_locks WHERE entity_type = ? AND entity_id = ?",
            (entity_type, entity_id),
        ).fetchone()
        if row is not None:
            expires = datetime.fromisoformat(row["expires_at"])
            if expires > moment and row["agent"] != agent:
                raise EntityLocked(
                    f"{entity_type} {entity_id} is locked by {row['agent']}",
                    entity_type=entity_type,
                    entity_id=entity_id,
                    owner=row["agent"],
                    owner_task=row["task_id"],
                    expires_at=row["expires_at"],
                )
            conn.execute(
                "DELETE FROM entity_locks WHERE entity_type = ? AND entity_id = ?",
                (entity_type, entity_id),
            )
        conn.execute(
            "INSERT INTO entity_locks (entity_type, entity_id, task_id, agent, model,"
            " acquired_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                entity_type,
                entity_id,
                task_id,
                agent,
                model,
                iso(moment),
                iso(moment + timedelta(minutes=ttl_minutes)),
            ),
        )


def release_lock(conn: sqlite3.Connection, entity_type: str, entity_id: str, *, agent: str) -> bool:
    cur = conn.execute(
        "DELETE FROM entity_locks WHERE entity_type = ? AND entity_id = ? AND agent = ?",
        (entity_type, entity_id, agent),
    )
    return cur.rowcount > 0


def list_locks(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute("SELECT * FROM entity_locks ORDER BY acquired_at")]
