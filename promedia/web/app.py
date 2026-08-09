"""Operator UI (DR-004) — the authority surface for F-2 approvals.

A thin generic adapter over the same registry the CLI uses. Every operation
gets a route automatically, so the UI cannot fall behind the repo-callable
surface (F-1, S4).

Two deliberate properties:

  * Server-rendered, no JavaScript required. The approval flow is where a human
    authorises irreversible, legally consequential actions; it must work
    plainly and be keyboard reachable.
  * Authority is NOT decided here. The registry decides it. This module only
    supplies the principal, so a bug in a template cannot grant authority.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..config import Config, load as load_config
from ..errors import ProMediaError
from ..core import db
from ..core.credentials import CredentialStore
from ..core.principal import agent as agent_principal, resolve
from ..core.registry import Context, invoke, load_operations

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

# Session cookie carrying the operator token. Set from the ?token= parameter in
# the URL printed at startup, so the token is presented once rather than living
# in every link the operator might copy.
COOKIE_NAME = "promedia_operator"


def create_app(config: Config | None = None, *, store: CredentialStore | None = None) -> FastAPI:
    cfg = config or load_config()
    credential_store = store or CredentialStore()
    app = FastAPI(title="ProMedia", docs_url=None, redoc_url=None)
    operations = load_operations()

    def context(request: Request) -> Context:
        """Resolve the caller's authority from a presented token.

        The UI must NOT grant operator authority merely because a request
        reached the port. Localhost is not an authentication boundary: an agent
        can issue local HTTP requests as easily as the operator's browser can,
        and F-2 exists precisely to stop an agent publishing. Binding to
        127.0.0.1 keeps other machines out; it does nothing about other
        processes on this one.

        So the same token the CLI requires must be presented here, as a cookie
        (set once from the startup URL) or as a ?token= parameter. An agent that
        cannot read the credential store cannot authenticate — which is the same
        boundary the CLI has, rather than a weaker one.
        """
        expected = credential_store.operator_token()
        supplied = request.cookies.get(COOKIE_NAME) or request.query_params.get("token")
        principal = (
            resolve(supplied, expected, identifier="ui")
            if expected and supplied
            else agent_principal("ui")
        )
        conn = db.connect(cfg.db_path)
        db.apply_schema(conn)
        return Context(config=cfg, conn=conn, principal=principal)

    def run(request: Request, name: str, params: dict[str, Any]) -> dict[str, Any]:
        ctx = context(request)
        try:
            return invoke(ctx, name, params)
        finally:
            ctx.conn.close()

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> Any:
        # Exchange ?token=... for a cookie once, then drop it from the URL so it
        # does not linger in history or get copied into a shared link.
        supplied = request.query_params.get("token")
        if supplied:
            response = RedirectResponse(url="/", status_code=303)
            response.set_cookie(
                COOKIE_NAME, supplied, httponly=True, samesite="strict", path="/"
            )
            return response

        ctx = context(request)
        try:
            status = invoke(ctx, "status", {})
            posts = invoke(ctx, "list-posts", {})
            assets = invoke(ctx, "list-assets", {})
            accounts = invoke(ctx, "list-accounts", {})
        finally:
            ctx.conn.close()
        return TEMPLATES.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "status": status,
                "posts": posts["posts"],
                "assets": assets["assets"],
                "accounts": accounts["accounts"],
                "operations": sorted(operations.values(), key=lambda o: o.name),
            },
        )

    @app.get("/posts/{post_id}", response_class=HTMLResponse)
    def post_detail(request: Request, post_id: str) -> Any:
        try:
            detail = run(request, "post", {"post_id": post_id})
        except ProMediaError as exc:
            return TEMPLATES.TemplateResponse(
                request=request, name="error.html", context={"error": exc.to_dict()}, status_code=404
            )
        return TEMPLATES.TemplateResponse(
            request=request, name="post.html", context={"d": detail}
        )

    @app.post("/posts/{post_id}/approve")
    def approve(request: Request, post_id: str, decision: str = Form("approved")) -> Any:
        try:
            run(request, "approve-post", {"post_id": post_id, "decision": decision})
        except ProMediaError as exc:
            return TEMPLATES.TemplateResponse(
                request=request,
                name="error.html",
                context={"error": exc.to_dict()},
                status_code=403 if exc.code in {"FORBIDDEN", "RIGHTS_BLOCKED"} else 400,
            )
        return RedirectResponse(url=f"/posts/{post_id}", status_code=303)

    @app.post("/posts/{post_id}/publish")
    def publish(request: Request, post_id: str) -> Any:
        try:
            run(request, "publish-post", {"post_id": post_id})
        except ProMediaError as exc:
            return TEMPLATES.TemplateResponse(
                request=request,
                name="error.html",
                context={"error": exc.to_dict()},
                status_code=403 if exc.code in {"FORBIDDEN", "APPROVAL_REQUIRED", "RIGHTS_BLOCKED"} else 400,
            )
        return RedirectResponse(url=f"/posts/{post_id}", status_code=303)

    @app.post("/posts/{post_id}/release-claim")
    def release_claim(request: Request, post_id: str) -> Any:
        try:
            run(request, "release-publish-claim", {"post_id": post_id})
        except ProMediaError as exc:
            return TEMPLATES.TemplateResponse(
                request=request,
                name="error.html",
                context={"error": exc.to_dict()},
                status_code=403 if exc.code == "FORBIDDEN" else 400,
            )
        return RedirectResponse(url=f"/posts/{post_id}", status_code=303)

    # --- generic surface: one route per registered operation (S4) -------------

    @app.get("/ops", response_class=HTMLResponse)
    def ops_index(request: Request) -> Any:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="ops.html",
            context={"operations": sorted(operations.values(), key=lambda o: o.name)},
        )

    @app.get("/api/ops")
    def api_ops() -> Any:
        return JSONResponse({"ok": True, "operations": [op.to_dict() for op in operations.values()]})

    @app.api_route("/api/op/{name}", methods=["GET", "POST"])
    async def api_op(request: Request, name: str) -> Any:
        """Every operation, reachable over HTTP with identical semantics.

        This is what makes dual-surface parity structural rather than a
        convention someone has to remember.
        """
        params: dict[str, Any] = dict(request.query_params)
        if request.method == "POST":
            content_type = request.headers.get("content-type", "")
            if content_type.startswith("application/json"):
                try:
                    body = await request.json()
                    if isinstance(body, dict):
                        params.update(body)
                except ValueError:
                    pass
            else:
                form = await request.form()
                params.update({k: v for k, v in form.items()})
        try:
            result = run(request, name, params)
        except ProMediaError as exc:
            status = {"FORBIDDEN": 403, "APPROVAL_REQUIRED": 403, "NOT_FOUND": 404, "VALIDATION": 400}
            return JSONResponse(exc.to_dict(), status_code=status.get(exc.code, 400))
        return JSONResponse(result)

    return app


app = None  # built by run_server so importing this module stays cheap


def run_server() -> None:  # pragma: no cover - operator entry point
    import uvicorn

    cfg = load_config()
    store = CredentialStore()
    token = store.ensure_operator_token()
    host = str(cfg.get("web", "host"))
    port = int(cfg.get("web", "port"))

    # The token is printed, never embedded in the app. Opening this URL is what
    # grants operator authority to the browser session; without it the UI runs
    # with agent authority and refuses to approve or publish.
    print("\nProMedia UI. Open this URL to authenticate as the operator:", flush=True)
    print(f"  http://{host}:{port}/?token={token}\n", flush=True)

    # access_log=False is deliberate and is a security control, not a
    # convenience. Uvicorn's access log records full request lines including
    # query strings, so the ?token= exchange would write the operator token
    # into a log file — prohibited by NON-NEGOTIABLES list A ("printing,
    # committing, or logging a secret in any form").
    #
    # Nothing is lost that matters: promedia's own audit_log records principal,
    # operation, entity and outcome for every authority-gated attempt including
    # denials, which is the security-relevant record. An HTTP access log is not.
    uvicorn.run(create_app(cfg, store=store), host=host, port=port, access_log=False)
