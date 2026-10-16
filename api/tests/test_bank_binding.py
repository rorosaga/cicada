"""G183(d) — a write the app made in one bank never lands in another (`bank_binding`).

The app names the bank an operation started in (`X-Cicada-Bank`); a mutating request whose bank is not the active one
is refused before its handler runs. Without the header every route behaves exactly as before."""
from __future__ import annotations

import subprocess

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import bank_binding, markdown_parser


def _git(repo, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True).stdout


@pytest.fixture
def bank(tmp_path, monkeypatch):
    """The legacy `default` bank (no registry), committed clean, with one page and one inbox question."""
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    (memory / "inbox").mkdir()
    (memory / "episodes").mkdir()
    markdown_parser.write(memory / "entities" / "alpha-project.md",
                          {"name": "alpha-project", "type": "project", "status": "active", "confidence": 0.8},
                          "## Summary\nx\n")
    markdown_parser.write(memory / "inbox" / "inbox-001.md",
                          {"kind": "decay", "status": "pending", "entity_id": "alpha-project",
                           "entity_name": "alpha-project", "title": "Still tracking alpha-project?",
                           "created_date": "2026-10-01"},
                          "context")
    _git(memory, "init", "-q")
    _git(memory, "config", "user.email", "test@cicada.local")
    _git(memory, "config", "user.name", "Cicada Test")
    _git(memory, "add", "-A")
    _git(memory, "commit", "-q", "-m", "seed")
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    config.get_settings.cache_clear()
    yield memory
    config.get_settings.cache_clear()


def _snapshot(memory):
    files = sorted(p.relative_to(memory).as_posix() for p in memory.rglob("*") if p.is_file() and ".git" not in p.parts)
    return files, {f: (memory / f).read_bytes() for f in files}, _git(memory, "rev-parse", "HEAD")


#: A representative set of the app's bank-scoped writes: an answer, a page rewrite, a picture, a per-bank setting,
#: a local source batch, and the owner page.
WRITES = [
    ("post", "/inbox/inbox-001/resolve", {"json": {"action": "defer"}}),
    ("put", "/entities/alpha-project/decay", {"json": {"decayClass": "durable"}}),
    ("post", "/entities/alpha-project/picture", {"files": {"file": ("a.png", b"\x89PNG\r\n\x1a\n", "image/png")}}),
    ("put", "/sleep/schedule", {"json": {"enabled": True, "time": "03:00"}}),
    ("post", "/sources/folders/fld-1/sync", {"json": {"files": [], "deleted": []}}),
    ("put", "/settings/owner", {"json": {"name": "bob-example"}}),
    ("put", "/memory/decay-tuning", {"json": {"project": 1.5}}),
]


@pytest.mark.parametrize("method,path,kwargs", WRITES, ids=[w[1] for w in WRITES])
def test_a_write_named_for_another_bank_is_refused_and_writes_nothing(bank, method, path, kwargs):
    before = _snapshot(bank)
    resp = getattr(TestClient(main.app), method)(path, headers={bank_binding.HEADER: "other-bank"}, **kwargs)
    assert resp.status_code == 409, resp.text
    assert resp.json() == {"code": "bank_mismatch", "detail": bank_binding.DETAIL}
    assert _snapshot(bank) == before, "the handler never ran"


def test_a_write_named_for_the_active_bank_goes_through(bank):
    resp = TestClient(main.app).put("/entities/alpha-project/decay", json={"decayClass": "durable"},
                                    headers={bank_binding.HEADER: "default"})
    assert resp.status_code == 200, resp.text


def test_the_bank_name_is_percent_decoded(bank):
    resp = TestClient(main.app).post("/inbox/inbox-001/resolve", json={"action": "defer"},
                                     headers={bank_binding.HEADER: "defa%75lt"})
    assert resp.status_code == 200, resp.text


@pytest.mark.parametrize("method,path,kwargs", WRITES[:2], ids=[w[1] for w in WRITES[:2]])
def test_without_the_header_every_route_is_unchanged(bank, method, path, kwargs):
    resp = getattr(TestClient(main.app), method)(path, **kwargs)
    assert resp.status_code == 200, resp.text


def test_reads_are_never_checked(bank):
    resp = TestClient(main.app).get("/inbox", headers={bank_binding.HEADER: "other-bank"})
    assert resp.status_code == 200


