"""T-036 — exporting the permanent set (project.md 5.4).

The easy part of a backup is copying rows. These tests are about the three
things that are easy to get wrong and expensive to discover late:

* a credential riding along into an off-site artefact, defeating DR-008's whole
  reason for keeping secrets out of the database;
* provenance whose integrity no longer verifies after the round trip, which
  turns a backup of EVIDENCE into a backup of bytes (F-8);
* a table added to the schema years from now that silently falls outside every
  future backup, and is noticed during a restore.

The last one has no failing test today by construction — it is about a table
that does not exist yet — so it is tested by adding one.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from promedia.core import backup, db
from promedia.core.principal import agent, operator
from promedia.core.registry import Context, invoke
from promedia.errors import Forbidden, IntegrityError, NotFound, ProMediaError, ValidationError
from tests.conftest import attest, declaration_original, make_config

CANARY = "canary-credential-must-never-be-backed-up-9x7"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("PROMEDIA_CREDENTIAL_STORE", str(tmp_path / "creds.json"))
    cfg = make_config(tmp_path, **{"publishing.allow_simulation": True})
    conn = db.connect(cfg.db_path)
    db.apply_schema(conn)
    yield cfg, Context(config=cfg, conn=conn, principal=operator("op"))
    conn.close()


def _full_history(ctx, media_file):
    """One complete slice, so the export has every permanent kind in it."""
    account = invoke(
        ctx, "connect-account", {"platform": "x", "handle": "me", "secret": CANARY}
    )["account_id"]
    as_agent = Context(config=ctx.config, conn=ctx.conn, principal=agent("ag"))
    asset = invoke(
        as_agent, "ingest",
        {"source_path": str(media_file), "declaration": declaration_original()},
    )["asset_id"]
    # Real evidence, so the artefact contains every permanent kind rather than
    # only the ones a minimal happy path happens to create.
    invoke(
        ctx, "add-evidence",
        {"asset_id": asset, "kind": "ownership_confirmed",
         "body": "shot by the operator", "produced_by": "operator"},
    )
    attest(ctx, asset)
    prov = invoke(ctx, "seal-provenance", {"asset_id": asset})["provenance_id"]
    post = invoke(
        ctx, "queue-post", {"account_id": account, "asset_id": asset, "body": "hello"}
    )["post_id"]
    invoke(ctx, "approve-post", {"post_id": post})
    invoke(ctx, "publish-post", {"post_id": post})
    return {"account": account, "asset": asset, "provenance": prov, "post": post}


# --- AC-2: no secret rides along ----------------------------------------------


def test_no_credential_appears_anywhere_in_the_artefact(env, media_file):
    """The control DR-008 exists to provide, asserted with a canary.

    The whole point of keeping credentials out of the database is that they are
    absent from backup artefacts. An export that carried one would look
    completely normal, which is why this is asserted against the serialised
    bytes rather than by reasoning about which tables were selected.
    """
    cfg, ctx = env
    _full_history(ctx, media_file)

    text = backup.dumps(backup.build(ctx.conn))

    assert CANARY not in text, "a credential reached the backup artefact"
    assert "credential_ref" in text, "sanity: the account row IS in the artefact"


def test_the_operator_token_is_not_in_the_artefact(env, media_file):
    """It grants publish authority over every account, and it lives in the
    credential store rather than the database — so it must be absent for the
    same reason, and is the one most likely to be forgotten."""
    cfg, ctx = env
    from promedia.core.credentials import CredentialStore

    token = CredentialStore().ensure_operator_token()
    _full_history(ctx, media_file)

    assert token not in backup.dumps(backup.build(ctx.conn))


# --- AC-3: provenance survives the round trip ---------------------------------


def test_provenance_integrity_verifies_out_of_the_artefact(env, media_file):
    """F-8. A record whose hash no longer checks is not evidence.

    Recomputed from the artefact's own payload, with no reference to the
    database — which is the situation a restore is actually performed in.
    """
    cfg, ctx = env
    ids = _full_history(ctx, media_file)

    artefact = json.loads(backup.dumps(backup.build(ctx.conn)))
    records = artefact["payload"]["provenance_records"]
    assert len(records) == 1
    record = records[0]
    assert record["id"] == ids["provenance"]

    from promedia.core.provenance import _integrity_hash

    payload = json.loads(record["payload"])
    assert _integrity_hash(payload) == record["integrity_hash"], (
        "provenance integrity does not verify from the artefact alone"
    )


def test_the_evidence_chain_is_complete_in_the_artefact(env, media_file):
    """'Rights evidence' is three tables, and a partial chain is not evidence."""
    cfg, ctx = env
    _full_history(ctx, media_file)
    payload = backup.build(ctx.conn)["payload"]

    for table in ("rights_declarations", "evidence", "rights_verdicts"):
        assert payload[table], f"{table} is empty; the rights chain is incomplete"
    assert payload["approvals"], "the approval record is missing"
    assert payload["publications"], "the publication record is missing"
    assert payload["audit_log"], "the audit log is missing"


# --- AC-1 / AC-5: the table classification ------------------------------------


def test_every_schema_table_is_classified(env):
    """No table may be in neither set."""
    cfg, ctx = env
    classified = backup.classify_tables(ctx.conn)
    assert set(classified["permanent"]) == set(backup.PERMANENT_TABLES)
    assert set(classified["transient"]) == set(backup.TRANSIENT_TABLES)


def test_a_new_unclassified_table_is_refused(env):
    """AC-1's real subject: the table that does not exist yet.

    A future migration adds a table, nobody updates this module, and it falls
    out of every backup silently. Here it fails loudly instead — at backup time,
    which is years before the restore where it would otherwise be discovered.
    """
    cfg, ctx = env
    ctx.conn.execute("CREATE TABLE future_feature (id TEXT PRIMARY KEY)")

    with pytest.raises(ProMediaError) as excinfo:
        backup.classify_tables(ctx.conn)
    assert "future_feature" in str(excinfo.value)

    # And the export refuses too, rather than quietly omitting it.
    with pytest.raises(ProMediaError):
        backup.build(ctx.conn)


def test_locks_and_ledger_are_excluded_with_a_stated_reason(env, media_file):
    """AC-5. Restoring these would actively harm, so the exclusion is not a
    space saving and must not read as one."""
    cfg, ctx = env
    artefact = backup.build(ctx.conn)

    assert "entity_locks" not in artefact["payload"]
    assert "storage_ledger" not in artefact["payload"]
    assert "ingest_queue" not in artefact["payload"]
    for table in ("entity_locks", "storage_ledger", "ingest_queue"):
        assert len(artefact["excluded_tables"][table]) > 40, (
            f"{table} is excluded without a real reason recorded"
        )


def test_the_artefact_says_media_is_not_included(env, media_file):
    """The surprising fact, stated inside the artefact itself.

    Someone restoring this in five years will not have read the source. 'Where
    is my media' is the worst question to have to answer during a recovery.
    """
    cfg, ctx = env
    _full_history(ctx, media_file)
    note = backup.build(ctx.conn)["note"]
    assert "transient" in note.lower() and "not" in note.lower()
    assert invoke(ctx, "backup-scope", {})["media_included"] is False


# --- AC-4: integrity of the artefact ------------------------------------------


def test_a_tampered_artefact_is_detected(env, media_file):
    cfg, ctx = env
    _full_history(ctx, media_file)
    artefact = json.loads(backup.dumps(backup.build(ctx.conn)))

    assert backup.verify(artefact)["integrity_verified"] is True

    artefact["payload"]["audit_log"] = []  # the edit an attacker would want
    result = backup.verify(artefact)
    assert result["integrity_verified"] is False
    assert result["expected_hash"] != result["actual_hash"]


def test_verification_needs_nothing_but_the_artefact(env, media_file, tmp_path):
    """It will be verified off-site, where the database does not exist."""
    cfg, ctx = env
    _full_history(ctx, media_file)
    path = tmp_path / "out" / "backup.json"
    invoke(ctx, "export-permanent-set", {"destination": str(path)})

    artefact = json.loads(path.read_text(encoding="utf-8"))
    assert backup.verify(artefact)["integrity_verified"] is True


def test_two_exports_of_an_unchanged_database_are_identical(env, media_file):
    """Lets a caller detect 'nothing changed' without diffing row by row."""
    cfg, ctx = env
    _full_history(ctx, media_file)
    at = "2026-08-13T00:00:00+00:00"
    first = backup.build(ctx.conn, at=at)
    second = backup.build(ctx.conn, at=at)
    assert backup.dumps(first) == backup.dumps(second)


# --- the operations -----------------------------------------------------------


def test_export_writes_a_file_and_reports_what_it_wrote(env, media_file, tmp_path):
    cfg, ctx = env
    _full_history(ctx, media_file)
    path = tmp_path / "nested" / "dir" / "backup.json"

    result = invoke(ctx, "export-permanent-set", {"destination": str(path)})

    assert path.is_file() and result["written_to"] == str(path)
    assert result["bytes"] > 0
    assert result["row_counts"]["publications"] == 1
    assert result["integrity_hash"]


def test_an_agent_cannot_export_the_permanent_set(env, media_file):
    """Read-only, but operator authority — see test_registry for the reasoning."""
    cfg, ctx = env
    as_agent = Context(config=ctx.config, conn=ctx.conn, principal=agent("ag"))
    with pytest.raises(Forbidden):
        invoke(as_agent, "export-permanent-set", {})


def test_an_agent_may_verify_a_backup(env, media_file, tmp_path):
    """Verifying must be cheap and frequent, so it is not gated."""
    cfg, ctx = env
    path = tmp_path / "backup.json"
    invoke(ctx, "export-permanent-set", {"destination": str(path)})

    as_agent = Context(config=ctx.config, conn=ctx.conn, principal=agent("ag"))
    assert invoke(as_agent, "verify-backup", {"source": str(path)})["integrity_verified"] is True


def test_verifying_a_missing_or_bogus_artefact_is_refused(env, tmp_path):
    cfg, ctx = env
    with pytest.raises(NotFound):
        invoke(ctx, "verify-backup", {"source": str(tmp_path / "nope.json")})

    junk = tmp_path / "junk.json"
    junk.write_text("this is not json", encoding="utf-8")
    with pytest.raises(ValidationError):
        invoke(ctx, "verify-backup", {"source": str(junk)})


def test_exporting_onto_a_directory_is_refused(env, tmp_path):
    cfg, ctx = env
    with pytest.raises(ValidationError):
        invoke(ctx, "export-permanent-set", {"destination": str(tmp_path)})


# --- send-offsite (T-038, OD-9: external/removable drive) --------------------


def test_send_offsite_writes_artefact_and_manifest(env, media_file, tmp_path):
    """AC-1: the artefact reaches the destination, and what/when/hash is recorded.

    tmp_path stands in for the mount point of an external drive — the code
    under test never distinguishes a removable drive from any other
    directory, so there is nothing OD-9-specific left to fake.
    """
    cfg, ctx = env
    _full_history(ctx, media_file)
    drive = tmp_path / "E" / "ProMediaBackups"
    drive.mkdir(parents=True)

    result = invoke(ctx, "send-offsite", {"destination": str(drive)})

    assert result["ok"] is True
    assert result["verified_on_destination"] is True
    sent = Path(result["sent_to"])
    assert sent.is_file() and sent.parent == drive

    manifest = Path(result["manifest"])
    assert manifest.is_file()
    lines = manifest.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["artefact_file"] == sent.name
    assert entry["integrity_hash"] == result["integrity_hash"]
    assert entry["sent_at"] == result["created_at"]
    assert entry["bytes"] == result["bytes"] > 0


def test_send_offsite_creates_the_destination_directory(env, tmp_path):
    """A fresh drive with no ProMediaBackups folder yet is not an error."""
    cfg, ctx = env
    drive = tmp_path / "F" / "not-yet-created"

    result = invoke(ctx, "send-offsite", {"destination": str(drive)})

    assert drive.is_dir()
    assert Path(result["sent_to"]).is_file()


def test_send_offsite_copy_verifies_independently_of_the_database(env, media_file, tmp_path):
    """The point of off-site: the copy must verify with no database at all."""
    cfg, ctx = env
    _full_history(ctx, media_file)
    drive = tmp_path / "drive"

    result = invoke(ctx, "send-offsite", {"destination": str(drive)})

    artefact = json.loads(Path(result["sent_to"]).read_text(encoding="utf-8"))
    assert backup.verify(artefact)["integrity_verified"] is True


def test_send_offsite_raises_if_the_destination_copy_fails_verification(env, tmp_path, monkeypatch):
    """DR-024's threat model T2, the negative path.

    Every other test here exercises a correctly-written copy; this one
    proves the read-back-and-rehash check actually FIRES on a bad one,
    rather than trusting that it would, by making the destination read as
    corrupted and asserting the call refuses instead of reporting success.
    """
    cfg, ctx = env

    def corrupted(artefact):
        return {"integrity_verified": False, "expected_hash": "a", "actual_hash": "b"}

    monkeypatch.setattr(backup, "verify", corrupted)

    with pytest.raises(IntegrityError):
        invoke(ctx, "send-offsite", {"destination": str(tmp_path / "drive")})


def test_send_offsite_manifest_write_failure_is_a_clear_error(env, tmp_path, monkeypatch):
    """The manifest append gets the same OSError-to-NotFound treatment as

    the artefact write and the destination mkdir — a drive that disconnects
    in the narrow window between a verified artefact write and the manifest
    append must not surface a bare OSError.
    """
    cfg, ctx = env
    real_open = Path.open

    def flaky_open(self, *args, **kwargs):
        if self.name == "promedia-backup-manifest.jsonl":
            raise OSError("drive disconnected")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", flaky_open)

    with pytest.raises(NotFound):
        invoke(ctx, "send-offsite", {"destination": str(tmp_path / "drive")})


def test_send_offsite_appends_to_the_manifest_across_transports(env, media_file, tmp_path):
    cfg, ctx = env
    drive = tmp_path / "drive"

    invoke(ctx, "send-offsite", {"destination": str(drive)})
    _full_history(ctx, media_file)
    invoke(ctx, "send-offsite", {"destination": str(drive)})

    manifest = drive / "promedia-backup-manifest.jsonl"
    lines = manifest.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    files = {json.loads(line)["artefact_file"] for line in lines}
    assert len(files) == 2, "each transport must write a distinct artefact file"


def test_send_offsite_refuses_a_destination_that_is_a_file(env, tmp_path):
    cfg, ctx = env
    not_a_dir = tmp_path / "backup.txt"
    not_a_dir.write_text("not a directory", encoding="utf-8")

    with pytest.raises(ValidationError):
        invoke(ctx, "send-offsite", {"destination": str(not_a_dir)})


def test_send_offsite_reports_a_clear_error_when_the_drive_is_unreachable(env, tmp_path):
    """Stands in for 'the removable drive is not plugged in': a destination

    that cannot be created because part of its path is a file, not a
    directory, is refused with a specific remedy rather than a bare OSError.
    """
    cfg, ctx = env
    blocking_file = tmp_path / "blocked"
    blocking_file.write_text("occupies the path a directory needs", encoding="utf-8")
    unreachable = blocking_file / "sub" / "dir"

    with pytest.raises(NotFound):
        invoke(ctx, "send-offsite", {"destination": str(unreachable)})


def test_an_agent_cannot_send_offsite(env, tmp_path):
    """Operator authority, same reasoning as export-permanent-set."""
    cfg, ctx = env
    as_agent = Context(config=ctx.config, conn=ctx.conn, principal=agent("ag"))
    with pytest.raises(Forbidden):
        invoke(as_agent, "send-offsite", {"destination": str(tmp_path / "drive")})


def test_send_offsite_does_not_carry_a_credential_either(env, media_file, tmp_path):
    """Same canary as the export path (DR-008) — send-offsite builds its own

    artefact via backup.build rather than reusing one handed to it, so this
    is not implied by the export test; it is a separate call to the same
    function and is checked separately for that reason.
    """
    cfg, ctx = env
    _full_history(ctx, media_file)
    drive = tmp_path / "drive"

    result = invoke(ctx, "send-offsite", {"destination": str(drive)})

    text = Path(result["sent_to"]).read_text(encoding="utf-8")
    assert CANARY not in text, "a credential reached the off-site artefact"
    manifest_text = Path(result["manifest"]).read_text(encoding="utf-8")
    assert CANARY not in manifest_text, "a credential reached the transport manifest"


def test_send_offsite_does_not_claim_encryption(env, tmp_path):
    """AC-2 is conditional on a third-party destination; OD-9 chose a drive.

    Asserted explicitly so a future change to the response shape cannot
    silently start claiming a protection this destination does not provide.
    """
    cfg, ctx = env
    result = invoke(ctx, "send-offsite", {"destination": str(tmp_path / "drive")})
    assert result["encrypted"] is False
    assert "third party" in result["note"]


def test_send_offsite_changes_nothing_except_recording_that_it_happened(env, media_file, tmp_path):
    cfg, ctx = env
    _full_history(ctx, media_file)
    before = backup.build(ctx.conn)["row_counts"]

    invoke(ctx, "send-offsite", {"destination": str(tmp_path / "drive")})
    after = backup.build(ctx.conn)["row_counts"]

    assert {t: n for t, n in after.items() if t != "audit_log"} == {
        t: n for t, n in before.items() if t != "audit_log"
    }
    entries = invoke(ctx, "audit", {"limit": 5})["entries"]
    assert any(e["operation"] == "send-offsite" for e in entries)
    assert db.list_locks(ctx.conn) == []


# --- backup-tick / backup-status (T-039) --------------------------------------


def test_backup_tick_writes_a_local_snapshot_and_reports_it_fresh(env, media_file):
    """AC-1: backup age is reportable, and a just-run tick is not overdue."""
    cfg, ctx = env
    _full_history(ctx, media_file)

    result = invoke(ctx, "backup-tick", {})

    assert result["ok"] is True
    assert result["local_export"]["ok"] is True
    local_path = Path(result["local_export"]["written_to"])
    assert local_path.is_file()
    assert local_path.parent == cfg.data_dir / "backups"

    written = json.loads(local_path.read_text(encoding="utf-8"))
    assert backup.verify(written)["integrity_verified"] is True

    assert result["local_export"]["overdue"] is False
    assert result["needs_attention"] >= 1, "offsite has never been sent, so it is overdue"
    assert result["offsite"]["overdue"] is True
    assert result["offsite"]["last_sent_at"] is None


def test_backup_tick_is_idempotent(env, media_file):
    """Safe to run twice — the local snapshot is overwritten, not accumulated."""
    cfg, ctx = env
    _full_history(ctx, media_file)

    invoke(ctx, "backup-tick", {})
    first = json.loads((cfg.data_dir / "backups" / "promedia-backup-local.json").read_text())
    result = invoke(ctx, "backup-tick", {})

    backups_dir = cfg.data_dir / "backups"
    files = list(backups_dir.glob("*.json"))
    assert files == [backups_dir / "promedia-backup-local.json"], (
        "a second tick must not accumulate a second file"
    )
    second = json.loads(files[0].read_text())
    # audit_log itself grows with every tick (each invoke() call is audited,
    # T-038's precedent in test_send_offsite_appends_to_the_manifest...), so
    # it is excluded the same way test_send_offsite_changes_nothing... and
    # test_export_changes_nothing... already do below.
    assert {t: n for t, n in second["row_counts"].items() if t != "audit_log"} == {
        t: n for t, n in first["row_counts"].items() if t != "audit_log"
    }
    assert result["local_export"]["ok"] is True


def test_backup_tick_treats_a_recent_send_offsite_as_not_overdue(env, media_file, tmp_path):
    """AC-1's other half: off-site freshness is read from send-offsite's own
    audit trail, per DR-024's revisit note, not reinvented."""
    cfg, ctx = env
    invoke(ctx, "send-offsite", {"destination": str(tmp_path / "drive")})

    result = invoke(ctx, "backup-tick", {})

    assert result["offsite"]["overdue"] is False
    assert result["offsite"]["last_sent_at"] is not None
    assert result["offsite"]["age_days"] < 1


