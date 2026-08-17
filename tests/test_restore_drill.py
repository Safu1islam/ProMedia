"""T-040 — restore drill: prove recovery against a destroyed database.

The only evidence a backup regime works is having actually recovered from
it. This is deliberately a different exercise from T-037's own restore
tests, which prove the reader can parse what the writer wrote — a fair unit
test, but one that never destroys anything and always hands
`restore-permanent-set` a path the test remembers from the moment it was
written. Neither is true of a real incident. This module proves the harder
claim end to end:

* the artefact travels through the REAL off-site transport (`send-offsite`,
  T-038), landing on what stands in for OD-9's removable drive — not
  `export-permanent-set` called directly, which is a different, untested
  path for this specific claim;
* the working database is actually destroyed (the file is deleted, not
  merely "a fresh directory that happens to have no data in it" — the
  distinction matters because the latter would never notice a restore path
  that secretly depended on something still present on the source machine);
* the artefact used for recovery is located by reading the drive's own
  manifest, the way an operator standing in front of a drive with no
  ProMedia database on it would have to — never a path variable carried
  forward from the moment `send-offsite` was called.

AC-2 is why this drill is one reusable function (`_run_drill`) called twice
against two independent scratch environments, rather than one long test:
running the identical procedure a second time and getting the identical
result is the actual evidence that recovery is repeatable and needs no
operator improvisation, not a claim taken on faith from a single pass.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from promedia.core import backup, db
from promedia.core.principal import agent, operator
from promedia.core.registry import Context, invoke
from tests.conftest import attest, declaration_original, make_config

CANARY = "canary-credential-must-never-be-backed-up-9x7"


def _ctx(base: Path, name: str):
    cfg = make_config(base / name, **{"publishing.allow_simulation": True})
    conn = db.connect(cfg.db_path)
    db.apply_schema(conn)
    return cfg, Context(config=cfg, conn=conn, principal=operator("op"))


def _full_history(ctx, media_file: Path) -> dict[str, str]:
    """One of every permanent kind (T-037/T-038's own precedent), so the
    drill proves recovery of the whole permanent set, not a lucky subset."""
    account = invoke(
        ctx, "connect-account", {"platform": "x", "handle": "me", "secret": CANARY}
    )["account_id"]
    as_agent = Context(config=ctx.config, conn=ctx.conn, principal=agent("ag"))
    asset = invoke(
        as_agent, "ingest",
        {"source_path": str(media_file), "declaration": declaration_original()},
    )["asset_id"]
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


def _latest_offsite_artefact(offsite_dir: Path) -> Path:
    """Find the artefact via the drive's OWN manifest — the file a real
    operator would be standing in front of, with no ProMedia database to
    ask. Never a path this module happened to keep in a variable."""
    manifest = offsite_dir / "promedia-backup-manifest.jsonl"
    lines = [line for line in manifest.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert lines, "the off-site manifest is empty; send-offsite never ran"
    last_entry = json.loads(lines[-1])
    return offsite_dir / last_entry["artefact_file"]


def _run_drill(base: Path, media_file: Path, credential_store: Path, label: str) -> dict[str, Any]:
    """The whole procedure, start to finish, as one callable — this IS the
    'repeatable without operator improvisation' proof AC-2 asks for. Every
    step is a real registered operation (F-1); nothing here reaches into
    promedia/core/** directly except `backup.build` to compute the
    before/after row-count comparison, which is read-only and mirrors what
    T-036/T-037's own tests already do."""
    import os

    os.environ["PROMEDIA_CREDENTIAL_STORE"] = str(credential_store)

    offsite = base / f"{label}-offsite-drive"

    # 1. A real system, sent off-site for real.
    scfg, sctx = _ctx(base, f"{label}-source")
    ids = _full_history(sctx, media_file)
    invoke(sctx, "send-offsite", {"destination": str(offsite)})
    before_counts = backup.build(sctx.conn)["row_counts"]
    before_rights = invoke(sctx, "rights", {"asset_id": ids["asset"]})["verdict"]
    before_audit_count = len(invoke(sctx, "audit", {"limit": 500})["entries"])
    sctx.conn.close()

    # 2. Destroy the working database. Not a fresh directory that merely
    #    lacks data — the actual file this system used, deleted, so a
    #    restore path that secretly still depended on it cannot pass by
    #    accident.
    assert scfg.db_path.is_file(), "nothing to destroy would make this drill meaningless"
    shutil.rmtree(scfg.data_dir)
    assert not scfg.db_path.exists()

    # 3. Recover using ONLY the off-site artefact, located via the drive's
    #    own manifest.
    artefact_path = _latest_offsite_artefact(offsite)
    tcfg, tctx = _ctx(base, f"{label}-recovered")
    result = invoke(tctx, "restore-permanent-set", {"source": str(artefact_path)})

    assert result["ok"] is True
    after_counts = backup.build(tctx.conn)["row_counts"]
    for table, count in before_counts.items():
        if table in ("schema_version", "audit_log"):
            continue  # audit_log grows by the restore's own entry; checked separately below
        assert after_counts[table] == count, f"{table}: {after_counts[table]} rows, expected {count}"

    integrity = invoke(tctx, "verify-provenance", {"provenance_id": ids["provenance"]})
    assert integrity["integrity_verified"] is True, "F-8: evidence must still verify after recovery"

    assert invoke(tctx, "rights", {"asset_id": ids["asset"]})["verdict"] == before_rights

    restored_audit = invoke(tctx, "audit", {"limit": 500})["entries"]
    assert len(restored_audit) >= before_audit_count
    assert any(e["operation"] == "publish-post" for e in restored_audit)

    # AC-2: what the drill does NOT recover is stated in its own output, not
    # left for the operator to discover the hard way.
    assert result["media_restored"] is False
    row = tctx.conn.execute(
        "SELECT state, object_path FROM assets WHERE id = ?", (ids["asset"],)
    ).fetchone()
    assert row["state"] == "absent", "recovered media state must be honest, not 'stored'"
    assert row["object_path"] is None

    scope = invoke(tctx, "backup-scope", {})
    assert scope["media_included"] is False

    tctx.conn.close()
    return result


def test_restore_drill_recovers_from_the_offsite_artefact_alone_after_the_database_is_destroyed(
    tmp_path, media_file, monkeypatch
):
    monkeypatch.delenv("PROMEDIA_CREDENTIAL_STORE", raising=False)
    _run_drill(tmp_path, media_file, tmp_path / "creds-1.json", label="run1")


def test_the_drill_is_repeatable_without_operator_improvisation(tmp_path, media_file, monkeypatch):
    """AC-2. The identical procedure, run twice against two independent
    scratch environments, produces the identical outcome — proof this is a
    repeatable drill, not a script that happened to work once."""
    monkeypatch.delenv("PROMEDIA_CREDENTIAL_STORE", raising=False)

    first = _run_drill(tmp_path, media_file, tmp_path / "creds-a.json", label="a")
    second = _run_drill(tmp_path, media_file, tmp_path / "creds-b.json", label="b")

    assert first["media_restored"] is second["media_restored"] is False
    assert first["assets_marked_absent"] == second["assets_marked_absent"] == 1
