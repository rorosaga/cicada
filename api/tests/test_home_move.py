"""G132 phase 2 (ruling 51a), in process: the pieces of moving the home. Synthetic banks only, nothing leaves loopback.

* the hand-off record: signed by the computer's own key, refused with another key, an edited body or no key on record;
* the registry every full device shares: a device's own row, what it says about itself (its key set once), the export
  and the import a new home makes (a revoke never undone, ``is_self`` only its own);
* a crash at each step of a hand-off, finished or undone at the next start — never two that admit;
* a home closed by a move refuses every bank writer, the app's writes and the tool door's, and starts no Sleep;
* the take-over preview says how far behind and when; the words for what an old home set aside;
* an offered episode is written once through the new home's writer;
* unset or off, nothing changes: ``/sync/home`` says ``shared: false`` and nothing is written under ``sync/``.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from _synthetic_bank import _bank
from api import config
from api.services import (bank_registry, device_key, device_tokens, home_move, home_record, markdown_parser,
                          replica_guard, sync_publish)


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True).stdout


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A computer whose memory (a git bank at the root) is shared: publishing on by its settings file."""
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "cicada"))
    for var in ("CICADA_REPLICA_OF", "CICADA_API_BASE", "CICADA_SYNC_PUBLISH", "CICADA_DEVICE_URL"):
        monkeypatch.delenv(var, raising=False)
    replica_guard.thaw()
    bank = _bank(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    config.get_settings.cache_clear()
    bank_registry.ensure_bank_ids(bank)
    home_move._CACHE.clear()     # noqa: SLF001
    yield bank
    config.get_settings.cache_clear()
    home_move._clear_handoff()   # noqa: SLF001


def _share() -> None:
    sync_publish.set_enabled(True)


# --- the record -----------------------------------------------------------------------------------------------------------

def test_a_record_holds_only_under_the_key_the_registry_knows_for_its_signer(home):
    rec = home_record.make(bank_id="b" * 32, term=1, kind="move", seq=7, after="a" * 40,
                           source={"device": "aaaaaaaa", "name": "alpha"}, to={"device": "bbbbbbbb", "name": "b"},
                           signer="aaaaaaaa")
    mine = device_key.thumbprint(device_key.public_jwk(create=False))
    assert mine and home_record.verify(rec, mine) is None
    assert home_record.verify(rec, None) == "unknown_signer"
    assert home_record.verify(rec, "x" * 43) == "wrong_key"
    edited = home_record.Record({**rec.data, "to": {"device": "cccccccc", "name": "c"}})
    assert home_record.verify(edited, mine) == "bad_signature"
    assert home_record.verify(home_record.Record({k: v for k, v in rec.data.items() if k != "sig"}), mine) \
        == "unsigned"
    # The key file is 0600 and never in a bank; the record carries only the public half.
    assert oct((Path(home_move._sync_root()) / device_key.FILE).stat().st_mode)[-3:] == "600"   # noqa: SLF001
    assert set(rec.data["key"]) == {"kty", "crv", "x", "y"}


def test_the_record_commits_alone_and_reads_back_from_the_history(home):
    _git(home, "config", "user.email", "t@example.com")
    (home / "entities" / "dirty-example.md").write_text("---\nname: Dirty\n---\nnot mine\n")
    rec = home_record.make(bank_id="b" * 32, term=1, kind="move", seq=1, after=None,
                           source={"device": "aaaaaaaa", "name": "a"}, to={"device": "bbbbbbbb", "name": "b"},
                           signer="aaaaaaaa")
    with replica_guard.applying():
        home_record.commit(home, rec, subject="Home moved to b")
    assert _git(home, "show", "--name-only", "--format=", "HEAD").split() == ["_home.json"]
    assert "Cicada-Author: cicada" in _git(home, "log", "-1", "--format=%B")
    assert home_record.at(home).to == "bbbbbbbb" and home_record.at(home).term == 1
    assert "dirty-example.md" in _git(home, "status", "--porcelain")          # someone else's edit rode in nowhere


# --- the registry -----------------------------------------------------------------------------------------------------------

def test_the_registry_moves_with_the_home_and_never_undoes_a_revoke(home, tmp_path, monkeypatch):
    store = device_tokens.store()
    laptop, laptop_token = store.create("laptop")
    phone, _ = store.create("phone")
    store.revoke(phone.id)
    store.announce(laptop.id, sign_jwk={"kty": "EC", "crv": "P-256", "x": "x", "y": "y"},
                   address="https://laptop.example", bank_id="b" * 32, seq=4)
    with pytest.raises(ValueError):
        store.announce(laptop.id, sign_jwk={"kty": "EC", "crv": "P-256", "x": "other", "y": "y"})   # set once
    own, own_token = store.make_own("desk", device_key.public_jwk())
    assert store.own().id == own.id and own.id not in {d.id for d in store.list()}       # never "your devices"
    rows = store.export()
    assert all("token" not in r for r in rows) and all(r["token_hash"] for r in rows)
    assert not any(own_token in json.dumps(r) or laptop_token in json.dumps(r) for r in rows)

    # Another computer takes the registry (it became the home): every token still works there; the phone stays revoked.
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "other"))
    other = device_tokens.store()
    other.create("unrelated")
    assert other.import_rows(rows, me=laptop.id) == 3
    assert other.verify(laptop_token).id == laptop.id and other.verify(own_token).id == own.id
    assert other.get(phone.id).revoked_at and other.own().id == laptop.id
    assert other.get(own.id).is_self is False


