"""Runtime configuration.

Single source of every threshold, limit and switch in the system. Protocol 05
forbids hardcoding these anywhere else: modules read them from here, and the
values come from ``promedia.toml`` at runtime rather than from literals baked
in at import time.

Import cost matters — this module is on the CLI cold-start path (C-4), so it
uses only ``tomllib`` and ``pathlib`` from the standard library.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import ConfigurationError

CONFIG_FILENAME = "promedia.toml"
ENV_CONFIG_PATH = "PROMEDIA_CONFIG"
ENV_DATA_DIR = "PROMEDIA_DATA_DIR"

# The only place these numbers appear in the package. Overridden by promedia.toml.
DEFAULTS: dict[str, dict[str, Any]] = {
    "storage": {
        "ceiling_bytes": 107374182400,  # 100 GB — C-13/F-7
        "warn_fraction": 0.70,
        "refuse_fraction": 0.85,
        "derivative_multiplier": 0.5,  # A-3
        "reservation_ttl_seconds": 3600,
    },
    "rights": {
        "ruleset": "conservative",
        "ruleset_version": "1.0.0",
        "jurisdiction": "neutral",
    },
    "publishing": {
        "tolerance_seconds": 300,  # C-26
        "allow_simulation": False,  # DR-010 / F-001
    },
    "locks": {"ttl_minutes": 90},
    "web": {"host": "127.0.0.1", "port": 8765},
    # T-030 (O2, O3). Both were literals in the modules that used them, which
    # protocol 05 forbids for the same reason as any other limit: the value a
    # reader finds in configuration was not the value the code used.
    "database": {"busy_timeout_ms": 5000},
    "ingest": {"probe_timeout_seconds": 30},
}


def defaults() -> dict[str, dict[str, Any]]:
    """A fresh copy of DEFAULTS.

    T-030 (O4). ``load()`` used to hand out the module-level dict itself on the
    no-file path, so every Config built without a promedia.toml SHARED one
    mutable object with the module and with each other. Config is frozen, but
    ``values`` is a plain nested dict and freezing does not reach into it: one
    ``cfg.values["storage"]["ceiling_bytes"] = 1`` would have moved the ceiling
    for every subsequent load in the process, including the test suite's. The
    file path never had the bug — ``_deep_merge`` already copies.
    """
    return {section: dict(keys) for section, keys in DEFAULTS.items()}


@dataclass(frozen=True)
class Config:
    """Resolved configuration. Immutable once built."""

    values: dict[str, dict[str, Any]]
    data_dir: Path
    source: Path | None = None
    _cache: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    def get(self, section: str, key: str) -> Any:
        try:
            return self.values[section][key]
        except KeyError as exc:
            raise ConfigurationError(
                f"unknown configuration key {section}.{key}", section=section, key=key
            ) from exc

    # Derived values, so callers never recompute thresholds from the ceiling.
    @property
    def ceiling_bytes(self) -> int:
        return int(self.get("storage", "ceiling_bytes"))

    @property
    def warn_bytes(self) -> int:
        return int(self.ceiling_bytes * float(self.get("storage", "warn_fraction")))

    @property
    def refuse_bytes(self) -> int:
        return int(self.ceiling_bytes * float(self.get("storage", "refuse_fraction")))

    @property
    def derivative_multiplier(self) -> float:
        return float(self.get("storage", "derivative_multiplier"))

    @property
    def db_path(self) -> Path:
        return self.data_dir / "promedia.db"

    @property
    def object_root(self) -> Path:
        return self.data_dir / "media" / "objects"


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Project keys replace framework keys at the same path (same rule as AEF overrides)."""
    out = {k: dict(v) if isinstance(v, dict) else v for k, v in base.items()}
    for section, values in override.items():
        if isinstance(values, dict) and isinstance(out.get(section), dict):
            out[section].update(values)
        else:
            out[section] = values
    return out


def find_config_file(start: Path | None = None) -> Path | None:
    explicit = os.environ.get(ENV_CONFIG_PATH)
    if explicit:
        p = Path(explicit)
        if not p.is_file():
            raise ConfigurationError(f"{ENV_CONFIG_PATH} points at a missing file", path=str(p))
        return p
    here = (start or Path.cwd()).resolve()
    for candidate in [here, *here.parents]:
        f = candidate / CONFIG_FILENAME
        if f.is_file():
            return f
    return None


def default_data_dir() -> Path:
    """Application data lives outside the repository tree by default.

    Credentials never live here at all (DR-008) — see promedia.core.credentials.
    """
    override = os.environ.get(ENV_DATA_DIR)
    if override:
        return Path(override)
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/.local/share")
    return Path(base) / "ProMedia"


def load(start: Path | None = None) -> Config:
    """Load configuration. Absent file is not an error — defaults apply."""
    path = find_config_file(start)
    values = defaults()
    if path is not None:
        # Decoded here rather than handed to tomllib.load() because Notepad —
        # the default editor on the operator's platform — writes UTF-8 with a
        # BOM, and tomllib rejects it with an opaque "Invalid statement at line
        # 1". Refusing to start because of an invisible byte is not acceptable
        # behaviour for a config file a human is expected to edit.
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ConfigurationError(
                f"{path} is not valid UTF-8: {exc}", path=str(path)
            ) from exc
        try:
            values = _deep_merge(DEFAULTS, tomllib.loads(text))
        except tomllib.TOMLDecodeError as exc:
            raise ConfigurationError(f"{path} is not valid TOML: {exc}", path=str(path)) from exc
    return Config(values=values, data_dir=default_data_dir(), source=path)