def test_the_routes_that_change_the_bank_are_exempt(bank):
    c = TestClient(main.app)
    stale = {bank_binding.HEADER: "other-bank"}
    assert c.post("/banks", json={"name": "beta"}, headers=stale).status_code == 200
    assert c.post("/banks/beta/activate", headers=stale).status_code == 200
    assert c.post("/banks/default/activate", headers=stale).status_code == 200
    # The bank moved: the app's next write names the bank it now shows.
    assert c.put("/entities/alpha-project/decay", json={"decayClass": "volatile"},
                 headers={bank_binding.HEADER: "beta"}).json()["code"] == "bank_mismatch"


def test_every_exempt_route_exists():
    """The exemptions are route templates; a renamed route must not silently fall out of them."""
    templates = {(m, r.path) for r in main.app.routes for m in getattr(r, "methods", ()) or ()}
    assert bank_binding.EXEMPT <= templates


# --- Fix round 3: the request is pinned to one bank -------------------------------------------------------------


@pytest.fixture
def two_banks(tmp_path, monkeypatch):
    """Synthetic `default` and `beta` banks, each with a committed `bob-example` page (the reviewer's probe setup)."""
    from api.services import bank_registry, sleep_cycle

    root = tmp_path / "bank-root"
    root.mkdir()
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(root))
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    config.get_settings.cache_clear()
    bank_registry.scaffold_bank(root)
    bank_registry.create_bank(root, "beta", seed_owner=False)
    for p in (root, bank_registry.bank_dir(root, "beta")):
        markdown_parser.write(p / "entities" / "bob-example.md", {"name": "bob-example", "type": "person",
                                                                  "status": "active"}, "synthetic")
        _git(p, "add", "entities/bob-example.md")
        _git(p, "-c", "user.name=Cicada Test", "-c", "user.email=test@cicada.local", "commit", "-q", "-m", "page")
    monkeypatch.setattr(sleep_cycle, "is_writing", lambda: False)
    yield root
    config.get_settings.cache_clear()


PNG = (b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + (32).to_bytes(4, "big") * 2 + b"\x08\x02\x00\x00\x00"
       + b"\x00" * 20)


def test_a_switch_while_a_request_waits_on_its_lock_leaves_it_in_its_own_bank(two_banks, monkeypatch):
    """Re-review round 2, blocker 1, replayed against the real ASGI app: the upload passes the bank check, parks on the
    production picture lock, the active bank moves to beta, the lock is released. The upload, the page change and
    their commit all land in `default` — the bank the request started in — and nothing at all lands in beta."""
    import asyncio

    import httpx

    from api.routers import entities
    from api.services import bank_registry

    root = two_banks
    beta = bank_registry.bank_dir(root, "beta")
    import threading

    # A thread-safe signal (G183): the route's admitted body runs on the write-admission writer loop, not this one.
    entered = threading.Event()
    original_page = entities._entity_page

    def observed_page(settings, entity_id):
        result = original_page(settings, entity_id)
        entered.set()   # synchronous: signals arrival without adding an await
        return result

    monkeypatch.setattr(entities, "_entity_page", observed_page)

    async def run():
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            await entities._PICTURE_LOCK.acquire()
            beta_before = _snapshot(beta)
            head_default = _git(root, "rev-parse", "HEAD")
            upload = asyncio.create_task(c.post("/entities/bob-example/picture",
                                                headers={bank_binding.HEADER: "default"},
                                                files={"file": ("probe.png", PNG, "image/png")}))
            assert await asyncio.to_thread(entered.wait, 5)
            bank_registry.activate_bank(root, "beta")          # the switch, while the request waits on the lock
            entities._PICTURE_LOCK.release()
            response = await upload
            return response, beta_before, head_default

    response, beta_before, head_default = asyncio.run(run())
    assert response.status_code == 200, response.text
    assert (root / "assets" / "pictures" / "bob-example.png").exists(), "the upload landed in its own bank"
    assert not (beta / "assets" / "pictures" / "bob-example.png").exists()
    assert _snapshot(beta) == beta_before, "nothing at all was written into the other bank"
    assert _git(root, "rev-parse", "HEAD") != head_default, "and its commit is in its own bank's history"
    assert bank_registry.active_bank_name(root) == "beta", "the switch itself stands"


