"""Ruling 47a, G179 (2026-10-28) — Telegram chats on the person's own account, against a FAKE client only.

No test signs in to Telegram or opens a socket: :class:`FakePort` stands in for `telegram_port.TelethonPort`. Covers
the rails: nothing happens without a kept session; the sign-in steps (code, two-step password) keep the session 0600
outside every bank and never the number, code or password; a session file others can read is refused; credentials
(the person's own over the release build's, none → a sentence); one-to-one chats only, each with the person's dated
confirmation that the other person agreed (ruling 47a amendment, owner 2026-10-28) — a group never listed or staged,
a chat without consent never staged, unticking withdraws it; live events staged for ticked chats only and dropped
for the rest; who is who (a bot is an agent, Telegram says so); deletes that name only ids; reaction changes as Telegram's whole set; history on ask; the demo bank never written; disconnect logs out
at Telegram and forgets the file, even when the log-out fails; and the routes."""
from __future__ import annotations

import asyncio
import json
import os
import time

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import (bank_index, chat_live, episode_staging, markdown_parser, telegram_account, telegram_source,
                          turn_extras)
from api.services.telegram_port import PasswordNeeded, TelegramError, TgDialog, TgEvent, TgMessage

T0 = 1_788_000_000.0
FRIEND, BOT, GROUP, OTHER = 1001, 1002, -100777, 1003     # placeholder peer ids
ME, CAROL, DAVE, HELPER = 1, 2001, 2002, 2003


class FakePort:
    def __init__(self, api_id, api_hash, session):
        self.session = session or ""
        self.calls: list[str] = []
        self.handler = None
        self.history_rows: dict[int, list[TgMessage]] = {}
        self.authorized_ok = True
        self.fail_log_out = False
        self.two_step = False

    async def send_code(self, phone):
        self.calls.append("send_code")
        return "hash-1"

    async def sign_in(self, phone, code, code_hash):
        self.calls.append("sign_in")
        if self.two_step:
            raise PasswordNeeded("two-step")
        self.session = "SESSION-STRING-PLACEHOLDER"

    async def sign_in_password(self, password):
        self.calls.append("password")
        self.session = "SESSION-STRING-PLACEHOLDER"

    async def authorized(self):
        return self.authorized_ok

    def session_string(self):
        return self.session

    async def dialogs(self, limit):
        return [TgDialog(FRIEND, "Bob Example", False, bot=False, last=T0),
                TgDialog(BOT, "Helper Bot", False, bot=True, last=T0),
                TgDialog(GROUP, "Weekend crew", True, last=T0),
                TgDialog(OTHER, "Not ticked", False, bot=False, last=T0),
                TgDialog(-100999, "A channel", False, last=T0, broadcast=True)]

    async def history(self, chat, *, min_id=0, limit=None):
        for m in self.history_rows.get(chat, []):
            if m.id > min_id:
                yield m

    async def listen(self, handler):
        self.handler = handler
        await asyncio.Event().wait()

    async def log_out(self):
        self.calls.append("log_out")
        if self.fail_log_out:
            raise ConnectionError("network down")

    async def disconnect(self):
        self.calls.append("disconnect")


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv(telegram_account.ID_ENV, "12345")
    monkeypatch.setenv(telegram_account.HASH_ENV, "placeholder-hash")
    return tmp_path / "home"


@pytest.fixture
def bank(tmp_path, monkeypatch, home):
    memory = tmp_path / "memory"
    for sub in ("episodes", "entities", "sources"):
        (memory / sub).mkdir(parents=True)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    yield memory
    config.get_settings.cache_clear()


@pytest.fixture
def made():
    ports: list[FakePort] = []

    def factory(api_id, api_hash, session):
        port = FakePort(api_id, api_hash, session)
        ports.append(port)
        return port
    return ports, factory


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def msg(i, chat, text, *, out=False, sender=None, name="", bot=None, at=None, **kw):
    return TgMessage(id=i, chat=chat, date=at or T0 + i * 10, out=out, text=text, sender=sender, sender_name=name,
                     sender_bot=bot, **kw)