def test_backup_tick_escalates_offsite_overdue_like_a_missed_publish_window(env, media_file):
    """AC-2: escalated (C-27's pattern), not merely absent from a log."""
    cfg, ctx = env

    invoke(ctx, "backup-tick", {})

    entries = invoke(ctx, "audit", {"limit": 10})["entries"]
    escalations = [
        e for e in entries
        if e["operation"] == "backup-tick" and e["outcome"] == "failed"
        and "OFFSITE BACKUP OVERDUE" in (e["detail"] or "")
    ]
    assert escalations, "an overdue off-site backup must leave its own audit entry"
    assert escalations[0]["entity_type"] == "backup"


def test_backup_tick_does_not_escalate_offsite_once_it_is_fresh(env, media_file, tmp_path):
    cfg, ctx = env
    invoke(ctx, "send-offsite", {"destination": str(tmp_path / "drive")})

    invoke(ctx, "backup-tick", {})

    entries = invoke(ctx, "audit", {"limit": 10})["entries"]
    assert not any(
        e["operation"] == "backup-tick" and "OFFSITE BACKUP OVERDUE" in (e["detail"] or "")
        for e in entries
    )


def test_backup_tick_escalates_a_local_export_failure_instead_of_crashing(env, media_file, tmp_path):
    """AC-2, the other failure mode: the export mechanism itself breaks.

    A file occupies the path the local snapshot's directory needs — the same
    'drive unreachable' shape send-offsite's own test uses, applied to the
    local path. The tick must report the failure, not raise past the caller,
    matching scheduling.tick()'s own per-post catch.
    """
    cfg, ctx = env
    (cfg.data_dir).mkdir(parents=True, exist_ok=True)
    (cfg.data_dir / "backups").write_text("occupies the path a directory needs", encoding="utf-8")

    result = invoke(ctx, "backup-tick", {})

    assert result["ok"] is True, "the tick itself must not raise"
    assert result["local_export"]["ok"] is False
    assert result["needs_attention"] >= 1

    entries = invoke(ctx, "audit", {"limit": 10})["entries"]
    assert any(
        e["operation"] == "backup-tick" and e["outcome"] == "failed"
        and "LOCAL EXPORT FAILED" in (e["detail"] or "")
        for e in entries
    )