# --- a crash at each step ------------------------------------------------------------------------------------------------------

def test_the_doors_close_first_and_the_bank_is_sealed_once_admitted_writers_finished(home):
    _share()
    to = {"device": "bbbbbbbb", "name": "b", "address": "https://b.example"}
    home_move._close(home, "leaving", to, 1)   # noqa: SLF001
    # Doors closed, the backstop still open: a writer admitted before the close finishes its whole write.
    assert home_move.writes_closed() and not replica_guard.blocks()
    markdown_parser.write(home / "entities" / "in-flight.md", {"name": "in flight"}, "body")
    home_move._close(home, "sealed", to, 1)   # noqa: SLF001
    assert replica_guard.blocks()
    with pytest.raises(PermissionError) as refused:
        markdown_parser.write(home / "entities" / "x.md", {"name": "x"}, "body")
    assert "moving to b" in str(refused.value) and refused.value.code == "home_moving"


@pytest.mark.parametrize("phase", ["leaving", "sealed"])
def test_a_move_cut_before_its_record_is_undone_and_the_home_admits_again(home, phase):
    _share()
    home_move._close(home, phase, {"device": "bbbbbbbb", "name": "b", "address": "https://b.example"}, 1)   # noqa: SLF001
    assert home_move.writes_closed()
    assert home_move.finish_at_start() == "undone"
    assert not home_move.writes_closed() and not replica_guard.blocks()
    assert home_move.role(home) == "home"


def test_a_home_whose_target_never_came_takes_its_memory_back(home, monkeypatch):
    _share()
    me = home_move.ensure_own_identity()
    to = {"device": "bbbbbbbb", "name": "b-desk", "address": "https://b.example"}
    home_move._close(home, "sealed", to, 1)   # noqa: SLF001
    rec = home_record.make(bank_id="b" * 32, term=1, kind="move", seq=1, after=None,
                           source={"device": me, "name": "a"}, to={"device": "bbbbbbbb", "name": "b-desk"}, signer=me)
    with replica_guard.applying():
        home_record.commit(home, rec, subject="Home moved to b-desk")
    home_move._close(home, "left", to, 1)   # noqa: SLF001
    monkeypatch.setattr(home_move, "_ask", lambda *a, **k: (None, None))       # b-desk never answers
    preview = home_move.take_over_preview(home)
    assert preview["possible"] and preview["behind"] == 0 and "has not taken over" in preview["text"]
    assert home_move.take_over(home, behind_seen=0)["takeBack"]
    back = home_record.at(home)
    assert back.term == 2 and back.kind == "take-over" and back.to == me
    assert home_move.role(home) == "home" and not replica_guard.blocks()
    monkeypatch.setattr(home_move, "_ask", lambda *a, **k: (200, {"role": "home", "term": 1}))
    home_move._close(home, "left", to, 1)   # noqa: SLF001
    assert home_move.take_over_preview(home)["code"] == "home_reachable"   # it is taking over: not taken back