def tick(bank, chat, *, group=False, history=False, consent=True):
    cid = telegram_source.conversation_id(chat)
    chat_live.update_settings(bank, telegram_source.SPEC, {"id": cid, "group": group, "ticked": True},
                              now="2026-01-01T00:00:00+00:00")
    if consent:
        telegram_account.set_consent(cid, True, at="2026-10-28T20:00:00+00:00")
    if history:
        chat_live.update_settings(bank, telegram_source.SPEC, {"id": cid, "history": True})
    return cid


def episodes(bank):
    bank_index.invalidate()
    index, _ = episode_staging.scan(bank / "episodes")
    return {sid: markdown_parser.parse(e.path) for sid, e in sorted(index.items())
            if not e.fm.get("source_deleted_at")}


async def connected(made, *, two_step=False):
    ports, factory = made
    account = telegram_account.Account(factory)
    await account.send_code("+1 555 000 0000")
    ports[-1].two_step = two_step
    status = await account.submit_code("12 345")
    if two_step:
        assert status["state"] == "password"
        status = await account.submit_password("placeholder-password")
    assert status["state"] == "connected"
    await asyncio.sleep(0)
    return account, ports[-1]


def test_nothing_happens_without_a_kept_session(home, made):
    ports, factory = made
    account = telegram_account.Account(factory)
    run(account.resume())
    assert ports == [] and account.state == "off"
    assert not (home / "telegram").exists()


def test_sign_in_keeps_only_the_session_0600_outside_the_bank(home, bank, made):
    async def go():
        account, port = await connected(made, two_step=True)
        assert port.calls == ["send_code", "sign_in", "password"]
        await account.stop()
    run(go())
    path = home / "telegram" / "session"
    assert path.read_text().strip() == "SESSION-STRING-PLACEHOLDER"
    assert oct(path.stat().st_mode & 0o777) == "0o600" and oct((home / "telegram").stat().st_mode & 0o777) == "0o700"
    everything = "".join(p.read_text(errors="ignore") for p in home.rglob("*") if p.is_file())
    assert "555" not in everything and "placeholder-password" not in everything and "12345" not in everything
    assert not any("SESSION-STRING" in p.read_text(errors="ignore") for p in bank.rglob("*") if p.is_file())


def test_a_session_file_others_can_read_is_refused(home, made):
    telegram_account.save_session("SESSION-STRING-PLACEHOLDER")
    os.chmod(home / "telegram" / "session", 0o644)
    ports, factory = made
    account = telegram_account.Account(factory)
    run(account.resume())
    assert ports == [] and account.state == "ended" and "readable" in account.error


def test_credentials_the_persons_own_win_and_none_is_a_sentence(home, monkeypatch, tmp_path):
    assert telegram_account.credentials()[2] == "own"
    monkeypatch.delenv(telegram_account.ID_ENV)
    app_file = tmp_path / "telegram_app.json"
    monkeypatch.setattr(telegram_account, "APP_FILE", app_file)
    assert telegram_account.credentials() is None
    with pytest.raises(TelegramError, match="my.telegram.org"):
        telegram_account.Account(lambda *a: None)._make()
    app_file.write_text(json.dumps({"api_id": 777, "api_hash": "release-hash"}))
    assert telegram_account.credentials() == (777, "release-hash", "cicada")


def test_the_tick_list_offers_one_to_one_chats_only_and_shows_no_ids(home, bank, made):
    async def go():
        account, _ = await connected(made)
        rows = await account.chats()
        await account.stop()
        return rows
    rows = run(go())
    assert [r["name"] for r in rows] == ["Bob Example", "Helper Bot", "Not ticked"]   # no group, no channel
    assert all(chat_live.ID_RE.match(r["id"]) and str(FRIEND) not in r["id"] for r in rows)


