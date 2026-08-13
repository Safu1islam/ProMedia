"""Export of the permanent set (T-036, project.md 5.4).

project.md divides everything this system holds into two sets. The PERMANENT
set — rights evidence, provenance chains, published-post records, the approval
and audit log — must survive disk loss. The TRANSIENT set — masters, proxies,
renders, caches — is deleted by retention policy or is recomputable, and is
explicitly out of scope for backup. That division is why this is cheap: masters
are the only large thing here, and they are the thing deliberately not backed
up, so the artefact is megabytes.

What makes this task non-trivial is not moving bytes. It is three properties
that are easy to lose and expensive to lose silently:

* **No secret may ride along.** DR-008 keeps credentials out of the database
  precisely so they are absent from backup artefacts. An export that carried a
  credential off-site would defeat the control the entire credential design
  exists to provide, and it would do so invisibly — the artefact would look
  fine. Asserted with a canary in tests, never by reading the code.
* **Provenance must still verify after the round trip.** F-8 makes a sealed
  record self-contained and integrity-hashed. A backup of evidence whose
  integrity check fails on restore is a backup of bytes, not of evidence.
* **A new table must be classified, not defaulted.** The failure mode here is a
  table added to the schema years from now that silently falls outside the
  export and is discovered missing during a restore. ``classify_tables`` refuses
  to let that happen quietly.

Where the artefact GOES is deliberately not this module's business (T-038). What
to back up and where to put it are separate questions, and answering them
together is how the second answer quietly constrains the first.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

from ..errors import ProMediaError, ValidationError
from .db import canonical_json, iso

ARTEFACT_VERSION = 1

# The permanent set of project.md 5.4, mapped to tables. Order matters on
# restore: a table is listed after everything it references, so a straight
# replay satisfies the foreign keys T-002 turned on.
PERMANENT_TABLES: tuple[str, ...] = (
    "schema_version",
    # Identity of the things evidence is ABOUT. The asset row is not the media —
    # the media is transient and its bytes are not here. Without it, a published
    # post and its rights evidence would reference an id with nothing behind it.
    "accounts",
    "assets",
    # Rights evidence (5.4, first bullet).
    "rights_declarations",
    "evidence",
    "rights_verdicts",
    # Provenance chains (second bullet).
    "provenance_records",
    # Published-post records (third bullet).
    "posts",
    "publications",
    # Approval and audit log (fourth bullet).
    "approvals",
    "audit_log",
)

# Excluded, each for a stated reason. Being listed here is what makes the
# exclusion a decision; a table in neither tuple is an unclassified table and
# classify_tables() refuses it.
TRANSIENT_TABLES: dict[str, str] = {
    "storage_ledger": (
        "Facts about THIS machine's disk, recomputed from what is actually "
        "stored. Restoring a ledger from another point in time would assert a "
        "committed footprint that does not match the files present, and DR-006 "
        "makes the ledger the sole source of truth for the F-7 ceiling — so a "
        "stale one is worse than an absent one."
    ),
    "ingest_queue": (
        "Work waiting on local storage that was refused at admission. It is "
        "about a disk state that no longer exists after a restore."
    ),
    "entity_locks": (
        "Session state (C-19). Restoring locks would wedge every listed entity "
        "against agent sessions that no longer exist, and the TTL that normally "
        "reclaims them would be measured from a timestamp in the past."
    ),
}


def classify_tables(conn: sqlite3.Connection) -> dict[str, list[str]]:
    """Every real table, split into permanent and transient. Refuses surprises.

    AC-1. The point is the failure: a table added to the schema later is in
    neither tuple, so this raises instead of quietly leaving it out of every
    future backup. Discovering that during a restore is the expensive version of
    the same discovery.
    """
    actual = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    known = set(PERMANENT_TABLES) | set(TRANSIENT_TABLES)
    unclassified = sorted(actual - known)
    if unclassified:
        raise ProMediaError(
            f"table(s) {unclassified} are in the schema but classified neither "
            "permanent nor transient; classify them in promedia.core.backup "
            "before taking a backup that would silently omit them",
            unclassified=unclassified,
        )
    missing = sorted(set(PERMANENT_TABLES) - actual)
    if missing:
        raise ProMediaError(
            f"permanent table(s) {missing} are declared but absent from this "
            "database; the schema and the backup definition disagree",
            missing=missing,
        )
    return {
        "permanent": [t for t in PERMANENT_TABLES if t in actual],
        "transient": sorted(t for t in TRANSIENT_TABLES if t in actual),
    }


def _rows(conn: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    # Ordered by rowid so two exports of an unchanged database are byte-identical,
    # which is what lets a caller detect "nothing changed" without a diff.
    cursor = conn.execute(f"SELECT * FROM {table} ORDER BY rowid")  # noqa: S608 - fixed set
    columns = [d[0] for d in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def build(conn: sqlite3.Connection, *, at: str | None = None) -> dict[str, Any]:
    """The artefact, as a dictionary. Self-contained and self-describing.

    The integrity hash covers the payload only, computed over canonical JSON —
    the same construction provenance sealing uses (F-8), so the two agree about
    what "unchanged" means.
    """
    classified = classify_tables(conn)
    payload = {table: _rows(conn, table) for table in classified["permanent"]}
    schema_version = None
    if payload.get("schema_version"):
        schema_version = payload["schema_version"][-1].get("version")

    return {
        "artefact_version": ARTEFACT_VERSION,
        "schema_version": schema_version,
        "created_at": at or iso(),
        "tables": list(payload),
        "excluded_tables": {t: TRANSIENT_TABLES[t] for t in classified["transient"]},
        "row_counts": {table: len(rows) for table, rows in payload.items()},
        "payload": payload,
        "integrity_hash": integrity_hash(payload),
        # Said plainly inside the artefact, because someone restoring one in
        # five years will not have read this module. F-7/5.4: masters are
        # transient by policy and are NOT here.
        "note": (
            "Permanent set only (project.md 5.4). Media masters, proxies, renders "
            "and caches are transient by policy and are NOT contained in this "
            "artefact; restoring it recovers the rights, provenance, publication "
            "and audit record, not the media."
        ),
    }


def integrity_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def verify(artefact: dict[str, Any]) -> dict[str, Any]:
    """Check an artefact against its own hash. AC-4.

    Takes the artefact rather than a path so it can be verified wherever it has
    got to — after transport, after storage, on a machine that has no ProMedia
    database at all.
    """
    if not isinstance(artefact, dict) or "payload" not in artefact:
        raise ValidationError("not a ProMedia backup artefact", got=type(artefact).__name__)
    expected = artefact.get("integrity_hash")
    actual = integrity_hash(artefact["payload"])
    return {
        "ok": expected == actual,
        "integrity_verified": expected == actual,
        "artefact_version": artefact.get("artefact_version"),
        "schema_version": artefact.get("schema_version"),
        "created_at": artefact.get("created_at"),
        "row_counts": artefact.get("row_counts", {}),
        "expected_hash": expected,
        "actual_hash": actual,
    }


def dumps(artefact: dict[str, Any]) -> str:
    return json.dumps(artefact, indent=2, sort_keys=True, default=str)