def test_the_hand_off_carries_what_is_uncommitted_and_leaves_the_cursor_and_markers(home):
    _git(home, "config", "user.email", "t@example.com")
    _git(home, "config", "user.name", "t")
    (home / "_state.md").write_text("cursor, regenerated by the next home\n")
    _git(home, "add", "_state.md")
    _git(home, "commit", "-q", "-m", "state")
    (home / "_state.md").write_text("a newer cursor, this computer's only\n")
    (home / "_preferences.md").write_text("edited by hand\n")
    _git(home, "add", "_preferences.md")
    _git(home, "commit", "-q", "-m", "prefs")
    (home / "_preferences.md").write_text("edited by hand again\n")
    (home / "episodes" / "ep_2026-10-29_009.md").write_text("---\nid: ep_2026-10-29_009\n---\na save\n")
    (home / ".a_migration_marker").write_text("x")
    with replica_guard.applying():
        assert home_move.carry_uncommitted(home) == 2
    assert _git(home, "status", "--porcelain", "--untracked-files=no") == ""
    shown = _git(home, "show", "--name-only", "--format=%B", "HEAD")
    assert "episodes/ep_2026-10-29_009.md" in shown and "_preferences.md" in shown and "_state.md" not in shown
    assert "Cicada-Author" not in shown and "trigger: sync/handoff-carry" in shown         # never under a guessed author
    assert (home / ".a_migration_marker").exists() and ".a_migration_marker" not in shown


def test_a_move_cut_after_its_record_stays_closed_and_goes_on_handing_off(home):
    _share()
    to = {"device": "bbbbbbbb", "name": "b", "address": "https://b.example"}
    home_move._close(home, "leaving", to, 1)   # noqa: SLF001
    rec = home_record.make(bank_id="b" * 32, term=1, kind="move", seq=1, after=None,
                           source={"device": "aaaaaaaa", "name": "a"}, to={"device": "bbbbbbbb", "name": "b"},
                           signer="aaaaaaaa")
    with replica_guard.applying():
        home_record.commit(home, rec, subject="Home moved to b")
    assert home_move.finish_at_start() == "closed"
    assert home_move.handoff()["phase"] == "left" and home_move.role(home) == "left"
    assert replica_guard.blocks()                                   # it never admits again before it follows b


def test_a_demotion_cut_short_is_finished_at_the_next_start(home):
    _share()
    (home_move._sync_root(create=True) / home_move.SELF_TOKEN).write_text("cic_dev_aaaaaaaa_" + "s" * 43 + "\n")   # noqa: SLF001
    home_move._close(home, "left", {"device": "bbbbbbbb", "name": "b", "address": "https://b.example"}, 1)   # noqa: SLF001
    name, path, bank_id = bank_registry._active_record(home)   # noqa: SLF001
    home_move._write_json(home_move._sync_root() / home_move.DEMOTE, {   # noqa: SLF001
        "bank": name, "bankPath": str(path), "bankId": bank_id,
        "to": {"device": "bbbbbbbb", "name": "b", "address": "https://b.example"}, "term": 1})
    assert home_move.finish_at_start() == "demoted"
    from api.services import runtime_layout

    assert (runtime_layout.cicada_home() / "replica_of").read_text().strip() == "https://b.example"
    assert (runtime_layout.cicada_home() / "device_token").read_text().startswith("cic_dev_aaaaaaaa_")
    assert not sync_publish.enabled() and not home_move.writes_closed()
    assert bank_registry.load_registry(home)["banks"][name]["replica"] is True
    assert home_move.finish_at_start() is None                      # once


