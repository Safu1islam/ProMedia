"""The operation registry — DR-002.

Every capability is registered here exactly once. Both surfaces are projections
of this dict: the CLI generates a subcommand per operation, the web app
generates a route per operation. Neither contains business logic, so a
capability reachable from one surface and not the other is not expressible
(F-1, S4). ``tests/test_parity.py`` asserts that property.

Authority (F-2) is a property of the operation, checked here in the operation
layer. Putting it in the adapters would mean enforcing it twice, and the second
copy is the one that eventually drifts.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Callable

from ..config import Config
from ..errors import Forbidden, ProMediaError, ValidationError
from .principal import Principal

Handler = Callable[..., Any]


@dataclass
class Context:
    """Everything a handler is allowed to reach."""

    config: Config
    conn: sqlite3.Connection
    principal: Principal
    agent_id: str = "claude-code"
    model: str = "claude-opus-5"


@dataclass(frozen=True)
class Param:
    name: str
    type: str = "str"  # str | int | float | bool | json
    required: bool = True
    default: Any = None
    help: str = ""

    def coerce(self, raw: Any) -> Any:
        """Convert a surface-supplied value to the declared type.

        Both surfaces deliver strings (argv, form fields), so coercion lives
        here rather than being implemented twice.
        """
        if raw is None:
            return None
        if self.type == "str":
            return str(raw)
        if self.type == "int":
            try:
                return int(raw)
            except (TypeError, ValueError):
                raise ValidationError(f"parameter '{self.name}' must be an integer", parameter=self.name, got=str(raw))
        if self.type == "float":
            try:
                return float(raw)
            except (TypeError, ValueError):
                raise ValidationError(f"parameter '{self.name}' must be a number", parameter=self.name, got=str(raw))
        if self.type == "bool":
            if isinstance(raw, bool):
                return raw
            return str(raw).strip().lower() in {"1", "true", "yes", "on"}
        if self.type == "json":
            if isinstance(raw, (dict, list)):
                return raw
            try:
                return json.loads(raw)
            except (TypeError, ValueError) as exc:
                raise ValidationError(
                    f"parameter '{self.name}' must be valid JSON: {exc}", parameter=self.name
                ) from exc
        raise ValidationError(f"unknown parameter type '{self.type}'", parameter=self.name)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "required": self.required,
            "default": self.default,
            "help": self.help,
        }


@dataclass(frozen=True)
class Operation:
    name: str
    summary: str
    handler: Handler
    params: tuple[Param, ...] = ()
    authority: str = "agent"  # 'agent' = either principal; 'operator' = operator only
    mutates: bool = False
    entity: str | None = None
    danger: str | None = None  # shown on the approval surface before the control

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "summary": self.summary,
            "authority": self.authority,
            "mutates": self.mutates,
            "entity": self.entity,
            "danger": self.danger,
            "params": [p.to_dict() for p in self.params],
        }


OPERATIONS: dict[str, Operation] = {}


def register(
    name: str,
    summary: str,
    *,
    params: tuple[Param, ...] = (),
    authority: str = "agent",
    mutates: bool = False,
    entity: str | None = None,
    danger: str | None = None,
) -> Callable[[Handler], Handler]:
    """Register a capability. Duplicate names are a hard error at import time.

    Silent overwrite is the failure this guards against: two modules claiming
    the same operation name would leave one implementation unreachable while
    both surfaces still advertised it.
    """
    if authority not in {"agent", "operator"}:
        raise ValueError(f"unknown authority '{authority}' for operation '{name}'")

    def decorate(fn: Handler) -> Handler:
        if name in OPERATIONS:
            raise ValueError(
                f"operation '{name}' is already registered by "
                f"{OPERATIONS[name].handler.__module__}"
            )
        OPERATIONS[name] = Operation(
            name=name,
            summary=summary,
            handler=fn,
            params=params,
            authority=authority,
            mutates=mutates,
            entity=entity,
            danger=danger,
        )
        return fn

    return decorate


def load_operations() -> dict[str, Operation]:
    """Import every operation module, then return the registry."""
    from . import ops  # noqa: F401  (import triggers registration)

    return OPERATIONS


def validate(op: Operation, raw: dict[str, Any]) -> dict[str, Any]:
    known = {p.name for p in op.params}
    unexpected = set(raw) - known
    if unexpected:
        raise ValidationError(
            f"unexpected parameter(s): {', '.join(sorted(unexpected))}",
            unexpected=sorted(unexpected),
            expected=sorted(known),
        )
    resolved: dict[str, Any] = {}
    for p in op.params:
        value = raw.get(p.name)
        if value is None or value == "":
            if p.required:
                raise ValidationError(
                    f"missing required parameter '{p.name}'", parameter=p.name, expected_type=p.type
                )
            resolved[p.name] = p.default
        else:
            resolved[p.name] = p.coerce(value)
    return resolved


def invoke(ctx: Context, name: str, raw_params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run an operation. The single entry point both surfaces use."""
    from .audit import record  # local import keeps CLI cold start light

    registry = load_operations()
    op = registry.get(name)
    if op is None:
        raise ValidationError(f"unknown operation '{name}'", operation=name, known=sorted(registry))

    # Authority is checked BEFORE parameter validation so a forbidden call
    # cannot be probed for parameter shape, and before any side effect.
    if op.authority == "operator" and not ctx.principal.is_operator:
        record(ctx, op.name, outcome="denied", detail="operator authority required")
        raise Forbidden(
            f"operation '{op.name}' requires operator authority",
            operation=op.name,
            principal=ctx.principal.kind,
            remedy="approve in the ProMedia UI, or supply the operator token",
        )

    params = validate(op, raw_params or {})
    audited = op.authority == "operator" or op.mutates
    try:
        result = op.handler(ctx, **params)
    except ProMediaError as exc:
        if audited:
            record(ctx, op.name, outcome="failed", detail=f"{exc.code}: {exc.message}",
                   entity_type=op.entity)
        raise
    except Exception as exc:  # noqa: BLE001 - deliberate catch-all, see below
        # Finding I1: only ProMediaError was audited, so an unexpected failure
        # (a constraint violation, say) left NO record of an authority-gated
        # attempt at all — contradicting DR-008's stated mitigation that every
        # such attempt is recorded. It also reached the surfaces as a raw
        # traceback or a bare HTTP 500.
        #
        # Finding N1: the exception TYPE is recorded, never str(exc). Arbitrary
        # exception text can carry a credential — an HTTP client will happily
        # put a full request URL in its error — and audit_log lives in the
        # database, which is the backup artefact DR-008 works to keep secrets
        # out of. The type is enough to diagnose; the message is not worth the
        # risk of persisting it.
        if audited:
            record(ctx, op.name, outcome="failed",
                   detail=f"unexpected {type(exc).__name__}", entity_type=op.entity)
        raise ProMediaError(
            f"operation '{op.name}' failed unexpectedly ({type(exc).__name__});"
            " see the server console for detail",
            operation=op.name,
            exception_type=type(exc).__name__,
        ) from exc
    if audited:
        record(ctx, op.name, outcome="allowed", detail=None,
               entity_type=op.entity, entity_id=_entity_id(result))
    return result if isinstance(result, dict) else {"result": result}


def _entity_id(result: Any) -> str | None:
    if isinstance(result, dict):
        for key in ("id", "asset_id", "post_id", "account_id", "provenance_id"):
            if isinstance(result.get(key), str):
                return result[key]
    return None
