"""Storage ledger and admission control (DR-006, F-7).

The ceiling is enforced against ``committed + reserved + projected``, decided
BEFORE any byte is written. Checking free disk space at write time — the usual
approach — cannot express a footprint for work not yet done, which is exactly
the failure mode a 20-file batch produces: the source fits, the derivatives do
not, and by then the bytes are already on disk.

The ledger, not the filesystem, is the source of truth for usage.
"""

from __future__ import annotations

import sqlite3
from datetime import timedelta
from typing import Any

from ..errors import CeilingExceeded, LedgerDrift
from ..config import Config
from .db import canonical_json, iso, new_id, now, transaction


def projected_bytes(config: Config, master_bytes: int) -> int:
    """Master plus the derivatives it will require.

    Multiplier is configuration (A-3), not a literal, because it is the
    assumption most likely to change — adding a platform moves it.
    """
    return int(master_bytes + master_bytes * config.derivative_multiplier)


def usage(conn: sqlite3.Connection) -> dict[str, int]:
    row = conn.execute(
        "SELECT"
        " COALESCE(SUM(CASE WHEN state = 'committed' THEN bytes ELSE 0 END), 0) AS committed,"
        " COALESCE(SUM(CASE WHEN state = 'reserved' AND (expires_at IS NULL OR expires_at > ?)"
        "     THEN bytes ELSE 0 END), 0) AS reserved"
        " FROM storage_ledger",
        (iso(),),
    ).fetchone()
    committed = int(row["committed"])
    reserved = int(row["reserved"])
    return {"committed_bytes": committed, "reserved_bytes": reserved, "total_bytes": committed + reserved}


def status(conn: sqlite3.Connection, config: Config) -> dict[str, Any]:
    u = usage(conn)
    total = u["total_bytes"]
    ceiling = config.ceiling_bytes
    return {
        **u,
        "ceiling_bytes": ceiling,
        "warn_bytes": config.warn_bytes,
        "refuse_bytes": config.refuse_bytes,
        "available_bytes": max(0, config.refuse_bytes - total),
        "fraction_used": round(total / ceiling, 4) if ceiling else 0.0,
        "state": (
            "refusing" if total >= config.refuse_bytes
            else "warning" if total >= config.warn_bytes
            else "ok"
        ),
    }


def reclaim_expired(conn: sqlite3.Connection) -> int:
    """Release reservations abandoned by a crashed ingest.

    Without this a failed ingest would consume quota permanently, and the
    ceiling would ratchet down until the system refused everything.
    """
    cur = conn.execute(
        "UPDATE storage_ledger SET state = 'released', released_at = ?"
        " WHERE state = 'reserved' AND expires_at IS NOT NULL AND expires_at <= ?",
        (iso(), iso()),
    )
    return cur.rowcount


def reserve(
    conn: sqlite3.Connection,
    config: Config,
    *,
    master_bytes: int,
    asset_id: str | None = None,
    kind: str = "master",
) -> str:
    """Claim quota before writing. Raises CeilingExceeded with the shortfall."""
    projected = projected_bytes(config, master_bytes)
    with transaction(conn):
        conn.execute(
            "UPDATE storage_ledger SET state = 'released', released_at = ?"
            " WHERE state = 'reserved' AND expires_at IS NOT NULL AND expires_at <= ?",
            (iso(), iso()),
        )
        u = usage(conn)
        if u["total_bytes"] + projected > config.refuse_bytes:
            shortfall = u["total_bytes"] + projected - config.refuse_bytes
            raise CeilingExceeded(
                "storage ceiling would be exceeded; ingest refused",
                projected_bytes=projected,
                shortfall_bytes=shortfall,
                **usage(conn),
                refuse_bytes=config.refuse_bytes,
                ceiling_bytes=config.ceiling_bytes,
            )
        reservation_id = new_id("res")
        ttl = int(config.get("storage", "reservation_ttl_seconds"))
        conn.execute(
            "INSERT INTO storage_ledger (id, asset_id, kind, bytes, state, created_at, expires_at)"
            " VALUES (?, ?, ?, ?, 'reserved', ?, ?)",
            (reservation_id, asset_id, kind, projected, iso(), iso(now() + timedelta(seconds=ttl))),
        )
    return reservation_id


def commit(conn: sqlite3.Connection, reservation_id: str, *, asset_id: str, actual_bytes: int | None = None) -> None:
    """Convert a reservation into committed usage.

    BLOCKING finding B4 (independent review, 2026-08-08). This used to be a
    fire-and-forget UPDATE. If the reservation had already expired and been
    reclaimed by a concurrent ingest — which a sleeping Windows desktop makes
    ordinary rather than exotic — the UPDATE matched nothing, returned silently,
    and the bytes landed on disk counting ZERO against the ceiling. DR-006 makes
    the ledger the sole source of truth, so nothing could ever detect the
    shortfall; the drift would accumulate until the disk, not the ledger, ran
    out. Protocol 05: fail loudly and recoverably.
    """
    with transaction(conn):
        if actual_bytes is None:
            cur = conn.execute(
                "UPDATE storage_ledger SET state = 'committed', asset_id = ?, expires_at = NULL"
                " WHERE id = ? AND state = 'reserved'",
                (asset_id, reservation_id),
            )
        else:
            cur = conn.execute(
                "UPDATE storage_ledger SET state = 'committed', asset_id = ?, bytes = ?, expires_at = NULL"
                " WHERE id = ? AND state = 'reserved'",
                (asset_id, int(actual_bytes), reservation_id),
            )
        if cur.rowcount == 0:
            row = conn.execute(
                "SELECT state FROM storage_ledger WHERE id = ?", (reservation_id,)
            ).fetchone()
            raise LedgerDrift(
                "storage reservation could not be committed; it was expired or already"
                " resolved, so these bytes would not have counted against the ceiling",
                reservation_id=reservation_id,
                state=row["state"] if row else "missing",
                remedy="re-run ingest; run reclaim-reservations to tidy expired rows",
            )


def release(conn: sqlite3.Connection, reservation_id: str) -> None:
    """Release a RESERVED row only.

    Scoped to 'reserved' (finding B4): the previous `state != 'released'`
    predicate would happily flip an already-COMMITTED row to released, erasing
    accounted storage that is genuinely on disk.
    """
    conn.execute(
        "UPDATE storage_ledger SET state = 'released', released_at = ? WHERE id = ? AND state = 'reserved'",
        (iso(), reservation_id),
    )


def enqueue_refused(
    conn: sqlite3.Connection,
    *,
    source_path: str,
    projected: int,
    declaration: dict[str, Any],
    shortfall_bytes: int,
) -> str:
    """F-7: refused ingest is queued, never discarded."""
    queue_id = new_id("q")
    conn.execute(
        "INSERT INTO ingest_queue (id, source_path, projected_bytes, declaration, queued_at,"
        " status, shortfall_bytes) VALUES (?, ?, ?, ?, ?, 'queued', ?)",
        (queue_id, source_path, projected, canonical_json(declaration), iso(), int(shortfall_bytes)),
    )
    return queue_id


def queued(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM ingest_queue WHERE status = 'queued' ORDER BY queued_at"
        )
    ]