def test_a_pin_follows_the_request_into_threads_and_never_leaks(two_banks):
    import asyncio

    from api.services import bank_registry

    root = two_banks
    beta = bank_registry.bank_dir(root, "beta")

    async def request():
        bank_registry.pin_request_bank(root)
        bank_registry.activate_bank(root, "beta")
        from starlette.concurrency import run_in_threadpool
        return (await run_in_threadpool(bank_registry.resolve_active_bank_path, root),
                await asyncio.to_thread(bank_registry.active_bank_name, root))

    path, name = asyncio.run(request())
    assert path == root and name == "default", "pinned through anyio's and asyncio's threads"
    assert bank_registry.resolve_active_bank_path(root) == beta, "outside the request, the active bank as before"


@pytest.mark.parametrize("names", [("beta", "beta\u00a0"), ("\u00a0gamma", "gamma"),
                                   ("\u8bb0\u5fc6", "\u8bb0\u5fc6\u00a0"), ("caf\u00e9", "cafe")])
def test_bank_names_are_compared_exactly_as_decoded(two_banks, names):
    """Re-review round 2, should-fix 3: two banks may differ only by a Unicode space (leading or trailing) or an
    accent; the header is decoded once and never stripped or normalised, so one never passes for the other. (A
    precomposed and a decomposed accent are one directory on APFS, so they cannot be two banks.)"""
    from urllib.parse import quote

    from api.services import bank_registry

    root = two_banks
    active, other = names
    for name in names:
        if name not in bank_registry.load_registry(root)["banks"]:
            bank_registry.create_bank(root, name, seed_owner=False)
    bank_registry.activate_bank(root, active)
    c = TestClient(main.app)
    named = lambda n: {bank_binding.HEADER: quote(n, safe="-_.~")}  # noqa: E731
    assert c.put("/sleep/schedule", json={"mode": "manual"}, headers=named(active)).status_code == 200
    refused = c.put("/sleep/schedule", json={"mode": "manual"}, headers=named(other))
    assert refused.status_code == 409 and refused.json()["code"] == "bank_mismatch"


def test_a_header_that_is_not_utf8_matches_no_bank(two_banks):
    resp = TestClient(main.app).put("/sleep/schedule", json={"mode": "manual"}, headers={bank_binding.HEADER: "%FF"})
    assert resp.status_code == 409 and resp.json()["code"] == "bank_mismatch"


def test_an_import_into_a_named_bank_is_not_checked_but_one_into_the_active_bank_is(two_banks):
    """Should-fix 4: `?bank=` names its own target, so a stale origin cannot misfile it; without it the import writes
    into the active bank and stays checked."""
    from api.services import bank_registry

    bank_registry.activate_bank(two_banks, "beta")
    c = TestClient(main.app)
    stale = {bank_binding.HEADER: "default"}
    named = c.post("/intake/import?bank=default", headers=stale, files={"file": ("synthetic.json", b"[]", "application/json")})
    assert named.status_code != 409 or named.json().get("code") != "bank_mismatch", named.text
    active = c.post("/intake/import", headers=stale, files={"file": ("synthetic.json", b"[]", "application/json")})
    assert active.status_code == 409 and active.json()["code"] == "bank_mismatch"


def test_a_read_only_post_and_machine_global_writes_are_not_checked(two_banks):
    from api.services import bank_registry

    bank_registry.activate_bank(two_banks, "beta")
    c = TestClient(main.app)
    stale = {bank_binding.HEADER: "default"}
    sniff = c.post("/intake/sniff", headers=stale, files={"file": ("synthetic.json", b"[]", "application/json")})
    assert sniff.json().get("code") != "bank_mismatch", sniff.text
    prefs = c.put("/connections/claude-plan/prefs", headers=stale, json={"enabled": False})
    assert prefs.json().get("code") != "bank_mismatch", prefs.text


def test_a_malformed_body_is_parsed_before_the_bank_check(bank):
    """FastAPI parses the body before app dependencies run: malformed JSON is a 422 whatever the header says. A
    well-formed body with a stale bank is refused before schema validation and before the handler."""
    c = TestClient(main.app)
    stale = {bank_binding.HEADER: "other-bank", "Content-Type": "application/json"}
    assert c.put("/sleep/schedule", headers=stale, content=b"{").status_code == 422
    assert c.put("/sleep/schedule", headers=stale, content=b'{"mode": 7}').json()["code"] == "bank_mismatch"


# --- Targeted fix: the pin never leaks into unattended work ---------------------------------------------------------


