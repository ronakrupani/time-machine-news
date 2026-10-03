"""ASGI app for the hosted server: the landing page at / and the MCP endpoint at /mcp.

Vercel resolves its entrypoint from the project root, so it loads this module
as src.time_machine_news.app (see [tool.vercel] in pyproject.toml). Locally:
    uvicorn time_machine_news.app:app --reload
"""

from __future__ import annotations

import html
from importlib.resources import files

from mcp.server.transport_security import TransportSecuritySettings
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response

from .server import mcp

LANDING_PAGE = files(__package__).joinpath("landing.html").read_text(encoding="utf-8")


def connector_url(request: Request) -> str:
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or "localhost"
    local = host.split(":")[0] in ("localhost", "127.0.0.1")
    scheme = request.headers.get("x-forwarded-proto") or ("http" if local else "https")
    return f"{scheme}://{host}/mcp"


@mcp.custom_route("/", methods=["GET"], include_in_schema=False)
async def home(request: Request) -> Response:
    page = LANDING_PAGE.replace("{{CONNECTOR_URL}}", html.escape(connector_url(request), quote=True))
    return HTMLResponse(page, headers={"Cache-Control": "public, max-age=300"})


@mcp.custom_route("/healthz", methods=["GET"], include_in_schema=False)
async def healthz(request: Request) -> Response:
    return JSONResponse({"ok": True})


# Stateless JSON responses suit serverless: any instance can answer any request and
# nothing is held open between calls. DNS rebinding protection is off because this
# is a public, read-only server reached through Vercel's domains, not a local one.
app = mcp.streamable_http_app(
    json_response=True,
    stateless_http=True,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["Mcp-Session-Id", "Mcp-Protocol-Version"],
)
