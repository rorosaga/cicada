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
        "bankId", "term", "role", "device", "seq", "home", "canHost", "record"}


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
                      (cli_app.cmd_home_take_over, type("A", (), {"yes": True, "behind": 0})())):
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
    with pytest.raises(Refusal) as refused:                          # --yes alone: it says the N, sends nothing
        cli_app.cmd_home_take_over(_Boot(), type("A", (), {"yes": True, "behind": None})())
    assert "--behind 2" in str(refused.value) and calls[-1][0] == "GET"
    with pytest.raises(Refusal):                                     # another N than the one shown: refused
        cli_app.cmd_home_take_over(_Boot(), type("A", (), {"yes": True, "behind": 5})())
    assert calls[-1][0] == "GET"
    cli_app.cmd_home_take_over(_Boot(), type("A", (), {"yes": True, "behind": 2})())
    assert calls[-1] == ("POST", "/sync/home/take-over", {"behind": 2, "confirm": True})


# --- review of #569: the tie-break, verified homes, mirrors, offers, keys ----------------------------------------


def test_an_equal_term_is_broken_the_same_way_everywhere():
    assert home_move.outranks(2, "zzzzzzzz", 1, "aaaaaaaa")              # a higher term wins
    assert home_move.outranks(1, "aaaaaaaa", 1, "bbbbbbbb")              # equal: the lower device id
    assert not home_move.outranks(1, "bbbbbbbb", 1, "aaaaaaaa")
    assert not home_move.outranks(1, "aaaaaaaa", 1, "aaaaaaaa")          # never over itself


def _signed(term: int, to: str, signer: str, bank_id: str = "b" * 32):
    return home_record.make(bank_id=bank_id, term=term, kind="take-over", seq=1, after=None,
                            source={"device": "aaaaaaaa", "name": "a"}, to={"device": to, "name": to},
                            signer=signer)


def test_a_revoked_signer_never_holds_and_an_unsigned_peer_is_never_followed(home, monkeypatch):
    _share()
    store = device_tokens.store()
    laptop, _ = store.create("stolen-laptop")
    store.announce(laptop.id, sign_jwk=device_key.public_jwk())          # this computer's key, for the test
    rec = _signed(1, laptop.id, laptop.id)
    assert home_move._check(rec, store.export()) is None                 # noqa: SLF001
    store.revoke(laptop.id)
    assert home_move._check(rec, store.export()) == "revoked_signer"     # noqa: SLF001
    monkeypatch.setattr(home_move, "_pin", lambda: home_move._Pin("b" * 32))   # noqa: SLF001
    peer = {"role": "home", "term": 1, "device": laptop.id, "record": rec.data}
    assert not home_move.verified_peer(home, peer)                       # revoked
    assert not home_move.verified_peer(home, {**peer, "record": None})   # no record: never followed
    other, _ = store.create("desk")
    store.announce(other.id, sign_jwk=device_key.public_jwk())
    good = _signed(1, other.id, other.id)
    assert home_move.verified_peer(home, {"role": "home", "term": 1, "device": other.id, "record": good.data})
    assert not home_move.verified_peer(home, {"role": "home", "term": 2, "device": other.id, "record": good.data})


def test_a_take_over_is_refused_while_another_device_is_the_home(home, monkeypatch):
    from api.services import replica, runtime_layout

    monkeypatch.setattr(runtime_layout, "is_replica", lambda environ=None: True)
    monkeypatch.setattr(replica, "state", lambda: {"seq": 4, "homeSeq": 4, "lastContact": None})
    monkeypatch.setattr(replica, "request", lambda *a, **k: (None, {}, None))       # the last home is gone
    monkeypatch.setattr(home_move, "_own_token", lambda: "cic_dev_cccccccc_" + "x" * 43)
    monkeypatch.setattr(home_move, "my_device_id", lambda: "cccccccc")
    monkeypatch.setattr(home_move, "_pin", lambda: home_move._Pin("b" * 32))         # noqa: SLF001
    monkeypatch.setattr(home_move, "registry", lambda _p: [
        {"id": "bbbbbbbb", "name": "bravo-laptop", "kind": "full", "address": "https://b.example"}])
    monkeypatch.setattr(home_move, "_ask", lambda *a, **k: (200, {"bankId": "b" * 32, "role": "home", "term": 1}))
    preview = home_move.take_over_preview(home)
    assert preview["code"] == "another_home" and "bravo-laptop holds your memory" in preview["text"]
    monkeypatch.setattr(home_move, "_ask", lambda *a, **k: (200, {"bankId": "b" * 32, "role": "replica", "term": 0}))
    assert home_move.take_over_preview(home)["possible"]


def test_a_home_never_trusts_a_mirror(home, monkeypatch):
    _share()
    store = device_tokens.store()
    gone, token = store.create("old-desk")
    rows = store.export()
    store.revoke(gone.id)                                                  # revoked on this home
    home_move.save_mirror(home, rows)                                      # an old mirror still lists it
    assert home_move.peer_caller(home, token) is None                     # a home reads its own store only
    monkeypatch.setattr(replica_guard, "active", lambda: True)
    assert home_move.peer_caller(home, token) == gone.id                   # a copy uses its mirror


def test_the_peer_route_on_one_computer_that_shares_nothing_writes_nothing(home, client):
    r = client.get("/sync/peer", headers={"Authorization": "Bearer cic_dev_zzzzzzzz_" + "x" * 43})
    assert r.status_code == 401
    root = home_move._sync_root()                                          # noqa: SLF001
    assert not root.exists() or not any(p.is_dir() for p in root.iterdir())