def test_an_agent_cannot_run_backup_tick(env, tmp_path):
    """Operator authority, same reasoning as export-permanent-set/send-offsite:
    it writes the whole permanent set to a file, even at a fixed path."""
    cfg, ctx = env
    as_agent = Context(config=ctx.config, conn=ctx.conn, principal=agent("ag"))
    with pytest.raises(Forbidden):
        invoke(as_agent, "backup-tick", {})


def test_an_agent_may_read_backup_status(env, media_file):
    """Read-only staleness check must be cheap and frequent, like schedule-status."""
    cfg, ctx = env
    invoke(ctx, "backup-tick", {})

    as_agent = Context(config=ctx.config, conn=ctx.conn, principal=agent("ag"))
    result = invoke(as_agent, "backup-status", {})

    assert result["ok"] is True
    assert result["local_export"]["overdue"] is False
    assert result["offsite"]["overdue"] is True  # never sent in this test


def test_backup_status_never_written_reports_overdue_and_writes_nothing(env, media_file):
    """AC-1: staleness is visible even before the first tick has ever run —
    and reading it must not itself create a snapshot or an audit entry."""
    cfg, ctx = env

    result = invoke(ctx, "backup-status", {})

    assert result["local_export"]["exists"] is False
    assert result["local_export"]["overdue"] is True
    assert result["offsite"]["overdue"] is True
    assert not (cfg.data_dir / "backups").exists()
    assert invoke(ctx, "audit", {"limit": 5})["entries"] == []


