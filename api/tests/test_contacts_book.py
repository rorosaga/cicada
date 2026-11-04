"""G154 (owner 2026-11-04): the Contacts page shows every card on this Mac. `contacts_book` keeps names and thumbnails
for that grid alone, outside every bank; it feeds no match, is wiped by every forget, is read per device, and is on no
agent door. Synthetic people only."""
from __future__ import annotations

import ast
import base64
import stat
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.testclient import TestClient as StarletteClient

from _synthetic_bank import _bank, _entity
from api import config, main
from api.remote import app as remote_app
from api.remote import store as remote_store
from api.remote.runtime import RemoteRuntime
from api.services import (
    bank_index,
    cli_map,
    contacts_book,
    contacts_local,
    demo_guard,
    fact_sources,
    people_directory,
    replica_routes,
)

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 60
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 60
BOOK = "/sources/contacts-local/book"


@pytest.fixture
def client(tmp_path, monkeypatch):
    memory = _bank(tmp_path)   # has `bob-example` (person, "Bob Example")
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    yield TestClient(main.app), memory
    config.get_settings.cache_clear()


@pytest.fixture
def server(tmp_path, monkeypatch):
    """Auth on: a master token, device tokens."""
    memory = _bank(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_API_AUTH", "on")
    monkeypatch.delenv("CICADA_API_TOKEN", raising=False)
    config.get_settings.cache_clear()
    bank_index.invalidate()
    from api.services.auth import get_token

    master = get_token()
    with TestClient(main.app) as test_client:
        yield test_client, master, memory
    config.get_settings.cache_clear()


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _card(cid, given="", family="", photo=None):
    body = {"id": cid, "givenName": given, "familyName": family}
    if photo is not None:
        body["photoB64"] = base64.b64encode(photo).decode()
    return body


def _sync_card(cid, given, family, **facts):
    return {"id": cid, "givenName": given, "familyName": family, **facts}


def _put(c, cards, connection=None, headers=None):
    return c.put(BOOK, json={"cards": cards, "connection": connection}, headers=headers or {})


def _folder(memory, scope=contacts_book.HERE):
    return people_directory.path(memory.name, contacts_book.BOOK_DIR) / scope


# --- the book: every card, faces only ----------------------------------------------------------------------------------

def test_every_card_is_kept_a_one_part_name_and_a_nameless_card_too(client):
    c, _memory = client
    r = _put(c, [_card("C1", "Ann", "Example"), _card("C2", "Mononym"), _card("C3", family="Solo"), _card("C4")])
    assert r.status_code == 200 and r.json()["total"] == 4
    body = c.get(BOOK).json()
    assert body["total"] == 4 and body["inMemory"] == 0
    assert [row["name"] for row in body["cards"]] == ["Ann Example", "Mononym", "Solo", ""], "A→Z, nameless last"


def test_a_row_says_nothing_but_a_face_and_no_card_id_leaves(client):
    c, memory = client
    _put(c, [_card("SECRET-CARD-ID", "Ann", "Example", photo=JPEG)])
    row = c.get(BOOK).json()["cards"][0]
    assert set(row) == {"key", "name", "entityId", "photo"}
    assert "SECRET-CARD-ID" not in c.get(BOOK).text
    stored = (_folder(memory) / contacts_book.BOOK_FILE).read_text(encoding="utf-8")
    assert "SECRET-CARD-ID" not in stored
    assert not any("SECRET" in p.name for p in _folder(memory).iterdir())


def test_a_field_beyond_the_names_and_the_thumbnail_is_never_kept(client):
    c, memory = client
    card = {**_card("C1", "Ann", "Example"), "hasPhone": True, "email": "ann@example.invalid",
            "organization": "alpha-org", "phone": "+10000000000"}
    assert _put(c, [card]).status_code == 200
    stored = (_folder(memory) / contacts_book.BOOK_FILE).read_text(encoding="utf-8")
    for word in ("example.invalid", "alpha-org", "+1000", "has_phone", "hasPhone"):
        assert word not in stored


def test_the_set_is_rewritten_whole_and_a_gone_card_takes_its_thumbnail(client):
    c, memory = client
    _put(c, [_card("C1", "Ann", "Example", photo=JPEG), _card("C2", "Mononym", photo=PNG)])
    assert sum(p.suffix in (".jpg", ".png") for p in _folder(memory).iterdir()) == 2
    _put(c, [_card("C2", "Mononym", photo=PNG)])
    assert [row["name"] for row in c.get(BOOK).json()["cards"]] == ["Mononym"]
    assert [p.suffix for p in _folder(memory).iterdir() if p.name != contacts_book.BOOK_FILE] == [".png"]


def test_the_folder_and_its_files_are_private_and_outside_the_bank(client):
    c, memory = client
    _put(c, [_card("C1", "Ann", "Example", photo=JPEG)])
    folder = _folder(memory)
    assert memory not in folder.parents
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700
    assert stat.S_IMODE(folder.parent.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in folder.iterdir())
    assert subprocess.run(["git", "-C", str(memory), "status", "--porcelain"], capture_output=True,
                          text=True).stdout == ""


def test_a_thumbnail_is_served_by_its_key_uncached_and_a_bad_one_draws_the_monogram(client):
    c, _memory = client
    _put(c, [_card("C1", "Ann", "Example", photo=JPEG), _card("C2", "Mono", photo=b"not an image")])
    rows = {row["name"]: row for row in c.get(BOOK).json()["cards"]}
    assert rows["Ann Example"]["photo"] and rows["Mono"]["photo"] is None
    got = c.get(f"{BOOK}/{rows['Ann Example']['key']}/photo")
    assert got.status_code == 200 and got.content == JPEG
    assert got.headers["content-type"] == "image/jpeg" and got.headers["cache-control"] == "no-store"
    assert c.get(f"{BOOK}/{rows['Mono']['key']}/photo").status_code == 404
    for key in ("0" * 16, "..", "ABCDEF0123456789"):
        assert c.get(f"{BOOK}/{key}/photo").status_code == 404


def test_too_many_cards_is_too_many(client, monkeypatch):
    c, _memory = client
    monkeypatch.setattr(contacts_local, "MAX_CONTACTS", 1)
    assert _put(c, [_card("C1", "Ann"), _card("C2", "Bea")]).status_code == 413


# --- which card has a page: read from the pages, never a second match ------------------------------------------------

def test_a_matched_card_opens_its_page_and_is_listed_first(client):
    c, memory = client
    c.post("/sources/contacts-local/sync", json={"contacts": [_sync_card("C1", "Bob", "Example", hasPhone=True)]})
    _put(c, [_card("C0", "Aaron", "Waiting"), _card("C1", "Bob", "Example")])
    body = c.get(BOOK).json()
    assert body["inMemory"] == 1
    assert [(row["name"], row["entityId"]) for row in body["cards"]] == [("Bob Example", "bob-example"),
                                                                         ("Aaron Waiting", None)]


def test_a_page_born_later_shows_with_no_new_sync_and_a_removal_shows_too(client):
    """The link follows the pages: Sleep's rematch or the person's removal needs no second write here."""
    c, memory = client
    _put(c, [_card("C1", "Bob", "Example")])
    assert c.get(BOOK).json()["inMemory"] == 0
    c.post("/sources/contacts-local/sync", json={"contacts": [_sync_card("C1", "Bob", "Example", hasEmail=True)]})
    bank_index.invalidate(memory)
    assert c.get(BOOK).json()["cards"][0]["entityId"] == "bob-example"
    assert c.delete("/entities/bob-example/sources/0").status_code == 200
    bank_index.invalidate(memory)
    assert c.get(BOOK).json()["inMemory"] == 0


def test_a_card_holding_only_a_photo_joins_its_page_by_the_name_but_never_a_shared_one(client):
    c, memory = client
    c.post("/sources/contacts-local/sync", json={"contacts": [
        {**_sync_card("C1", "Bob", "Example"), "photoB64": base64.b64encode(JPEG).decode()}]})
    bank_index.invalidate(memory)
    assert not fact_sources.list_sources(memory, "bob-example"), "no facts: the page holds the photo only"
    _put(c, [_card("C1", "Bob", "Example")])
    assert c.get(BOOK).json()["cards"][0]["entityId"] == "bob-example"
    _put(c, [_card("C1", "Bob", "Example"), _card("C2", "Example", "Bob")])
    assert c.get(BOOK).json()["inMemory"] == 0, "two cards carry that name: neither is claimed"


def test_a_one_part_card_never_joins_a_page_by_a_name(client):
    c, memory = client
    _entity(memory, "mono-page", type="person", name="Mononym", contacts_photo={"sha": "abc", "ext": "jpg"})
    bank_index.invalidate(memory)
    _put(c, [_card("C1", "Mononym")])
    assert c.get(BOOK).json()["inMemory"] == 0


# --- it feeds nothing Sleep reads --------------------------------------------------------------------------------------

def test_the_book_feeds_no_waiting_index_seed_or_rematch(client):
    c, memory = client
    _entity(memory, "ann-example", type="person", name="Ann Example")
    subprocess.run(["git", "-C", str(memory), "add", "entities"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(memory), "commit", "-qm", "ann"], check=True, capture_output=True)
    bank_index.invalidate(memory)
    _put(c, [_card("C1", "Ann", "Example"), _card("C2", "Mononym"), _card("C3", "New", "Person")])
    assert contacts_local.load_waiting(memory.name) == []
    assert contacts_local.waiting_status(memory.name) == {"waiting": 0}
    index = contacts_local.waiting_index(memory)
    assert index.cards == {} and index.match(["New Person"]) is None and index.by_id("C3") is None
    report = contacts_local.rematch(memory)
    assert report.matched == 0 and report.paths == []
    assert not fact_sources.list_sources(memory, "ann-example")


def test_a_one_part_name_still_never_waits_with_the_book_beside_it(client):
    c, memory = client
    posted = c.post("/sources/contacts-local/sync", json={"contacts": [_sync_card("C1", "Mononym", ""),
                                                                       _sync_card("C2", "New", "Person")]})
    assert posted.json()["waiting"] == 1
    _put(c, [_card("C1", "Mononym"), _card("C2", "New", "Person")])
    assert [card["id"] for card in contacts_local.load_waiting(memory.name)] == ["C2"]
    assert c.get(BOOK).json()["total"] == 2


def _imports_of_the_book(tree) -> bool:
    """Any spelling: `import api.services.contacts_book`, `from api.services import contacts_book`, or
    `from api.services.contacts_book import read`, at any depth of the file."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any("contacts_book" in alias.name.split(".") for alias in node.names):
            return True
        if isinstance(node, ast.ImportFrom):
            if "contacts_book" in (node.module or "").split("."):
                return True
            if any(alias.name == "contacts_book" for alias in node.names):
                return True
    return False


def _sources():
    """Every door's code: the backend and the MCP server."""
    repo = Path(contacts_book.__file__).resolve().parents[2]
    for root in (repo / "api", repo / "mcp"):
        for path in root.rglob("*.py"):
            if not {"tests", ".venv", "__pycache__"} & set(path.parts):
                yield repo, path


def test_nothing_but_its_routes_imports_the_book():
    """A match cannot read a store it does not know. `contacts_local` names only the folder, to forget it."""
    importers = set()
    for repo, path in _sources():
        if path.name != "contacts_book.py" and _imports_of_the_book(ast.parse(path.read_text(encoding="utf-8"))):
            importers.add(path.relative_to(repo).as_posix())
    assert importers == {"api/routers/local_sources.py", "api/routers/devices.py"}


@pytest.mark.parametrize("line", ["from api.services.contacts_book import read", "import api.services.contacts_book as b",
                                  "from api.services import contacts_book", "def f():\n    from .contacts_book import read"])
def test_the_import_check_catches_every_spelling(line):
    assert _imports_of_the_book(ast.parse(line))


def test_no_other_code_names_the_books_route():
    """An MCP tool or a CLI command could reach the book over HTTP without importing it."""
    named = set()
    for repo, path in _sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        prose = {id(node.value) for node in ast.walk(tree) if isinstance(node, ast.Expr)}   # docstrings
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and BOOK in node.value \
                    and id(node) not in prose:
                named.add(path.relative_to(repo).as_posix())
    assert named == {"api/routers/local_sources.py", "api/services/replica_routes.py"}


def test_a_page_with_a_malformed_alias_field_never_fails_the_read_or_the_sync(client):
    c, memory = client
    _entity(memory, "photo-page", type="person", name="Photo Page", aliases=5,
            contacts_photo={"sha": "abc", "ext": "jpg"})
    _entity(memory, "one-alias", type="person", name="One Alias", aliases="Lone Alias",
            contacts_photo={"sha": "abd", "ext": "jpg"})
    bank_index.invalidate(memory)
    _put(c, [_card("C1", "Photo", "Page"), _card("C2", "Lone", "Alias")])
    body = c.get(BOOK).json()
    assert {row["name"]: row["entityId"] for row in body["cards"]} == {"Photo Page": "photo-page",
                                                                       "Lone Alias": "one-alias"}
    synced = c.post("/sources/contacts-local/sync", json={"contacts": [_sync_card("C9", "New", "Person")]})
    assert synced.status_code == 200, synced.text
    assert contacts_local.rematch(memory).matched == 0


def test_a_stored_row_it_cannot_read_is_skipped_not_a_failure(client):
    c, memory = client
    _put(c, [_card("C1", "Ann", "Example")])
    target = _folder(memory) / contacts_book.BOOK_FILE
    target.write_text('{"v": 1, "cards": [{"key": 5}, "x", {"key": "abc", "given": 7, "family": null}]}', encoding="utf-8")
    body = c.get(BOOK)
    assert body.status_code == 200, body.text
    assert [row["key"] for row in body.json()["cards"]] == ["abc"]


# --- the forget ----------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("route", ["/sources/contacts-local/waiting", BOOK])
def test_either_forget_wipes_the_book_in_every_bank_and_scope(client, route):
    c, memory = client
    _put(c, [_card("C1", "Ann", "Example", photo=JPEG)])
    contacts_book.save("other-bank", contacts_book.scope_of("dev1"), [{"id": "C2", "given_name": "Bea"}])
    answer = c.delete(route)
    assert answer.status_code == 200 and answer.json() == {"forgotten": 0}, "it keeps counting waiting cards only"
    assert not people_directory.path(memory.name, contacts_book.BOOK_DIR).exists()
    assert not people_directory.path("other-bank", contacts_book.BOOK_DIR).exists()
    assert c.get(BOOK).json() == {"total": 0, "inMemory": 0, "cards": []}


def test_a_save_read_before_a_forget_never_brings_the_book_back(client, monkeypatch):
    c, memory = client

    def forget_midway(_connection):   # after the save took its read time, before it takes the lock
        contacts_local.forget_waiting()
        return False

    with monkeypatch.context() as patch:
        patch.setattr(contacts_local, "connection_ended", forget_midway)
        assert contacts_book.save(memory.name, contacts_book.HERE, [{"id": "C1", "given_name": "Ann"}]) == 0
    assert not _folder(memory).exists()


def test_a_book_from_an_ended_connection_is_dropped(client):
    c, memory = client
    connection = "aaaaaaaa-0000-4000-8000-000000000000"
    assert c.delete(BOOK, params={"connection": connection}).status_code == 200
    assert _put(c, [_card("C1", "Ann")], connection=connection).status_code == 409
    assert not _folder(memory).exists()
    assert _put(c, [_card("C1", "Ann")], connection="bbbbbbbb-0000-4000-8000-000000000000").status_code == 200


def test_a_trashed_bank_takes_its_book_and_a_rename_moves_it(client):
    c, memory = client
    _put(c, [_card("C1", "Ann")])
    people_directory.rename(memory.name, "renamed")
    assert (people_directory.path("renamed", contacts_book.BOOK_DIR) / contacts_book.HERE).is_dir()
    people_directory.forget("renamed")
    assert not people_directory.folder("renamed").exists()


# --- a demo bank ---------------------------------------------------------------------------------------------------------

def test_a_demo_bank_takes_no_book_and_shows_none(client, monkeypatch):
    c, memory = client
    _put(c, [_card("C1", "Ann", "Example", photo=JPEG)])
    key = c.get(BOOK).json()["cards"][0]["key"]
    monkeypatch.setattr(demo_guard, "is_demo", lambda path: True)
    assert _put(c, [_card("C2", "Bea")]).status_code == 409
    assert c.get(BOOK).json()["total"] == 0
    assert c.get(f"{BOOK}/{key}/photo").status_code == 404


# --- who may read it -----------------------------------------------------------------------------------------------------

def test_no_token_reads_nothing(server):
    client, master, _memory = server
    assert _put(client, [_card("C1", "Ann", photo=JPEG)], headers=_auth(master)).status_code == 200
    key = client.get(BOOK, headers=_auth(master)).json()["cards"][0]["key"]
    assert client.get(BOOK).status_code == 401
    assert client.get(f"{BOOK}/{key}/photo").status_code == 401
    assert client.put(BOOK, json={"cards": []}).status_code == 401
    assert client.delete(BOOK).status_code == 401


def test_a_device_reads_only_the_book_it_posted_and_revoking_it_removes_that(server):
    client, master, memory = server
    made = client.post("/devices", json={"name": "laptop"}, headers=_auth(master)).json()
    device = made["token"]
    assert _put(client, [_card("C1", "Here", "Mac", photo=JPEG)], headers=_auth(master)).status_code == 200
    assert client.get(BOOK, headers=_auth(device)).json()["total"] == 0, "the server's own book is not this device's"
    here_key = client.get(BOOK, headers=_auth(master)).json()["cards"][0]["key"]
    assert client.get(f"{BOOK}/{here_key}/photo", headers=_auth(device)).status_code == 404

    assert _put(client, [_card("C2", "Client", "Mac")], headers=_auth(device)).status_code == 200
    assert [r["name"] for r in client.get(BOOK, headers=_auth(device)).json()["cards"]] == ["Client Mac"]
    assert [r["name"] for r in client.get(BOOK, headers=_auth(master)).json()["cards"]] == ["Here Mac"]

    scope = contacts_book.scope_of(made["device"]["id"])
    assert _folder(memory, scope).is_dir()
    assert client.delete(f"/devices/{made['device']['id']}", headers=_auth(master)).status_code == 200
    assert not _folder(memory, scope).exists()
    assert client.get(BOOK, headers=_auth(master)).json()["total"] == 1, "the server's own book stays"


def test_a_put_racing_a_revoke_never_brings_that_devices_book_back(server, monkeypatch):
    client, master, memory = server
    made = client.post("/devices", json={"name": "laptop"}, headers=_auth(master)).json()
    device_id = made["device"]["id"]
    scope = contacts_book.scope_of(device_id)
    real = contacts_local.connection_ended

    def revoke_midway(connection):   # the token was already checked; the revoke lands before the save takes its lock
        contacts_book.forget_device(device_id)
        return real(connection)

    # A context, never `monkeypatch.undo()`: that would also take back the fixture's own `CICADA_HOME`.
    with monkeypatch.context() as patch:
        patch.setattr(contacts_local, "connection_ended", revoke_midway)
        assert contacts_book.save(memory.name, scope, [{"id": "C1", "given_name": "Ann"}]) == 0
    assert not _folder(memory, scope).exists()
    # Nobody else's book is touched, and the marker survives the Contacts forget.
    assert contacts_book.save(memory.name, contacts_book.HERE, [{"id": "C1", "given_name": "Ann"}]) == 1
    contacts_local.forget_waiting()
    assert contacts_book.save(memory.name, scope, [{"id": "C1", "given_name": "Ann"}]) == 0
    marker = people_directory.folder("x").parent / contacts_book.REVOKED_FILE
    assert stat.S_IMODE(marker.stat().st_mode) == 0o600 and device_id not in marker.read_text(encoding="utf-8")


def test_a_capture_only_device_is_refused(server, monkeypatch):
    client, master, _memory = server
    from api.services import device_tokens

    pairing, code = device_tokens.store().create_pairing(kind="capture")
    redeemed = client.post("/pair", json={"code": code, "name": "phone"})
    assert redeemed.status_code in (200, 201), redeemed.text
    phone = redeemed.json()["token"]
    assert client.get(BOOK, headers=_auth(phone)).status_code == 403
    assert client.put(BOOK, json={"cards": []}, headers=_auth(phone)).status_code == 403


def test_an_agent_token_never_opens_it(server):
    client, master, _memory = server
    made = client.post("/agent-api/tokens", json={"name": "Agent", "scopes": ["search", "read", "record", "sources"],
                                                  "expiresInDays": 30, "baseUrl": "https://cicada.example.ts.net"},
                       headers=_auth(master))
    assert made.status_code == 201, made.text
    assert client.get(BOOK, headers=_auth(made.json()["token"])).status_code == 401


def test_the_remote_listener_has_no_such_path(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    config.get_settings.cache_clear()
    db = remote_store.ConnectorStore(tmp_path / "remote" / "connectors.db")
    runtime = RemoteRuntime(post=lambda p, d: {"status": "resolved"}, sleep_running=lambda: False)
    listener = StarletteClient(remote_app.build_app(db, runtime=runtime))
    for method in ("GET", "PUT", "DELETE"):
        assert listener.request(method, BOOK).status_code == 404
    assert listener.get(f"{BOOK}/{'0' * 16}/photo").status_code == 404
    config.get_settings.cache_clear()


def test_no_tool_cli_row_or_v1_operation_reaches_it():
    """Every generated door is built from `cli_map`'s rows: none names the book's route or a contacts-card read."""
    for row in cli_map.ROWS:
        words = " ".join(str(part) for part in (row.tool, row.command, row.summary)).lower()
        assert "contacts-local" not in words and "contacts_book" not in words, row.tool
    tools = [row.tool for row in cli_map.ROWS if row.tool]
    assert not [tool for tool in tools if "contact" in tool], "no agent tool reads a contact card"
    from api.remote import agent_api

    paths = agent_api.openapi("https://cicada.example.ts.net")["paths"]
    assert paths and not [path for path in paths if "contact" in path.lower()]


def test_on_a_copy_the_book_stays_on_this_computer():
    assert replica_routes.ROUTES[f"PUT {BOOK}"] == replica_routes.LOCAL
    assert replica_routes.ROUTES[f"DELETE {BOOK}"] == replica_routes.LOCAL
    assert f"GET {BOOK}" not in replica_routes.GET_FROM_HOME
