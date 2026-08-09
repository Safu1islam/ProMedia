"""Repo-callable surface (DR-005).

A thin, generic adapter: argv in, JSON out. Every subcommand is generated from
the registry, so an operation present in the UI is present here by
construction (F-1, S4). There is no business logic in this file and there must
never be — logic here would be logic the web surface does not have.

Cold start matters (C-4). Nothing at module scope imports the web framework,
and the registry is loaded lazily.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .config import load as load_config
from .errors import ProMediaError

ENV_OPERATOR_TOKEN = "PROMEDIA_OPERATOR_TOKEN"


def _build_parser(operations: dict[str, Any]) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="promedia",
        description=(
            "ProMedia — single-operator content production and publishing. "
            "Every capability here is the same implementation the UI calls."
        ),
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON (default for agents).")
    parser.add_argument(
        "--operator-token",
        default=None,
        help=f"Operator authority token. Also read from ${ENV_OPERATOR_TOKEN}.",
    )
    subparsers = parser.add_subparsers(dest="operation", metavar="OPERATION")
    for name, op in sorted(operations.items()):
        authority_note = "" if op.authority == "agent" else "  [OPERATOR AUTHORITY REQUIRED]"
        sub = subparsers.add_parser(name, help=f"{op.summary}{authority_note}")
        # Accepted before OR after the operation name. Agents write
        # `promedia status --json` far more naturally than the reverse, and a
        # usage error there costs a whole invocation to discover.
        sub.add_argument("--json", action="store_true", dest="json_after", default=False)
        sub.add_argument("--operator-token", dest="operator_token_after", default=None)
        for p in op.params:
            sub.add_argument(
                f"--{p.name.replace('_', '-')}",
                dest=p.name,
                required=False,  # required-ness is enforced in the operation layer
                default=None,
                help=f"{p.help} ({'required' if p.required else 'optional'}, {p.type})",
            )
    return parser


def _emit(payload: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, default=str))
        return
    if payload.get("ok") is False:
        print(f"{payload.get('error', 'ERROR')}: {payload.get('message', '')}", file=sys.stderr)
        detail = payload.get("detail") or {}
        for key, value in detail.items():
            print(f"  {key}: {value}", file=sys.stderr)
        return
    print(json.dumps(payload, indent=2, default=str))


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # Imported here, not at module scope, to keep cold start inside C-4.
    from .core import db
    from .core.credentials import CredentialStore
    from .core.principal import resolve
    from .core.registry import Context, invoke, load_operations

    operations = load_operations()
    parser = _build_parser(operations)
    args = parser.parse_args(argv)

    if not args.operation:
        parser.print_help()
        return 2

    as_json = bool(args.json or getattr(args, "json_after", False))
    config = load_config()

    try:
        import os

        supplied = (
            args.operator_token
            or getattr(args, "operator_token_after", None)
            or os.environ.get(ENV_OPERATOR_TOKEN)
        )
        expected = CredentialStore().operator_token()
        principal = resolve(supplied, expected, identifier="cli")

        conn = db.connect(config.db_path)
        try:
            if args.operation != "init":
                db.apply_schema(conn)  # idempotent; keeps a fresh checkout usable
            ctx = Context(config=config, conn=conn, principal=principal)
            op = operations[args.operation]
            raw = {p.name: getattr(args, p.name, None) for p in op.params}
            raw = {k: v for k, v in raw.items() if v is not None}
            result = invoke(ctx, args.operation, raw)
        finally:
            conn.close()
    except ProMediaError as exc:
        _emit(exc.to_dict(), as_json)
        return exc.exit_code
    except KeyboardInterrupt:  # pragma: no cover
        return 130

    _emit(result, as_json)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