def test_an_offered_conversation_that_continues_one_here_updates_it_in_place(home):
    from api.services import offered_episode

    first = ("---\nid: ep_2026-10-20_001\ntimestamp: '2026-10-20T10:00:00+00:00'\nsource: claude-code\n"
             "session_id: ses_long_1\n---\nuser: the juliet-example plan\n")
    made = offered_episode.write(home, first, from_device="aaaaaaaa", term=1)
    longer = first + "assistant: noted\nuser: and the kilo-example budget\n"
    again = offered_episode.write(home, longer, from_device="aaaaaaaa", term=1)
    assert again == {"status": "updated", "episodeId": made["episodeId"]}            # later turns never dropped
    text = (home / "episodes" / f"{made['episodeId']}.md").read_text()
    assert "kilo-example budget" in text and "processed: false" in text
    assert offered_episode.write(home, first, from_device="aaaaaaaa", term=1) == {"status": "already"}
    other = first.replace("juliet-example plan", "lima-example plan")                 # diverged: kept on its own
    assert offered_episode.write(home, other, from_device="aaaaaaaa", term=1)["status"] == "created"


def _identity(bank):
    _git(bank, "config", "user.email", "t@example.com")
    _git(bank, "config", "user.name", "t")


def test_a_write_is_offered_by_what_it_produced_never_by_a_seq(home):
    from api.services import admitted_log

    _identity(home)
    _share()
    base = _git(home, "rev-parse", "HEAD").strip()
    for title in ("One", "Two"):
        (home / "entities" / f"{title.lower()}.md").write_text(f"{title}\n")
        _git(home, "add", "-A")
        _git(home, "commit", "-q", "-m", title)
        # Both read seq 10 (concurrent writes); the new home took over at `base`.
        admitted_log.record_tool(home, tool="cicada_add_backlog_item", arguments={"title": title}, seq_before=10)
    assert [e["arguments"]["title"] for e in admitted_log.not_in(home, base, since_seq=11)] == ["One", "Two"]
    assert admitted_log.not_in(home, _git(home, "rev-parse", "HEAD").strip()) == []   # both already in it


def test_the_outbox_keeps_an_offer_once(home):
    from api.services import tx_outbox

    entry = tx_outbox.rest_entry("POST", "/capture/offered", "", b"{}", "application/json", bank_id="b",
                                 base_seq=None, key="k" * 32)
    assert tx_outbox.keep(entry) and tx_outbox.keep(dict(entry))
    assert sum(1 for p in tx_outbox.entries() if "kkkkkkkkkkkk" in p.name) == 1


def test_a_reconcile_whose_offers_cannot_be_kept_rewrites_nothing(home, tmp_path, monkeypatch):
    """The offers are kept before the rewrite; a refused keep stops it with the copy untouched, and done again it
    finishes."""
    from api.services import tx_outbox

    _identity(home)
    _share()
    me = home_move.ensure_own_identity()
    other = tmp_path / "theirs"
    _git(tmp_path, "clone", "-q", str(home), str(other))
    _identity(other)
    (home / "episodes" / "ep_2026-10-29_050.md").write_text("---\nid: ep_2026-10-29_050\n---\nuser: mike-example\n")
    _git(home, "add", "-A")
    _git(home, "commit", "-q", "-m", "after the take-over point, here")
    mine = _git(home, "rev-parse", "HEAD").strip()
    rec = home_record.make(bank_id="b" * 32, term=1, kind="take-over", seq=1, after=None,
                           source={"device": me, "name": "a"}, to={"device": me, "name": "x"}, signer=me)
    (other / "_home.json").write_bytes(home_record.encode(rec))
    _git(other, "add", "-A")
    _git(other, "commit", "-q", "-m", "taken over")
    bundle = tmp_path / "pack.bundle"
    _git(other, "bundle", "create", "-q", str(bundle), "HEAD")
    monkeypatch.setattr(home_move, "outranks", lambda *a: True)
    real_keep = tx_outbox.keep
    monkeypatch.setattr(tx_outbox, "keep", lambda *a, **k: False)
    with pytest.raises(RuntimeError):
        home_move.reconcile(home, bundle)
    assert _git(home, "rev-parse", "HEAD").strip() == mine                    # nothing rewritten
    assert _git(home, "rev-parse", f"{home_move.SET_ASIDE_REF}/term-1").strip() == mine   # set aside first
    monkeypatch.setattr(tx_outbox, "keep", real_keep)
    summary = home_move.reconcile(home, bundle)
    assert summary["commits"] == 1 and summary["episodes"] == 1
    assert _git(home, "rev-parse", "HEAD").strip() == _git(other, "rev-parse", "HEAD").strip()
    assert any("capture/offered" in p.read_text() for p in tx_outbox.entries())


def test_idempotency_keys_travel_to_the_next_home(tmp_path, monkeypatch):
    import asyncio

    from api.services import idempotency

    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "old"))
    ran = []

    async def work():
        ran.append(1)
        return 200, {"text": "saved"}

    asyncio.run(idempotency.run_once("dev:b", "/tools/call:cicada_save_episode", "K-1", work))
    rows = idempotency.export_since(0)
    assert rows and "K-1" not in str(rows)                                    # the key's hash, never the key
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "new"))
    assert idempotency.import_rows(rows) == 1
    _status, body, replayed = asyncio.run(idempotency.run_once("dev:b", "/tools/call:cicada_save_episode", "K-1",
                                                               work))
    assert replayed and body == {"text": "saved"} and ran == [1]             # applied once across the move
