"""G183(d) — a write is bound to the bank it was made in.

The app names the bank an operation started in on every mutating request (``X-Cicada-Bank``, percent-encoded). The
server moves its active bank before it answers a switch, and a long operation (a picture upload, a folder scan) can
outlive one, so a write the app sent for bank A can arrive while bank B is active. This one dependency, on every
route, compares the header with the active bank and answers ``409 {"code": "bank_mismatch", "detail": …}`` before the
handler runs — nothing is read or written. A request without the header (the hooks, the MCP server, curl, an older
app) behaves exactly as before. Exempt: the routes that themselves change the active bank, and bank CRUD that names
its bank in the path (or creates one), since none of them reads the active bank.
"""
from __future__ import annotations

from urllib.parse import unquote

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from api.config import Settings, get_settings
from api.services import bank_registry

HEADER = "X-Cicada-Bank"
CODE = "bank_mismatch"
DETAIL = "Memory switched before this was saved — nothing was written."
MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})
#: (method, route path template) — matched against the route FastAPI resolved, never a raw URL.
EXEMPT = frozenset({
    ("POST", "/banks"),
    ("POST", "/banks/{name}/activate"),
    ("POST", "/banks/{name}/duplicate"),
    ("POST", "/banks/{name}/rename"),
    ("POST", "/banks/{name}/import"),
    ("DELETE", "/banks/{name}"),
    ("POST", "/banks/demo"),
    ("POST", "/banks/leave-demo"),
})


class BankMismatch(HTTPException):
    def __init__(self) -> None:
        super().__init__(status_code=409, detail=DETAIL)


async def handler(_request: Request, exc: BankMismatch) -> JSONResponse:
    return JSONResponse(status_code=409, content={"code": CODE, "detail": exc.detail})


def claimed_bank(request: Request) -> str | None:
    raw = request.headers.get(HEADER)
    if raw is None:
        return None
    name = unquote(raw).strip()
    return name or None


async def require_same_bank(request: Request, settings: Settings = Depends(get_settings)) -> None:
    if request.method not in MUTATING:
        return
    claimed = claimed_bank(request)
    if claimed is None:
        return
    route = request.scope.get("route")
    if (request.method, getattr(route, "path", None)) in EXEMPT:
        return
    if claimed != bank_registry.active_bank_name(settings.memory_root):
        raise BankMismatch()
