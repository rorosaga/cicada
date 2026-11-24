"""An ETag walks the folders its keys name (a listing and a stat of every file, the inbox parsed) — 70 to 140 ms at
6,600 pages, 3,500 conversations and 700 inbox files on an idle Mac, seconds when the Mac is busy (G238, 2026-11-24).
Run by an `async def` handler it held the event loop, so `/healthz` and every other request waited behind it. A handler
on the loop asks `sync_service.etag_for_async`; the sync `etag_for` stays for code that is already on a thread."""
from __future__ import annotations

import ast
import asyncio
import threading
from pathlib import Path

import pytest

from _synthetic_bank import _bank

from api.services import sync_service

ROUTERS = Path(__file__).resolve().parents[1] / "routers"


def _etag_calls_on_the_loop() -> list[str]:
    """``file:line`` of every ``sync_service.etag_for(`` inside an ``async def`` of a router."""
    found = []
    for path in sorted(ROUTERS.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.AsyncFunctionDef):
                continue
            for node in ast.walk(fn):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "etag_for" and isinstance(node.func.value, ast.Name)
                        and node.func.value.id == "sync_service"):
                    found.append(f"{path.name}:{node.lineno} in {fn.name}")
    return found


def test_no_async_handler_computes_an_etag_on_the_loop():
    assert _etag_calls_on_the_loop() == [], (
        "a handler on the event loop must `await sync_service.etag_for_async(...)` (or run its helper in "
        "`run_in_threadpool`): the ETag's folder walk stalls every other request (G238)")


def test_the_async_etag_is_the_same_string_computed_on_a_worker_thread(tmp_path, monkeypatch):
    memory = _bank(tmp_path, git=False)
    seen: list[int] = []
    real = sync_service.etag_for

    def spy(*args, **kwargs):
        seen.append(threading.get_ident())
        return real(*args, **kwargs)

    monkeypatch.setattr(sync_service, "etag_for", spy)

    async def go() -> tuple[str, int]:
        return await sync_service.etag_for_async(memory, "entities", "episodes", "inbox", extra="x"), \
            threading.get_ident()

    got, loop_thread = asyncio.run(go())
    assert seen and seen[0] != loop_thread
    monkeypatch.setattr(sync_service, "etag_for", real)
    assert got == sync_service.etag_for(memory, "entities", "episodes", "inbox", extra="x")


@pytest.mark.parametrize("handler", ["sleep_episodes", "sleep_kept"])
def test_the_sleep_lists_read_their_rows_in_a_function_run_on_a_worker_thread(handler):
    """`GET /sleep/episodes` read a body per row (200 ms for 3,500 conversations, 2 MB) and `GET /sleep/kept` walked
    every header, both on the loop: their rows are built inside `build()`, awaited through `run_in_threadpool`."""
    from api.routers import sleep

    tree = ast.parse(Path(sleep.__file__).read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == handler)
    build = next(n for n in ast.walk(fn) if isinstance(n, ast.FunctionDef) and n.name == "build")
    inside = {id(n) for n in ast.walk(build)}
    rows = [n for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id == "_episode_items"]
    assert rows and all(id(n) in inside for n in rows)
    pooled = [n for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
              and n.func.id == "run_in_threadpool" and n.args and isinstance(n.args[0], ast.Name)
              and n.args[0].id == "build"]
    assert pooled
