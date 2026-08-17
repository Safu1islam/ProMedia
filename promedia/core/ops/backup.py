"""Backup capabilities (T-036, T-038, T-039).

Registered like everything else, so the permanent set can be exported from
either surface (F-1) and, by the scheduler (T-039), through the same
repo-callable path the operator uses.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from ...errors import IntegrityError, NotFound, ValidationError
from .. import backup
from ..audit import record
from ..db import now
from ..registry import Context, Param, register

# T-039. One rolling local snapshot, not a growing pile — the local export
# needs no drive and can run unattended on a schedule, but it is same-disk
# and does NOT satisfy F-7/5.4's off-site durability requirement on its own
# (that is send-offsite's job, and it still needs a human to plug in the
# drive). Its value is narrower and specific: proving the export mechanism
# itself still works on a cadence, so a regression (a table that stops
# classifying, a schema drift) is caught by a quiet scheduled run instead of
# by a restore that needed it.
_LOCAL_SNAPSHOT_DIRNAME = "backups"
_LOCAL_SNAPSHOT_FILENAME = "promedia-backup-local.json"


@register(
    "export-permanent-set",
    "Export rights evidence, provenance, publication and audit records to a verifiable artefact.",
    params=(
        Param(
            "destination",
            "str",
            required=False,
            help=(
                "File path to write the artefact to. Omit to return it inline,"
                " which is useful for inspection but not for backup."
            ),
        ),
    ),
    authority="operator",
    mutates=False,
    danger="Writes the rights, provenance and audit record to a file you choose the location of.",
)
def export_permanent_set(ctx: Context, destination: str | None = None) -> dict[str, Any]:
    """Operator authority despite being read-only.

    Every other read here is agent-callable, and this one is not: it collects
    the entire audit log and publication history into a single portable file
    whose location the caller chooses. That is a capability worth a human, and
    the authority check is the only thing standing between "an agent may read
    the audit log" and "an agent may write the whole of it anywhere it likes".
    """
    artefact = backup.build(ctx.conn)
    summary = {
        "ok": True,
        "artefact_version": artefact["artefact_version"],
        "schema_version": artefact["schema_version"],
        "created_at": artefact["created_at"],
        "row_counts": artefact["row_counts"],
        "excluded_tables": sorted(artefact["excluded_tables"]),
        "integrity_hash": artefact["integrity_hash"],
        "note": artefact["note"],
    }

    if destination is None:
        return {**summary, "written_to": None, "artefact": artefact}

    path = Path(destination).expanduser()
    if path.is_dir():
        raise ValidationError(
            f"destination '{destination}' is a directory; name the file to write",
            parameter="destination",
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(backup.dumps(artefact), encoding="utf-8")
    return {**summary, "written_to": str(path), "bytes": path.stat().st_size}


@register(
    "send-offsite",
    "Copy the permanent-set artefact to the off-site destination (OD-9: an "
    "external/removable drive) and record the transport.",
    params=(
        Param(
            "destination",
            "str",
            required=True,
            help=(
                "Directory to copy the artefact into — the mount point of an"
                " external/removable drive, or a folder on it."
            ),
        ),
    ),
    authority="operator",
    mutates=False,
    danger="Writes the rights, provenance and audit record to a drive outside this machine.",
)
def send_offsite(ctx: Context, destination: str) -> dict[str, Any]:
    """OD-9: an external/removable drive, not a third party.

    That is why AC-2's encryption clause does not fire here — it is
    conditional on a third-party destination. No secret rides along either
    way: DR-008 already keeps credentials out of the database, so out of
    every artefact this module builds.

    Refuses up front rather than writing a partial or unreadable copy: a
    destination that exists as a file is refused before anything is written,
    and one that cannot be created or written to (typically: the drive is
    not connected) raises with that read directly, not a bare OSError.

    Verified on the DESTINATION after the write, not just at the source —
    the source artefact is trivially correct since ``backup.build`` just
    made it; what a transport can actually get wrong is the copy, and the
    only way to catch that is to read back what landed and hash it again.
    """
    dest_root = Path(destination).expanduser()
    if dest_root.exists() and not dest_root.is_dir():
        raise ValidationError(
            f"destination '{destination}' exists and is not a directory",
            parameter="destination",
        )
    try:
        dest_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise NotFound(
            f"cannot reach destination '{destination}' ({exc.strerror or exc}); "
            "check the drive is connected and the path is correct",
            destination=str(dest_root),
        ) from exc

    artefact = backup.build(ctx.conn)
    # Colons in an ISO timestamp are not a legal Windows filename character;
    # everything else in it is.
    safe_stamp = artefact["created_at"].replace(":", "-")
    filename = f"promedia-backup-{safe_stamp}.json"
    dest_path = dest_root / filename
    try:
        dest_path.write_text(backup.dumps(artefact), encoding="utf-8")
    except OSError as exc:
        raise NotFound(
            f"could not write to '{dest_path}' ({exc.strerror or exc}); check the "
            "drive is connected, writable, and has room",
            destination=str(dest_path),
        ) from exc

    written = json.loads(dest_path.read_text(encoding="utf-8"))
    verified = backup.verify(written)
    if not verified["integrity_verified"]:
        raise IntegrityError(
            f"artefact at '{dest_path}' failed integrity verification on "
            "read-back; the transport is not trustworthy — retry it",
            destination=str(dest_path),
        )

    # AC-1: what was sent, when, and its hash — durable at the destination
    # itself, so the drive is self-describing even read on a machine with no
    # ProMedia database, the same reasoning `backup.verify` already applies
    # to the artefact. One line appended per transport, never rewritten.
    manifest_entry = {
        "sent_at": artefact["created_at"],
        "artefact_file": filename,
        "integrity_hash": artefact["integrity_hash"],
        "bytes": dest_path.stat().st_size,
        "row_counts": artefact["row_counts"],
    }
    manifest_path = dest_root / "promedia-backup-manifest.jsonl"
    try:
        with manifest_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(manifest_entry, sort_keys=True) + "\n")
    except OSError as exc:
        raise NotFound(
            f"artefact '{dest_path}' was written and verified, but the manifest "
            f"at '{manifest_path}' could not be updated ({exc.strerror or exc}); "
            "the drive likely disconnected mid-transport — check it and retry",
            destination=str(manifest_path),
        ) from exc

    return {
        "ok": True,
        "sent_to": str(dest_path),
        "manifest": str(manifest_path),
        "bytes": dest_path.stat().st_size,
        "created_at": artefact["created_at"],
        "integrity_hash": artefact["integrity_hash"],
        "row_counts": artefact["row_counts"],
        "verified_on_destination": True,
        "encrypted": False,
        "note": (
            "Not encrypted: OD-9 chose an external/removable drive, which is "
            "not a third party. AC-2 applies only when the destination IS a "
            "third party (a cloud drive or object storage) and must be "
            "implemented before this operation is pointed at one."
        ),
    }


@register(
    "verify-backup",
    "Check a backup artefact against its own integrity hash.",
    params=(Param("source", "str", help="Path to an artefact written by export-permanent-set."),),
)
def verify_backup(ctx: Context, source: str) -> dict[str, Any]:
    """Agent-readable: verifying a backup must be cheap and frequent.

    Deliberately does not consult the database. An artefact that can only be
    verified against the system that produced it is not verifiable off-site,
    which is the only place it will ever matter.
    """
    path = Path(source).expanduser()
    if not path.is_file():
        raise NotFound(f"no backup artefact at '{source}'", source=str(path))
    try:
        artefact = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValidationError(
            f"'{source}' is not readable as a backup artefact: {exc}", parameter="source"
        ) from exc
    return {**backup.verify(artefact), "source": str(path)}


@register(
    "restore-permanent-set",
    "Rebuild rights, provenance, publication and audit records from a backup artefact.",
    params=(Param("source", "str", help="Path to an artefact written by export-permanent-set."),),
    authority="operator",
    mutates=True,
    danger=(
        "Writes the entire permanent record into this database. Only possible on an"
        " empty one, and it does NOT restore media."
    ),
)
def restore_permanent_set(ctx: Context, source: str) -> dict[str, Any]:
    """Operator authority: this reconstitutes the whole rights and audit history.

    No entity lock is taken. The operation is only permitted against an empty
    database, so there is no existing entity for another agent to be holding,
    and a lock over 'every entity at once' is not a thing C-19 expresses.
    """
    from .. import db as db_layer

    path = Path(source).expanduser()
    if not path.is_file():
        raise NotFound(f"no backup artefact at '{source}'", source=str(path))
    try:
        artefact = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValidationError(
            f"'{source}' is not readable as a backup artefact: {exc}", parameter="source"
        ) from exc

    result = backup.restore(
        ctx.conn, artefact, build_schema_version=db_layer.SCHEMA_VERSION
    )
    return {**result, "source": str(path)}


@register(
    "backup-scope",
    "Report which tables are backed up, which are excluded, and why.",
)
def backup_scope(ctx: Context) -> dict[str, Any]:
    """What a restore will and will not bring back, before it is needed.

    The question this answers — "is my media in the backup?" — has a surprising
    answer (no, by policy), and the worst time to discover it is during a
    recovery.
    """
    classified = backup.classify_tables(ctx.conn)
    return {
        "ok": True,
        "permanent": classified["permanent"],
        "excluded": {t: backup.TRANSIENT_TABLES[t] for t in classified["transient"]},
        "media_included": False,
        "note": backup.build(ctx.conn)["note"],
    }


# --- scheduling and staleness (T-039) -----------------------------------------


def _local_snapshot_path(ctx: Context) -> Path:
    return ctx.config.data_dir / _LOCAL_SNAPSHOT_DIRNAME / _LOCAL_SNAPSHOT_FILENAME


def _last_offsite_send(ctx: Context) -> str | None:
    """DR-024's own revisit note: read audit_log's send-offsite entries as the
    source of "when did off-site last succeed", rather than a second record.

    outcome='allowed' only — a denied or failed attempt did not reach the
    drive, per invoke()'s own recording rule (registry.py), so it must not
    count as a successful transport.
    """
    row = ctx.conn.execute(
        "SELECT at FROM audit_log WHERE operation = 'send-offsite' AND outcome = 'allowed'"
        " ORDER BY at DESC LIMIT 1"
    ).fetchone()
    return row["at"] if row else None


def _age(at: datetime, moment: str | None) -> float | None:
    """Hours (well, whatever unit the caller wants) between `moment` and `at`.

    Returns None for "never happened" rather than a sentinel number, so a
    caller cannot mistake "no backup yet" for "an ancient one" — both would
    otherwise render as some very large float.
    """
    if moment is None:
        return None
    parsed = datetime.fromisoformat(moment)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=at.tzinfo)
    return (at - parsed).total_seconds()


def _freshness(ctx: Context, at: datetime) -> dict[str, Any]:
    """The staleness picture both `backup-tick` and `backup-status` report.

    One function, not two copies: AC-1 requires this be reportable from both
    surfaces, and a tick's own report drifting from a plain status read would
    be exactly the kind of duplicate implementation F-1/DR-002 forbids.
    """
    local_hours_threshold = float(ctx.config.get("backup", "local_export_overdue_hours"))
    offsite_days_threshold = float(ctx.config.get("backup", "offsite_overdue_days"))

    local_path = _local_snapshot_path(ctx)
    local_created_at = None
    local_integrity_verified = None
    if local_path.is_file():
        try:
            snapshot = json.loads(local_path.read_text(encoding="utf-8"))
            local_created_at = snapshot.get("created_at")
            local_integrity_verified = backup.verify(snapshot)["integrity_verified"]
        except (ValueError, OSError):
            # Unreadable is reported, not raised — a status read must never
            # itself fail because the thing it is checking on is broken.
            local_integrity_verified = False

    local_age_seconds = _age(at, local_created_at)
    local_overdue = (
        local_age_seconds is None
        or not local_integrity_verified
        or local_age_seconds > local_hours_threshold * 3600
    )

    offsite_last_sent = _last_offsite_send(ctx)
    offsite_age_seconds = _age(at, offsite_last_sent)
    offsite_overdue = offsite_age_seconds is None or offsite_age_seconds > offsite_days_threshold * 86400

    return {
        "local_export": {
            "path": str(local_path),
            "exists": local_path.is_file(),
            "created_at": local_created_at,
            "integrity_verified": local_integrity_verified,
            "age_hours": round(local_age_seconds / 3600, 2) if local_age_seconds is not None else None,
            "overdue_threshold_hours": local_hours_threshold,
            "overdue": local_overdue,
        },
        "offsite": {
            "last_sent_at": offsite_last_sent,
            "age_days": round(offsite_age_seconds / 86400, 2) if offsite_age_seconds is not None else None,
            "overdue_threshold_days": offsite_days_threshold,
            "overdue": offsite_overdue,
        },
    }


@register(
    "backup-tick",
    "Run the scheduled local backup export and surface off-site staleness. Idempotent.",
    authority="operator",
    mutates=False,
    danger="Writes a local backup snapshot to disk. Intended to be called by the scheduler, not by hand.",
)
def backup_tick(ctx: Context) -> dict[str, Any]:
    """DR-009's tick pattern (T-018), reused rather than a second scheduler.

    Operator authority, matching export-permanent-set and send-offsite: this
    collects the entire audit log, publication history and rights evidence
    into a file on disk, which is a capability worth a human even though the
    destination this time is fixed rather than caller-chosen.

    What it does NOT do: send anything off-site. OD-9 chose a removable
    drive, and T-038's own assumption is explicit — the destination is
    supplied per call because a drive's mount point is not stable across
    sessions — so an unattended tick has no destination it could safely
    assume. What it CAN do unattended is the local export (no drive needed)
    and a staleness check against the audit log's own send-offsite history,
    which is DR-024's own revisit_if instruction for this task. A forgotten
    rotation becomes VISIBLE (escalated, C-27's pattern), not fixed by magic.
    """
    at = now()
    local_path = _local_snapshot_path(ctx)
    local_result: dict[str, Any]
    try:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        artefact = backup.build(ctx.conn)
        local_path.write_text(backup.dumps(artefact), encoding="utf-8")
        written = json.loads(local_path.read_text(encoding="utf-8"))
        verified = backup.verify(written)
        if not verified["integrity_verified"]:
            raise IntegrityError(
                f"local backup snapshot at '{local_path}' failed integrity "
                "verification on read-back; the write is not trustworthy",
                destination=str(local_path),
            )
        local_result = {
            "ok": True,
            "written_to": str(local_path),
            "created_at": artefact["created_at"],
            "integrity_hash": artefact["integrity_hash"],
        }
    except Exception as exc:  # noqa: BLE001 - a scheduled job's own failure must not vanish
        # C-27's pattern, applied here: the scheduler ran and something it
        # depends on broke. Recorded with its own targeted audit entry so the
        # failure is visible in `audit`/`backup-status` even though the tick
        # AS A WHOLE still returns normally below (mirrors scheduling.tick(),
        # which marks individual missed posts without raising itself).
        record(
            ctx,
            "backup-tick",
            outcome="failed",
            detail=f"LOCAL EXPORT FAILED — {type(exc).__name__}: {exc}"[:500],
            entity_type="backup",
        )
        local_result = {"ok": False, "error": type(exc).__name__, "message": str(exc)[:500]}

    freshness = _freshness(ctx, at)
    # The local half is already covered by local_result above (if the write
    # just above failed, _freshness will independently see a missing/overdue
    # local snapshot too — recomputed, not copied, so the two cannot disagree).
    if freshness["offsite"]["overdue"]:
        last = freshness["offsite"]["last_sent_at"]
        record(
            ctx,
            "backup-tick",
            outcome="failed",
            detail=(
                "OFFSITE BACKUP OVERDUE — last successful send-offsite was "
                f"{last or 'never'}, exceeding the "
                f"{freshness['offsite']['overdue_threshold_days']}-day threshold; "
                "plug in the off-site drive and run send-offsite"
            ),
            entity_type="backup",
        )

    # `freshness["local_export"]` and `local_result` are NOT merged by a bare
    # `**freshness` spread here — both use the key "local_export", and the
    # later one in a dict literal silently wins, which would drop `ok`/
    # `written_to`/`error` from the report entirely. Merged explicitly instead,
    # with this run's own outcome (`local_result`) taking precedence over the
    # freshness re-read for any field both compute.
    local_report = {**freshness["local_export"], **local_result}
    return {
        "ok": True,
        "at": at.isoformat(),
        "local_export": local_report,
        "offsite": freshness["offsite"],
        "needs_attention": int(not local_result["ok"]) + int(freshness["offsite"]["overdue"]),
    }


@register(
    "backup-status",
    "Report backup freshness: local export age and off-site transport age, and whether either is overdue.",
)
def backup_status(ctx: Context) -> dict[str, Any]:
    """Read-only, agent authority — the half of T-039 that answers 'is it working'.

    A scheduled job whose only output is a side effect cannot be checked
    without reading the audit log by hand. This is that check, made cheap and
    frequent (schedule-status's own reasoning, T-018), and it is what a UI
    badge or a health check calls without needing operator authority.
    """
    at = now()
    freshness = _freshness(ctx, at)
    return {
        "ok": True,
        "at": at.isoformat(),
        **freshness,
        "needs_attention": int(freshness["local_export"]["overdue"])
        + int(freshness["offsite"]["overdue"]),
    }
