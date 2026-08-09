"""Account connection (T-006).

Connecting an account is operator authority: it establishes the capability to
publish and, once real adapters exist, to spend. An agent may list accounts but
may not create one.

No operation here ever returns a credential value — only a reference (DR-008).
"""

from __future__ import annotations

from typing import Any

from ...errors import ValidationError
from .. import publishers
from ..credentials import REDACTED, CredentialStore
from ..db import iso, new_id
from ..registry import Context, Param, register


@register(
    "connect-account",
    "Connect a platform account and store its credential outside the repository.",
    params=(
        Param("platform", "str", help="Platform key: x or linkedin."),
        Param("handle", "str", help="Account handle as it appears on the platform."),
        Param("secret", "str", required=False, help="Credential value. Stored, never echoed."),
    ),
    authority="operator",
    mutates=True,
    entity="account",
    danger="Establishes publishing capability for this account.",
)
def connect_account(ctx: Context, platform: str, handle: str, secret: str | None = None) -> dict[str, Any]:
    key = platform.strip().lower()
    if key not in publishers.SUPPORTED_PLATFORMS:
        raise ValidationError(
            f"unsupported platform '{platform}'",
            parameter="platform",
            supported=list(publishers.SUPPORTED_PLATFORMS),
        )
    account_id = new_id("acct")
    credential_ref = f"{key}:{handle}"

    if secret:
        CredentialStore().put(credential_ref, secret)

    ctx.conn.execute(
        "INSERT OR REPLACE INTO accounts (id, platform, handle, credential_ref, status, connected_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (
            account_id,
            key,
            handle,
            credential_ref,
            "connected" if secret else "error",
            iso(),
        ),
    )
    return {
        "ok": True,
        "account_id": account_id,
        "platform": key,
        "handle": handle,
        "credential_ref": credential_ref,
        "credential_value": REDACTED,
        "status": "connected" if secret else "error",
        "note": (
            None if secret
            else "no credential supplied; account recorded but cannot publish (T-019)"
        ),
    }


@register("list-accounts", "List connected accounts. Never returns credential values.")
def list_accounts(ctx: Context) -> dict[str, Any]:
    rows = ctx.conn.execute("SELECT * FROM accounts ORDER BY connected_at DESC").fetchall()
    return {
        "ok": True,
        "count": len(rows),
        "accounts": [
            {
                "id": r["id"],
                "platform": r["platform"],
                "handle": r["handle"],
                "credential_ref": r["credential_ref"],
                "credential_value": REDACTED,
                "status": r["status"],
                "connected_at": r["connected_at"],
            }
            for r in rows
        ],
    }


@register(
    "platform-capabilities",
    "Report a platform's limits. Unverified limits read as UNKNOWN, never as a guess.",
    params=(Param("platform", "str"),),
)
def platform_capabilities(ctx: Context, platform: str) -> dict[str, Any]:
    from ..publishers.stub import capabilities_for_real_platform

    return {
        "ok": True,
        **capabilities_for_real_platform(platform.strip().lower()),
        "note": "Rate limits and pricing must be verified against live documentation (O-3).",
    }
