-- ProMedia schema, version 1. DR-003.
--
-- Two rules shape this file:
--   F-8  provenance_records and publications carry NO foreign key to assets.
--        They must remain valid and readable after retention deletes the media,
--        so they key on content hash and embed their payload.
--   C-19 entity_locks implements per-entity exclusive ownership with a visible
--        owner; SQLite's own locking is too coarse to express it.

CREATE TABLE IF NOT EXISTS schema_version (
    version    INTEGER NOT NULL,
    applied_at TEXT    NOT NULL
);

-- Connected platform accounts. credential_ref is a pointer into the credential
-- store, never a secret (DR-008).
CREATE TABLE IF NOT EXISTS accounts (
    id             TEXT PRIMARY KEY,
    platform       TEXT NOT NULL,
    handle         TEXT NOT NULL,
    credential_ref TEXT NOT NULL,
    status         TEXT NOT NULL CHECK (status IN ('connected', 'disconnected', 'error')),
    connected_at   TEXT NOT NULL,
    UNIQUE (platform, handle)
);

-- Content-addressed media. object_path is derived from content_hash and is
-- nullable because retention deletes the bytes while the row may linger until
-- the row itself is purged.
CREATE TABLE IF NOT EXISTS assets (
    id                TEXT PRIMARY KEY,
    content_hash      TEXT NOT NULL UNIQUE,
    byte_size         INTEGER NOT NULL CHECK (byte_size >= 0),
    original_filename TEXT NOT NULL,
    mime_type         TEXT,
    duration_seconds  REAL,
    probe_status      TEXT NOT NULL CHECK (probe_status IN ('ok', 'unavailable', 'failed')),
    derived_from      TEXT REFERENCES assets (id) ON DELETE SET NULL,
    state             TEXT NOT NULL CHECK (state IN ('stored', 'deleted')),
    ingested_at       TEXT NOT NULL,
    object_path       TEXT
);

-- Structured rights metadata supplied at ingest. Ingest without one is refused.
CREATE TABLE IF NOT EXISTS rights_declarations (
    id                   TEXT PRIMARY KEY,
    asset_id             TEXT NOT NULL REFERENCES assets (id) ON DELETE CASCADE,
    authorship           TEXT NOT NULL CHECK (authorship IN ('operator_original', 'third_party', 'unknown')),
    third_party_material TEXT NOT NULL,   -- JSON array
    source_url           TEXT,
    licence_grantor      TEXT,
    licence_scope        TEXT,
    licence_evidence_ref TEXT,
    public_domain_source TEXT,
    declared_by          TEXT NOT NULL,
    -- WHO attested matters as much as what was declared. A permitting rule may
    -- only fire on an operator-attested declaration: an agent asserting "this is
    -- the operator's own work" is a proposal, not an attestation.
    declared_by_kind     TEXT NOT NULL CHECK (declared_by_kind IN ('operator', 'agent')),
    declared_at          TEXT NOT NULL
);

-- Evidence. An LLM may write rows here and ONLY here (F-5): there is
-- deliberately no verdict column, so a model cannot express a decision.
CREATE TABLE IF NOT EXISTS evidence (
    id          TEXT PRIMARY KEY,
    asset_id    TEXT NOT NULL REFERENCES assets (id) ON DELETE CASCADE,
    kind        TEXT NOT NULL,
    body        TEXT NOT NULL,
    confidence  REAL CHECK (confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)),
    produced_by TEXT NOT NULL CHECK (produced_by IN ('operator', 'agent', 'model', 'system')),
    model_id    TEXT,
    created_at  TEXT NOT NULL
);

-- Verdicts are immutable once written. A ruleset change never rewrites history.
CREATE TABLE IF NOT EXISTS rights_verdicts (
    id              TEXT PRIMARY KEY,
    asset_id        TEXT NOT NULL REFERENCES assets (id) ON DELETE CASCADE,
    verdict         TEXT NOT NULL CHECK (verdict IN ('PERMITTED', 'BLOCKED', 'ESCALATE')),
    matched_rule    TEXT NOT NULL,
    reasons         TEXT NOT NULL,   -- JSON array
    ruleset         TEXT NOT NULL,
    ruleset_version TEXT NOT NULL,
    jurisdiction    TEXT NOT NULL,
    evidence_digest TEXT NOT NULL,
    decided_at      TEXT NOT NULL,
    decided_by      TEXT NOT NULL
);