def test_a_promotion_cut_short_is_finished_at_the_next_start(home, monkeypatch):
    from api.services import replica, runtime_layout

    store = device_tokens.store()
    them, _ = store.create("desk")
    rows = store.export()
    name, path, bank_id = bank_registry._active_record(home)   # noqa: SLF001
    registry = bank_registry.load_registry(home)
    registry["banks"][name]["replica"] = True
    bank_registry.save_registry(home, registry)
    replica._write_marker(path, {"home": "a.example", "bankId": bank_id, "seq": 1, "sha": ""})   # noqa: SLF001
    (runtime_layout.cicada_home() / "replica_of").write_text("https://a.example\n")
    home_move._write_json(home_move._sync_root(create=True) / home_move.PROMOTE, {   # noqa: SLF001
        "bank": name, "bankPath": str(path), "bankId": bank_id, "term": 1, "me": them.id, "rows": rows,
        "schedule": {"mode": "daily", "enabled": True, "hour": 4, "minute": 30}})
    assert home_move.finish_at_start() == "promoted"
    assert not (runtime_layout.cicada_home() / "replica_of").exists() and sync_publish.enabled()
    assert bank_registry.load_registry(home)["banks"][name]["replica"] is False
    assert replica.read_marker(path) is None
    from api.services import sleep_scheduler

    assert sleep_scheduler.read_schedule(path).hour == 4                  # Sleep moved with the home


# --- a closed home's doors ---------------------------------------------------------------------------------------------------

@pytest.fixture
def client(home):
    from api.main import app

    with TestClient(app) as c:
        yield c


def _auth() -> dict:
    from api.services import auth

    return {"Authorization": f"Bearer {auth.get_token()}"}


def test_a_closed_home_refuses_the_apps_writes_the_tool_door_and_sleep(home, client):
    _share()
    home_move._close(home, "left", {"device": "bbbbbbbb", "name": "b-desk", "address": "https://b.example"}, 1)   # noqa: SLF001
    r = client.post("/sources/save", json={"url": "https://example.com/x"}, headers=_auth())
    assert r.status_code == 503 and r.json()["code"] == "home_moving" and "b-desk" in r.json()["detail"]
    r = client.post("/tools/call", json={"tool": "cicada_save_episode", "arguments": {"content": "x"}},
                    headers=_auth())
    assert r.status_code == 503 and r.json()["code"] == "home_moving"
    r = client.post("/tools/call", json={"tool": "cicada_recall", "arguments": {"query": "alpha"}},
                    headers=_auth())
    assert r.status_code == 200                                       # reads still answer
    assert client.post("/sleep/trigger", headers=_auth()).status_code in (409, 503)
    assert client.get("/sync/home", headers=_auth()).json()["role"] == "left"


def test_one_computer_that_shares_nothing_sees_nothing_new(home, client):
    assert client.get("/sync/home", headers=_auth()).json() == {"shared": False, "role": "local"}
    assert client.get("/sync/devices", headers=_auth()).status_code == 404
    r = client.post("/sync/home/move", json={"device": "bbbbbbbb"}, headers=_auth())
    assert r.status_code == 409 and r.json()["code"] == "not_shared"
    assert not (home_move._sync_root() / home_move.HANDOFF).exists()   # noqa: SLF001
    assert not device_key.exists() and device_tokens.store().own() is None


def test_a_demo_never_moves(home, client, monkeypatch):
    from api.services import demo_guard

    _share()
    monkeypatch.setattr(demo_guard, "is_demo", lambda _p: True)
    r = client.post("/sync/home/move", json={"device": "bbbbbbbb"}, headers=_auth())
    assert r.status_code == 409 and r.json()["code"] == "demo"