def test_backup_status_and_backup_tick_agree_on_freshness(env, media_file, tmp_path):
    """One implementation, not two (DR-002) — a status read must match what
    the tick that just ran reported, not a second, drifting computation."""
    cfg, ctx = env
    invoke(ctx, "send-offsite", {"destination": str(tmp_path / "drive")})
    tick_result = invoke(ctx, "backup-tick", {})

    status_result = invoke(ctx, "backup-status", {})

    assert status_result["local_export"]["overdue"] == tick_result["local_export"]["overdue"] is False
    assert status_result["offsite"] == tick_result["offsite"]


def test_backup_tick_changes_nothing_in_the_permanent_set_itself(env, media_file):
    cfg, ctx = env
    _full_history(ctx, media_file)
    before = backup.build(ctx.conn)["row_counts"]

    invoke(ctx, "backup-tick", {})
    after = backup.build(ctx.conn)["row_counts"]

    assert {t: n for t, n in after.items() if t != "audit_log"} == {
        t: n for t, n in before.items() if t != "audit_log"
    }
    assert db.list_locks(ctx.conn) == []


def test_export_changes_nothing_except_recording_that_it_happened(env, media_file):
    """A backup that changed the thing it backs up would be a poor backup.

    The one exception is the audit log, and it is not an exception worth
    removing: export-permanent-set is operator authority, so invoke() audits it
    like every other authority-gated call. An operation that writes the entire
    audit log to a file of the caller's choosing is exactly the kind that should
    leave a trace of having been used. This test originally asserted NOTHING
    changed and failed on that entry, which was the test being wrong rather than
    the code.
    """
    cfg, ctx = env
    _full_history(ctx, media_file)
    before = backup.build(ctx.conn)["row_counts"]

    invoke(ctx, "export-permanent-set", {})
    after = backup.build(ctx.conn)["row_counts"]

    assert {t: n for t, n in after.items() if t != "audit_log"} == {
        t: n for t, n in before.items() if t != "audit_log"
    }
    assert after["audit_log"] == before["audit_log"] + 1
    entries = invoke(ctx, "audit", {"limit": 5})["entries"]
    assert any(e["operation"] == "export-permanent-set" for e in entries)
    assert db.list_locks(ctx.conn) == []