-- F-8: NO foreign key to assets. Self-contained and survives media deletion.
CREATE TABLE IF NOT EXISTS provenance_records (
    id             TEXT PRIMARY KEY,
    asset_id       TEXT NOT NULL,
    content_hash   TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    payload        TEXT NOT NULL,   -- canonical JSON, self-contained
    integrity_hash TEXT NOT NULL,
    sealed_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS posts (
    id           TEXT PRIMARY KEY,
    account_id   TEXT NOT NULL REFERENCES accounts (id) ON DELETE RESTRICT,
    asset_id     TEXT NOT NULL REFERENCES assets (id) ON DELETE RESTRICT,
    body         TEXT NOT NULL,
    -- 'publishing' is the claim state: exactly one caller may hold it, which is
    -- what makes publish idempotent against the external call (see posts.py).
    status       TEXT NOT NULL CHECK (status IN ('queued', 'approved', 'publishing', 'published', 'missed', 'rejected')),
    scheduled_at TEXT,
    created_by   TEXT NOT NULL,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS approvals (
    id          TEXT PRIMARY KEY,
    post_id     TEXT NOT NULL REFERENCES posts (id) ON DELETE CASCADE,
    decision    TEXT NOT NULL CHECK (decision IN ('approved', 'rejected')),
    approved_by TEXT NOT NULL,
    approved_at TEXT NOT NULL,
    verdict_id  TEXT NOT NULL,
    UNIQUE (post_id)
);

-- F-8: no FK to posts. The published record outlives everything it describes.
-- UNIQUE(post_id) is what makes publish idempotent (T-011 AC-5).
CREATE TABLE IF NOT EXISTS publications (
    id               TEXT PRIMARY KEY,
    post_id          TEXT NOT NULL UNIQUE,
    account_id       TEXT NOT NULL,
    platform         TEXT NOT NULL,
    content_hash     TEXT NOT NULL,
    platform_post_id TEXT NOT NULL,
    permalink        TEXT,
    published_at     TEXT NOT NULL,
    simulated        INTEGER NOT NULL CHECK (simulated IN (0, 1)),
    provenance_id    TEXT NOT NULL
);

-- DR-006 reservation ledger. Source of truth for usage; the filesystem is not.
CREATE TABLE IF NOT EXISTS storage_ledger (
    id            TEXT PRIMARY KEY,
    asset_id      TEXT,
    kind          TEXT NOT NULL CHECK (kind IN ('master', 'derivative')),
    bytes         INTEGER NOT NULL CHECK (bytes >= 0),
    state         TEXT NOT NULL CHECK (state IN ('reserved', 'committed', 'released')),
    created_at    TEXT NOT NULL,
    expires_at    TEXT,
    released_at   TEXT
);

-- Ingest refused by admission control is queued, never discarded (F-7).
CREATE TABLE IF NOT EXISTS ingest_queue (
    id             TEXT PRIMARY KEY,
    source_path    TEXT NOT NULL,
    projected_bytes INTEGER NOT NULL,
    declaration    TEXT NOT NULL,   -- JSON, held until admission succeeds
    queued_at      TEXT NOT NULL,
    status         TEXT NOT NULL CHECK (status IN ('queued', 'admitted', 'cancelled')),
    shortfall_bytes INTEGER NOT NULL
);

-- C-19: exclusive per-entity ownership with a visible owner.
CREATE TABLE IF NOT EXISTS entity_locks (
    entity_type TEXT NOT NULL,
    entity_id   TEXT NOT NULL,
    task_id     TEXT NOT NULL,
    agent       TEXT NOT NULL,
    model       TEXT NOT NULL,
    acquired_at TEXT NOT NULL,
    expires_at  TEXT NOT NULL,
    PRIMARY KEY (entity_type, entity_id)
);

-- Append-only. Every authority-gated attempt, including denials.
CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    at          TEXT NOT NULL,
    principal   TEXT NOT NULL,
    principal_id TEXT NOT NULL,
    operation   TEXT NOT NULL,
    entity_type TEXT,
    entity_id   TEXT,
    outcome     TEXT NOT NULL CHECK (outcome IN ('allowed', 'denied', 'failed')),
    detail      TEXT
);

CREATE INDEX IF NOT EXISTS idx_assets_hash        ON assets (content_hash);
CREATE INDEX IF NOT EXISTS idx_verdicts_asset     ON rights_verdicts (asset_id, decided_at DESC);
CREATE INDEX IF NOT EXISTS idx_evidence_asset     ON evidence (asset_id);
CREATE INDEX IF NOT EXISTS idx_ledger_state       ON storage_ledger (state);
CREATE INDEX IF NOT EXISTS idx_posts_status       ON posts (status, scheduled_at);
CREATE INDEX IF NOT EXISTS idx_provenance_hash    ON provenance_records (content_hash);
CREATE INDEX IF NOT EXISTS idx_audit_at           ON audit_log (at DESC);