def test_live_events_stage_ticked_consented_one_to_one_chats_only(home, bank, made):
    friend = tick(bank, FRIEND)
    bot = tick(bank, BOT)
    group = tick(bank, GROUP, group=True)              # even ticked and "consented" in the files, a group is never read
    other = tick(bank, OTHER, consent=False)           # ticked in the bank, but no confirmation kept

    async def go():
        account, _ = await connected(made)
        await account.chats()
        pending = {
            FRIEND: [TgEvent("new", FRIEND, msg(1, FRIEND, "Dinner Friday?", sender=FRIEND, name="Bob")),
                     TgEvent("new", FRIEND, msg(2, FRIEND, "Yes, at 8.", out=True, reply_to=1)),
                     TgEvent("new", FRIEND, msg(3, FRIEND, "joined", service=True))],
            BOT: [TgEvent("new", BOT, msg(1, BOT, "Remind me to call alpha-project.", out=True)),
                  TgEvent("new", BOT, msg(2, BOT, "Reminder set.", sender=BOT, name="Helper Bot", bot=True))],
            GROUP: [TgEvent("new", GROUP, msg(1, GROUP, "a group line, never stored", sender=DAVE,
                                               name="Dave Example", bot=False))],
            OTHER: [TgEvent("new", OTHER, msg(1, OTHER, "no consent, never stored", sender=OTHER))],
        }
        out = await account.flush(pending)
        await account.stop()
        return out
    out = run(go())
    assert set(out) == {friend, bot} and group not in out and other not in out
    eps = {p.frontmatter["conversation"]: p for p in episodes(bank).values()}
    assert set(eps) == {friend, bot}
    assert eps[friend].body.splitlines() == ["speaker:bob-example: Dinner Friday?", "user: Yes, at 8."]
    assert eps[friend].frontmatter["correspondent"] == {"name": "Bob Example", "kind": "person",
                                                        "decided_by": "source"}
    assert [e.get("reply_to") for e in turn_extras.by_offset(eps[friend].frontmatter).values()] == [0]
    assert eps[bot].body.splitlines() == ["user: Remind me to call alpha-project.", "assistant: Reminder set."]
    assert eps[bot].frontmatter["correspondent"]["kind"] == "agent"
    assert "never stored" not in "".join(p.read_text() for p in (bank / "episodes").glob("*.md"))
    assert eps[friend].frontmatter["origin"] == "telegram-chats"
    assert eps[friend].frontmatter["title"].startswith("Telegram with Bob Example")


def test_the_ingest_itself_refuses_a_group_and_a_chat_without_consent(home, bank):
    group = tick(bank, GROUP, group=True)
    with pytest.raises(telegram_source.NotOneToOne):
        telegram_source.ingest(bank, {"id": group, "chat": GROUP, "group": True}, [msg(1, GROUP, "x", sender=DAVE)])
    other = tick(bank, OTHER, consent=False)
    with pytest.raises(telegram_source.NoConsent):
        telegram_source.ingest(bank, {"id": other, "chat": OTHER}, [msg(1, OTHER, "x", sender=OTHER)])
    assert list((bank / "episodes").glob("*.md")) == []


@pytest.fixture
def live_account(made, monkeypatch):
    """The module's ACCOUNT, connected to the fake client, for the routes."""
    _, factory = made
    account = telegram_account.Account(factory)
    account.port, account.state = factory(1, "h", ""), "connected"
    monkeypatch.setattr(telegram_account, "ACCOUNT", account)
    return account


def test_consent_is_kept_dated_outside_the_bank_and_unticking_withdraws_it(home, bank, live_account):
    client = TestClient(main.app)
    cid = telegram_source.conversation_id(FRIEND)
    r = client.put("/sources/telegram/settings", json={"conversation": {"id": cid, "ticked": True}})
    assert r.status_code == 409 and "agreed" in r.json()["detail"]
    r = client.put("/sources/telegram/settings", json={"conversation": {"id": cid, "group": True, "ticked": True,
                                                                         "consent": True}})
    assert r.status_code == 422
    r = client.put("/sources/telegram/settings", json={"conversation": {"id": cid, "ticked": True, "consent": True}})
    assert r.status_code == 200, r.text
    path = home / "telegram" / "consents.json"
    kept = json.loads(path.read_text())
    assert list(kept) == [cid] and kept[cid]["at"].startswith("20")
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert not any("consent" in p.name for p in bank.rglob("*"))
    r = client.put("/sources/telegram/settings", json={"conversation": {"id": cid, "ticked": False}})
    assert r.status_code == 200 and json.loads(path.read_text()) == {}
    assert telegram_account.CONSENT_ASK.count("{name}") == 1 and "can't check" in telegram_account.CONSENT_ASK