def test_the_peer_route_answers_only_a_device_of_the_group(home, client):
    _share()
    _device, token = device_tokens.store().create("laptop")
    assert client.get("/sync/peer").status_code == 401
    assert client.get("/sync/peer", headers={"Authorization": "Bearer cic_dev_zzzzzzzz_" + "x" * 43}).status_code == 401
    body = client.get("/sync/peer", headers={"Authorization": f"Bearer {token}"}).json()
    assert body["role"] == "home" and body["term"] == 0 and set(body) == {
        "bankId", "term", "role", "device", "seq", "home", "canHost"}


def test_recopy_racing_a_stop_answers_409_with_a_sentence(home, client, monkeypatch):
    from api.services import replica

    monkeypatch.setattr(replica_guard, "active", lambda: True)

    def stopped():
        raise replica.NoLongerACopy()

    monkeypatch.setattr(replica, "recopy", stopped)
    r = client.post("/sync/replica/recopy", headers=_auth())
    assert r.status_code == 409 and r.json()["code"] == "no_longer_a_copy" and r.json()["detail"]


# --- take-over words, set-aside words ------------------------------------------------------------------------------------

def test_the_take_over_preview_says_how_far_behind_and_when(home, monkeypatch):
    from api.services import replica, runtime_layout

    monkeypatch.setattr(runtime_layout, "is_replica", lambda environ=None: True)
    monkeypatch.setattr(replica, "state", lambda: {"seq": 40, "homeSeq": 43, "lastContact": "2026-10-29T09:00:00Z"})
    monkeypatch.setattr(replica, "request", lambda *a, **k: (None, {}, None))
    preview = home_move.take_over_preview(home)
    assert preview["possible"] and preview["behind"] == 3
    assert preview["text"].startswith("This computer is 3 changes behind the last home it saw")
    monkeypatch.setattr(replica, "request", lambda *a, **k: (200, {}, {}))
    assert home_move.take_over_preview(home)["code"] == "home_reachable"          # not lost: a move instead


def test_a_copy_reports_the_move_its_home_is_making(home, monkeypatch):
    """Review of #570: a move pressed on a copy runs at the home; the copy's overview says so from the home's words."""
    from api.services import replica

    monkeypatch.setattr(home_move, "role", lambda _p: "replica")
    monkeypatch.setattr(home_move, "my_device_id", lambda: "cccccccc")
    monkeypatch.setattr(home_move, "registry", lambda _p: [])
    monkeypatch.setattr(replica, "state", lambda: {"status": "following", "seq": 3, "homeSeq": 3, "behind": 0})
    moving = {"phase": "leaving", "text": "Your memory is moving to bravo-laptop."}
    monkeypatch.setattr(replica, "request", lambda *a, **k: (200, {}, {"moving": moving}))
    assert home_move.overview(home)["moving"] == moving
    monkeypatch.setattr(replica, "request", lambda *a, **k: (None, {}, None))      # the home is restarting
    assert home_move.overview(home)["moving"] is None


def test_the_set_aside_words_count_what_was_kept_and_what_was_sent():
    text = home_move.set_aside_text({"commits": 3, "home": "desk", "episodes": 2, "calls": 1, "wasHome": True})
    assert text.startswith("3 changes made on this computer after desk took over are kept aside here, never merged.")
    assert "2 conversations and notes and 1 other change were sent to desk to apply" in text
    copy = home_move.set_aside_text({"commits": 1, "home": "desk", "episodes": 0, "calls": 0, "wasHome": False})
    assert copy.startswith("1 change this copy had that desk never received is kept aside here, never merged.")


# --- an offered episode ------------------------------------------------------------------------------------------------------

