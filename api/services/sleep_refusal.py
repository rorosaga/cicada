"""The one shape of a "Sleep holds the pages" refusal (G177).

Every route that waits for Sleep's write window (``sleep_cycle.is_writing``) raises ``SleepWriting``; the handler
in ``api.main`` answers ``409 {"code": "sleep_writing", "detail": <the route's sentence>}``. The ``code`` is what a
client keys off — a ``detail`` is a sentence for the person, and other 409s (a claims block that will not parse, a
bank pinned by a run) can name a page whose id says "sleep". ``detail`` stays a plain string, so an older client and
any caller that reads ``HTTPException.detail`` see exactly what they did before.
"""
from __future__ import annotations

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

CODE = "sleep_writing"


class SleepWriting(HTTPException):
    def __init__(self, detail: str) -> None:
        super().__init__(status_code=409, detail=detail)


async def handler(_request: Request, exc: SleepWriting) -> JSONResponse:
    return JSONResponse(status_code=409, content={"code": CODE, "detail": exc.detail}, headers=exc.headers)