# --- #504 review B4: one-to-one is decided from Telegram's own peer, never the client's `group` flag -----------------

def test_the_route_refuses_a_groups_id_even_flagged_one_to_one(home, bank, live_account):
    client = TestClient(main.app)
    group = telegram_source.conversation_id(GROUP)
    r = client.put("/sources/telegram/settings", json={"conversation": {"id": group, "group": False, "ticked": True,
                                                                         "consent": True}})
    assert r.status_code == 422 and "one-to-one" in r.json()["detail"]
    assert group not in telegram_account.consents()
    assert not chat_live.ticked_ids(bank, telegram_source.SPEC)
    r = client.put("/sources/telegram/settings", json={"conversation": {"id": "cd" * 12, "ticked": True,
                                                                         "consent": True}})
    assert r.status_code == 422, "an id Telegram does not list is refused too"


def test_the_flush_never_stages_a_groups_update_whatever_the_files_say(home, bank, made):
    lie = tick(bank, GROUP, group=False)                 # the bank says one-to-one, consent kept: both lies

    async def go():
        account, _ = await connected(made)
        out = await account.flush({GROUP: [TgEvent("new", GROUP, msg(1, GROUP, "group words", sender=DAVE))]})
        await account.stop()
        return out
    assert run(go()) == {}
    assert list((bank / "episodes").glob("*.md")) == [] and lie


def test_the_ingest_decides_from_the_peer(home, bank):
    group = tick(bank, GROUP, group=False)
    with pytest.raises(telegram_source.NotOneToOne):
        telegram_source.ingest(bank, {"id": group, "chat": GROUP, "group": False}, [msg(1, GROUP, "x", sender=DAVE)])
    friend = tick(bank, FRIEND)
    with pytest.raises(telegram_source.NotOneToOne):     # a user's id dressed as another chat's conversation
        telegram_source.ingest(bank, {"id": friend, "chat": OTHER}, [msg(1, OTHER, "x", sender=OTHER)])
    with pytest.raises(telegram_source.NotOneToOne):     # a group's message slipped into a one-to-one batch
        telegram_source.ingest(bank, {"id": friend, "chat": FRIEND}, [msg(1, GROUP, "x", sender=DAVE)])
    assert list((bank / "episodes").glob("*.md")) == []


def test_deletes_by_id_alone_and_reaction_sets_replace(home, bank, made):
    friend = tick(bank, FRIEND)

    async def go():
        account, _ = await connected(made)
        await account.chats()
        await account.flush({FRIEND: [TgEvent("new", FRIEND, msg(1, FRIEND, "keep", out=True)),
                                      TgEvent("new", FRIEND, msg(2, FRIEND, "oops wrong chat", sender=FRIEND))]})
        await account.flush({FRIEND: [TgEvent("reactions", FRIEND, ids=[1], reactions=[
            {"emoji": "👍", "from_me": False, "sender": FRIEND}, {"emoji": "🔥", "from_me": True}])]})
        first = episodes(bank)
        await account.flush({None: [TgEvent("delete", None, ids=[2])],
                             FRIEND: [TgEvent("reactions", FRIEND, ids=[1], reactions=[{"emoji": "🔥",
                                                                                        "from_me": True}])]})
        await account.stop()
        return first
    first = run(go())
    (before,) = first.values()
    (extras,) = turn_extras.by_offset(before.frontmatter).values()
    assert sorted(r["by"] for r in extras["reactions"]) == ["speaker:bob-example", "user"]
    (ep,) = episodes(bank).values()
    assert ep.body == "user: keep"
    assert len(turn_extras.unsent(ep.frontmatter)) == 1
    (extras,) = turn_extras.by_offset(ep.frontmatter).values()
    assert extras["reactions"] == [{"by": "user", "kind": "emoji", "emoji": "🔥"}]
    assert ep.frontmatter["conversation"] == friend


