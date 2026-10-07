"""G183(d) — a request runs in one bank, and a write runs only in the bank it was made in.

Two things, in one dependency on every route:

1. **The pin.** The active bank is resolved ONCE, when the request starts, and pinned for the rest of the request
   (``bank_registry.pin_request_bank``, a ContextVar). ``Settings.memory_path``, ``bank_registry.active_bank_name`` and
   ``capture_bank`` answer the pinned bank, and the ContextVar follows the request into ``run_in_threadpool`` /
   ``asyncio.to_thread`` and into tasks it starts — so a switch while the request awaits a lock, a thread or its commit
   leaves the request finishing in its own bank, never writing part of its work into the other. Reads are pinned too,
   so a handler that reads then writes sees one bank. Not pinned: the routes that change the active bank (they must
   see the switch they make), bank CRUD that names its bank (a rename moves the active bank's directory) and the SSE
   stream (it follows switches for as long as it is open). Work that is not a
   request (the scheduler, Sleep's own runs) resolves the active bank as before.
2. **The check.** The app names the bank an operation started in on every mutating request (``X-Cicada-Bank``,
   percent-encoded UTF-8). A mutating request whose named bank is not the active one is answered
   ``409 {"code": "bank_mismatch", "detail": …}`` before its handler runs (after body parsing — FastAPI parses the
   body before app dependencies — but before schema validation and before anything is read or written). The name is
   compared exactly as decoded, never stripped or normalised: two banks may differ only by a Unicode space. A request
   without the header (the hooks, the MCP server, curl, an older app) is never checked.

Not checked (still pinned): routes that name their own target bank (bank CRUD in the path, an intake import with an
explicit ``?bank=``), a read-only POST (the intake sniff), and machine-global writes that touch no bank (an engine
connection's login, key and preferences live in ``~/.cicada``).
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
#: Routes that change the active bank: never checked, never pinned (they must see the switch they make).
SWITCHES = frozenset({
    ("POST", "/banks/{name}/activate"),
    ("POST", "/banks/demo"),
    ("POST", "/banks/leave-demo"),
})
#: Bank CRUD that names its bank in the path (or creates one): never reads the active bank, so neither checked nor
#: pinned — a rename of the active bank moves the very directory a pin would hold.
NAMED_TARGET = frozenset({
    ("POST", "/banks"),
    ("POST", "/banks/{name}/duplicate"),
    ("POST", "/banks/{name}/rename"),
    ("POST", "/banks/{name}/import"),
    ("DELETE", "/banks/{name}"),
})
#: A read-only POST, and machine-global writes that touch no bank.
NO_BANK_WRITE = frozenset({
    ("POST", "/intake/sniff"),
    ("POST", "/connections/{connection_id}/login"),
    ("POST", "/connections/{connection_id}/logout"),
    ("PUT", "/connections/{connection_id}/key"),
    ("DELETE", "/connections/{connection_id}/key"),
    ("PUT", "/connections/{connection_id}/prefs"),
})
#: Routes that write into ``?bank=`` when it is given, and into the active bank when it is not.
EXPLICIT_QUERY_TARGET = frozenset({("POST", "/intake/import")})
#: Long-lived GETs that must follow a switch while they stay open.
UNPINNED = frozenset({("GET", "/sync/events")})
#: Every exemption, for the test that keeps them pointing at real routes.
EXEMPT = SWITCHES | NAMED_TARGET | NO_BANK_WRITE | EXPLICIT_QUERY_TARGET


class BankMismatch(HTTPException):
    def __init__(self) -> None:
        super().__init__(status_code=409, detail=DETAIL)


async def handler(_request: Request, exc: BankMismatch) -> JSONResponse:
    return JSONResponse(status_code=409, content={"code": CODE, "detail": exc.detail})


class _Unreadable:
    """A header that is present but does not decode to a name: it can match no bank."""


def claimed_bank(request: Request) -> str | _Unreadable | None:
    raw = request.headers.get(HEADER)
    if raw is None or raw == "":
        return None
    try:
        return unquote(raw, encoding="utf-8", errors="strict")
    except UnicodeDecodeError:
        return _Unreadable()


def _checked(method: str, template: str | None, request: Request) -> bool:
    key = (method, template)
    if key in NAMED_TARGET or key in NO_BANK_WRITE:
        return False
    if key in EXPLICIT_QUERY_TARGET and request.query_params.get("bank"):
        return False
    return True


async def require_same_bank(request: Request, settings: Settings = Depends(get_settings)) -> None:
    method = request.method.upper()
    template = getattr(request.scope.get("route"), "path", None)
    if (method, template) in SWITCHES or (method, template) in NAMED_TARGET or (method, template) in UNPINNED:
        return
    root = getattr(settings, "memory_root", None)
    if root is None:   # a settings stand-in with no bank container (a test's): nothing to pin or compare
        return
    pin = bank_registry.pin_request_bank(root)
    if method not in MUTATING or not _checked(method, template, request):
        return
    claimed = claimed_bank(request)
    if claimed is not None and claimed != pin.name:
        raise BankMismatch()
