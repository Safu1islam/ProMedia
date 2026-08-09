"""Operation modules.

Importing this package registers every capability. Both surfaces call
``registry.load_operations()``, which imports this, so neither can see a
different set of operations than the other (F-1, S4).
"""

from . import accounts, assets, posts, provenance, rights, storage, system  # noqa: F401

__all__ = ["accounts", "assets", "posts", "provenance", "rights", "storage", "system"]