def test_a_schedule_saved_in_a_request_fires_in_the_bank_active_when_it_fires(two_banks, monkeypatch):
    """The reviewer's reproduction, with the real `PUT /sleep/schedule`, the bank dependency, a real AsyncIOScheduler
    and `_run_if_idle` — only the cron is a date trigger 0.3 s away and Sleep's run is an observation stub. The schedule
    is saved while `default` is active, `beta` is activated before it fires, and the scheduled run resolves beta (the
    ACTIVE bank) with no pin: the request's pin never reached the scheduler's callbacks."""
    import asyncio
    from datetime import datetime, timedelta, timezone

    import httpx
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.date import DateTrigger

    from api.services import bank_registry, sleep_cycle, sleep_scheduler

    root = two_banks
    seen: list[dict] = []

    async def run():
        done = asyncio.Event()

        async def observed_run(settings, *args, **kwargs):
            pin = bank_registry._PINNED.get()
            seen.append({"path": settings.memory_path, "pin": pin.name if pin else None,
                         "user_triggered": kwargs.get("user_triggered")})
            done.set()

        monkeypatch.setattr(sleep_cycle, "run", observed_run)
        monkeypatch.setattr(sleep_scheduler, "CronTrigger",
                            lambda **kw: DateTrigger(run_date=datetime.now(timezone.utc) + timedelta(seconds=0.3)))
        scheduler = AsyncIOScheduler()
        scheduler.start()
        monkeypatch.setattr(main.app.state, "scheduler", scheduler, raising=False)
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as c:
                saved = await asyncio.create_task(c.put("/sleep/schedule", json={"mode": "daily", "hour": 4, "minute": 5},
                                                        headers={bank_binding.HEADER: "default"}))
                assert saved.status_code == 200, saved.text
                bank_registry.activate_bank(root, "beta")      # before the job fires
                await asyncio.wait_for(done.wait(), 5)
        finally:
            scheduler.shutdown(wait=False)

    asyncio.run(run())
    assert seen == [{"path": bank_registry.bank_dir(root, "beta"), "pin": None, "user_triggered": False}]


def test_every_scheduler_entry_point_drops_a_pin_it_was_handed(two_banks, monkeypatch):
    """A callback that already carries a request's context (scheduled before this fix, or by a path not yet wrapped)
    is cleaned at the job's own entry: each job resolves the bank active when it runs."""
    import asyncio

    from api.services import bank_registry, sleep_autocontinue, sleep_cycle, sleep_scheduler

    root = two_banks
    settings = config.get_settings()
    seen = []

    async def observed_run(settings, *args, **kwargs):
        seen.append(settings.memory_path)

    monkeypatch.setattr(sleep_cycle, "run", observed_run)
    monkeypatch.setattr(sleep_scheduler, "_paused_for_the_person", lambda mp: False)

    async def stale_job(job, *args):
        bank_registry.pin_request_bank(root)            # the request that scheduled it: `default`
        bank_registry.activate_bank(root, "beta")       # the switch, before it fires
        try:
            await job(*args)
            return bank_registry._PINNED.get()
        finally:
            bank_registry.activate_bank(root, "default")

    assert asyncio.run(stale_job(sleep_scheduler._run_if_idle, settings)) is None
    assert seen == [bank_registry.bank_dir(root, "beta")]
    assert asyncio.run(stale_job(sleep_scheduler._run_after_intake_if_settled, settings)) is None
    assert asyncio.run(stale_job(sleep_autocontinue._fire, str(root), "no-such-run")) is None


def test_registration_hands_the_scheduler_an_unpinned_context(two_banks):
    """What APScheduler captures is the context `add_job` is called in: `register_job` and the auto-continue arming
    call it in an unpinned copy, so neither the wakeup nor the timer carries a request's pin."""
    import asyncio

    from api.services import bank_registry, sleep_autocontinue, sleep_scheduler
    from api.services.sleep_scheduler import ScheduleConfig

    root = two_banks
    captured = []

    class Recorder:
        def remove_job(self, *_):
            pass

        def add_job(self, *args, **kwargs):
            captured.append(bank_registry._PINNED.get())

    async def request():
        bank_registry.pin_request_bank(root)
        sleep_scheduler.register_job(Recorder(), config.get_settings(), ScheduleConfig(mode="daily", hour=4, minute=5))
        sleep_autocontinue._add_job(Recorder(), str(root), 2_000_000_000, {"run_id": "r1", "paused_at_ts": 1})
        return bank_registry._PINNED.get()

    still = asyncio.run(request())
    assert captured == [None, None]
    assert still is not None and still.name == "default", "the request itself keeps its own pin"