def test_an_offered_episode_is_written_once_through_the_writer(home):
    from api.services import offered_episode

    text = ("---\nid: ep_2026-10-20_007\ntimestamp: '2026-10-20T10:00:00+00:00'\nsource: claude-code\n"
            "session_id: ses_offered_1\nprocessed: true\n---\nuser: decided the india-example plan\n")
    first = offered_episode.write(home, text, from_device="aaaaaaaa", term=1)
    assert first["status"] == "created" and first["episodeId"].startswith("ep_2026-10-20_")
    fm = markdown_parser.parse(home / "episodes" / f"{first['episodeId']}.md").frontmatter
    assert fm["processed"] is False and fm["offered_from"] == "aaaaaaaa" and fm["session_id"] == "ses_offered_1"
    assert offered_episode.write(home, text, from_device="aaaaaaaa", term=1) == {"status": "already"}
    again = text.replace("ses_offered_1", "ses_offered_2")          # the same words from another door: once
    assert offered_episode.write(home, again, from_device="aaaaaaaa", term=1) == {"status": "already"}
    assert offered_episode.write(home, "no frontmatter", from_device=None, term=None)["status"] == "refused"


# --- the command line (ruling 21a: the backend's own routes; refused from an agent's shell) ----------------------------

class _Boot:
    probe = {"state": "ok"}


def test_home_move_and_take_over_refuse_from_an_agents_shell(monkeypatch):
    from api import cli_app
    from api.cli_types import Refusal

    sent = []
    monkeypatch.setattr(cli_app, "call", lambda *a, **k: sent.append(a) or {})
    monkeypatch.setenv("CODEX_THREAD_ID", "thread-example")
    for cmd, args in ((cli_app.cmd_home_move, type("A", (), {"device": "desk"})()),
                      (cli_app.cmd_home_take_over, type("A", (), {"yes": True})())):
        with pytest.raises(Refusal) as refused:
            cmd(_Boot(), args)
        assert refused.value.code == "person_only"
    assert sent == []                                                  # nothing reached the backend


def test_home_move_names_the_device_and_take_over_confirms_what_it_showed(monkeypatch):
    from api import cli_app
    from api.cli_types import Refusal

    for key in ("CODEX_THREAD_ID", "CODEX_SESSION_ID", "CODEX_SANDBOX", "CLAUDE_CODE_SESSION_ID", "CLAUDECODE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(cli_app, "agent_shell", lambda environ=None: None)
    page = {"shared": True, "home": {"name": "alpha", "me": True, "online": True, "sleep": {"status": "idle"}},
            "devices": [{"id": "bbbbbbbb", "name": "Desk", "online": True, "keepsCopy": True, "behind": 0}]}
    calls = []

    def fake(_boot, method, path, body=None, **_k):
        calls.append((method, path, body))
        if path == "/sync/home":
            return page
        if path == "/sync/home/take-over" and method == "GET":
            return {"possible": True, "behind": 2, "text": "This computer is 2 changes behind the last home it saw."}
        return {"moving": {"text": "Your memory is moving to Desk."}} if path.endswith("move") else {"took": True}

    monkeypatch.setattr(cli_app, "call", fake)
    out = cli_app.cmd_home_move(_Boot(), type("A", (), {"device": "desk"})())
    assert calls[-1] == ("POST", "/sync/home/move", {"device": "bbbbbbbb"}) and "Desk" in out.text
    assert "Home (runs Sleep): alpha — this computer" in cli_app.cmd_home_status(_Boot(), None).text
    monkeypatch.setattr(cli_app, "_interactive", lambda: False)
    with pytest.raises(Refusal) as refused:                          # shown, not confirmed: nothing sent
        cli_app.cmd_home_take_over(_Boot(), type("A", (), {"yes": False})())
    assert "2 changes behind" in str(refused.value) and calls[-1][0] == "GET"
    cli_app.cmd_home_take_over(_Boot(), type("A", (), {"yes": True})())
    assert calls[-1] == ("POST", "/sync/home/take-over", {"behind": 2, "confirm": True})