def test_history_only_on_ask_and_the_cursor_catches_up(home, bank, made):
    friend = tick(bank, FRIEND)

    async def go():
        account, port = await connected(made)
        port.history_rows[FRIEND] = [msg(i, FRIEND, f"old {i}", sender=FRIEND, at=1_700_000_000 + i * 10)
                                     for i in range(1, 6)]
        before = await account.read(friend)              # ticked but no history asked: all before the tick
        chat_live.update_settings(bank, telegram_source.SPEC, {"id": friend, "history": True})
        after = await account.read(friend)
        await account.stop()
        return before, after
    before, after = run(go())
    assert before["created"] == 0 and after["created"] == 1
    (ep,) = episodes(bank).values()
    assert ep.body.count("\n") == 4
    assert json.loads((home / "telegram" / "cursors.json").read_text()) == {friend: 5}


def test_the_demo_bank_is_never_written(home, bank, made, monkeypatch):
    tick(bank, FRIEND)
    monkeypatch.setattr("api.services.demo_guard.is_demo", lambda path: True)

    async def go():
        account, _ = await connected(made)
        out = await account.flush({FRIEND: [TgEvent("new", FRIEND, msg(1, FRIEND, "hi", sender=FRIEND))]})
        await account.stop()
        return out
    assert run(go()) == {}
    assert list((bank / "episodes").glob("*.md")) == []


def test_disconnect_logs_out_and_forgets_even_when_telegram_does_not_answer(home, bank, made):
    async def go(fail):
        account, port = await connected(made)
        port.fail_log_out = fail
        status = await account.disconnect()
        return port, status
    port, status = run(go(False))
    assert "log_out" in port.calls and status["state"] == "off" and status["error"] is None
    assert not (home / "telegram" / "session").exists()
    port, status = run(go(True))
    assert not (home / "telegram" / "session").exists() and "Active sessions" in status["error"]


def test_routes_say_the_consent_and_refuse_without_a_connection(bank, home):
    client = TestClient(main.app)
    status = client.get("/sources/telegram/status").json()
    assert status["consent"] == telegram_account.CONSENT and status["state"] in ("off", "ended")
    assert "Active sessions" in status["consent"] and "one click" in status["consent"]
    assert client.get("/sources/telegram/chats").status_code == 409
    r = client.put("/sources/telegram/settings", json={"conversation": {"id": "ab" * 12, "history": True}})
    assert r.status_code == 422   # not connected: Telegram lists nothing, so nothing is one-to-one


def test_live_update_cost_p95(home, bank, made):
    """Telegram update → episode, the backend half: one new message into a chat holding 40 sittings."""
    friend = tick(bank, FRIEND, history=True)

    async def go():
        account, _ = await connected(made)
        await account.chats()
        await account.flush({FRIEND: [TgEvent("new", FRIEND, msg(i, FRIEND, f"m {i}", sender=FRIEND,
                                                                   at=T0 + i * 4 * 3600)) for i in range(1, 41)]})
        took = []
        for i in range(41, 71):
            started = time.perf_counter()
            await account.flush({FRIEND: [TgEvent("new", FRIEND, msg(i, FRIEND, f"live {i}", sender=FRIEND,
                                                                       at=T0 + 41 * 4 * 3600 + i * 60))]})
            took.append(time.perf_counter() - started)
        await account.stop()
        return sorted(took)
    took = run(go())
    p95 = took[int(len(took) * 0.95) - 1]
    print(f"telegram live update p95 {p95 * 1000:.1f} ms over {len(took)} (flush + commit, 41 sittings)")
    assert p95 < 1.0 and friend
