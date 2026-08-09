"""Credential store (DR-008).

The decision that matters is separation, not the cipher: credentials live
outside the repository and outside the application database, so they are absent
from every backup, export, provenance artefact and agent-readable path.

v1 uses a file backend with a restrictive ACL. DPAPI is the intended production
backend (T-022) and is a swap behind this interface, not a rewrite. The
plaintext-at-rest gap is registered in .ai/state/fabrications.yaml rather than
silently accepted.
"""

from __future__ import annotations

import json
import os
import secrets
import stat
from pathlib import Path
from typing import Any

from ..errors import ConfigurationError, NotFound

ENV_STORE_PATH = "PROMEDIA_CREDENTIAL_STORE"
OPERATOR_TOKEN_KEY = "operator_token"
REDACTED = "<redacted>"


def default_store_path() -> Path:
    """Outside the repository, always.

    Placed under the user profile rather than the project so that cloning,
    zipping or backing up the repo cannot carry credentials with it.
    """
    override = os.environ.get(ENV_STORE_PATH)
    if override:
        return Path(override)
    base = os.environ.get("APPDATA") or os.path.expanduser("~/.config")
    return Path(base) / "ProMedia" / "credentials.json"


class CredentialStore:
    """Key/value secret store. Values are never returned to any surface."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_store_path()

    # --- internals ---
    def _read(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise ConfigurationError(
                f"credential store at {self.path} is not valid JSON", path=str(self.path)
            ) from exc

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        # Best effort on Windows; the real boundary is the user profile ACL.
        try:
            self.path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except OSError:  # pragma: no cover
            pass

    # --- public ---
    def put(self, ref: str, value: str) -> str:
        data = self._read()
        data[ref] = value
        self._write(data)
        return ref

    def get(self, ref: str) -> str:
        data = self._read()
        if ref not in data:
            raise NotFound(f"no credential stored under '{ref}'", ref=ref)
        return str(data[ref])

    def has(self, ref: str) -> bool:
        return ref in self._read()

    def delete(self, ref: str) -> bool:
        data = self._read()
        if ref not in data:
            return False
        del data[ref]
        self._write(data)
        return True

    def refs(self) -> list[str]:
        """Reference names only. Never values — this is what surfaces may show."""
        return sorted(self._read())

    # --- operator token (F-2) ---
    def operator_token(self) -> str | None:
        data = self._read()
        value = data.get(OPERATOR_TOKEN_KEY)
        return str(value) if value else None

    def ensure_operator_token(self) -> str:
        existing = self.operator_token()
        if existing:
            return existing
        token = secrets.token_urlsafe(32)
        self.put(OPERATOR_TOKEN_KEY, token)
        return token
