"""The person chooses which folders Cicada's own agent may read (ruling 84, 2026-11-26): the rule proposes, the person disposes.

Invented folders only. The file-level rules (document kinds, no secret-shaped name, key-shaped text never stored) are proved to
hold for a folder the person turned on or added exactly as for one the rule chose.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from api.services import agent_folders as af, auth, harness_files as hf

FAKE_KEY = "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC\n-----END PRIVATE KEY-----\n"


def _put(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    bank = tmp_path / "bank"
    bank.mkdir()
    cicada = tmp_path / "cicada-home"
    cicada.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setenv("CICADA_HOME", str(cicada))
    return h


@pytest.fixture
def bank(tmp_path):
    return tmp_path / "bank"


def _layout(h: Path) -> None:
    _put(h, {
        "vault/Daily/2026-11-01.md": "met the team", "vault/Projects/plan.md": "the plan", "vault/Projects/todo.txt": "later",
        "vault/attachments/scan.png": "x",
        "Notes/a.md": "x", "Notes/b.md": "x",
        "secrets/fake.key": FAKE_KEY, "secrets/cloud.json": "{}", "secrets/readme.md": "about these",
        "code/app/main.py": "print()", "code/notes.md": "hello",
        "Papers/p.pdf": "x",
    })


def _by_id(grant: hf.Grant) -> dict[str, hf.Folder]:
    return {f.id: f for f in grant.folders}


# --- the rule's change: a vault of notes is a notes folder ---------------------------------------------------------------


def test_a_vault_of_notes_is_on_by_default_and_every_other_secret_name_stays_off(home, bank):
    _layout(home)
    _put(home, {"Vault Keys/a.md": "x", "my-passwords/a.md": "x", "Private/a.md": "x"})
    g = af.listing(bank, home=home)
    rows = _by_id(g)
    assert rows["vault"].state == "default" and rows["vault"].why == "notes_vault" and rows["vault"].granted
    assert "notes only" in rows["vault"].reason or "only notes" in rows["vault"].reason
    assert str(home / "vault") in g.roots
    for name in ("secrets", "Vault Keys", "my-passwords", "Private"):
        assert rows[name].state == "refused" and rows[name].why == "secrets" and not rows[name].granted and not rows[name].locked
        assert "name says secrets" in rows[name].reason
    assert rows["code"].why == "tooling" and rows["Notes"].state == "default" and rows["Notes"].why == ""
    # the vault's own non-document files are still denied, like any granted folder's
    assert "Read(//**/*.png)" in g.deny and "Read(//**/*.pdf)" not in g.deny


@pytest.mark.parametrize("extra", [
    {"deploy.pem": "x"}, {"id_rsa": "x"}, {".env": "A=1"}, {"credentials.md": "x"}, {"cloud.json": "{}"}, {"settings.yaml": "a: 1"},
    {"keepass.kdbx": "x"}, {".ssh/config": "x"}, {".aws/config": "x"}, {"sub/secrets/a.md": "x"}, {"run.py": "x"}])
def test_a_vault_that_holds_anything_key_like_stays_refused(home, bank, extra):
    _put(home, {"vault/a.md": "x", "vault/b.md": "x", **{f"vault/{k}": v for k, v in extra.items()}})
    row = _by_id(af.listing(bank, home=home))["vault"]
    assert row.state == "refused" and row.why == "secrets" and not row.granted


def test_a_vault_that_is_mostly_not_notes_or_holds_a_bank_or_is_too_large_is_not_proposed(home, bank, monkeypatch):
    _put(home, {"vault/a.md": "x", "vault/1.png": "x", "vault/2.png": "x", "vault/3.png": "x",
                "vaults/a.md": "x", "vaults/m/entities/e.md": "x", "vaults/m/episodes/e.md": "x"})
    rows = _by_id(af.listing(bank, home=home))
    assert rows["vault"].state == "refused" and rows["vaults"].why == "cicada" and rows["vaults"].locked
    _put(home, {"Big vault/%d.md" % i: "x" for i in range(30)})
    monkeypatch.setattr(hf, "MAX_ENTRIES", 10)
    assert _by_id(af.listing(bank, home=home))["Big vault"].why == "too_large"


def test_a_name_that_says_more_than_vault_is_never_a_notes_folder(home, bank):
    for name in ("vault-keys", "vault passwords", "tokens vault", "vault_secrets", "VaultCredentials"):
        assert not hf.vault_named(name), name
    for name in ("vault", "Vault", "vaults", "Obsidian Vault", "my-vault-2026"):
        assert hf.vault_named(name), name


# --- the person's choice ---------------------------------------------------------------------------------------------


def test_what_the_person_turned_off_stays_off_and_what_they_turned_on_stays_on(home, bank):
    _layout(home)
    rows = af.set_state(bank, "vault", False)
    assert {r["id"]: r for r in rows}["vault"]["state"] == "off"
    rows = af.set_state(bank, "secrets", True)
    row = {r["id"]: r for r in rows}["secrets"]
    assert row["state"] == "on" and row["granted"] and "Turned on by you" in row["reason"]
    # a later listing, a later process: the file says it
    g = af.listing(bank, home=home)
    assert str(home / "secrets") in g.roots and str(home / "vault") not in g.roots
    assert _by_id(g)["vault"].state == "off" and ("vault", "off") in g.skipped
    stored = json.loads((auth.cicada_home() / af.FILENAME).read_text())["folders"]
    assert set(stored) == {"vault", "secrets"} and stored["vault"]["state"] == "off" and "day" in stored["secrets"]
    assert oct((auth.cicada_home() / af.FILENAME).stat().st_mode & 0o777) == "0o600"
    # putting a proposal back to what the rule says leaves no decision behind
    af.set_state(bank, "vault", True)
    af.set_state(bank, "secrets", False)
    assert json.loads((auth.cicada_home() / af.FILENAME).read_text()) == {"folders": {}}
    assert _by_id(af.listing(bank, home=home))["vault"].state == "default"


def test_a_folder_turned_on_keeps_the_file_rules(home, bank):
    """The secrets folder turned on: documents only, never a key file, never anything that looks like key material."""
    _layout(home)
    _put(home, {"secrets/notes.txt": "plain words", "secrets/private/inner.md": "x", "secrets/.env": "A=1", "secrets/id_rsa": FAKE_KEY})
    af.set_state(bank, "secrets", True)
    g = af.listing(bank, home=home)
    root = str(home / "secrets")
    assert root in g.roots
    ok = lambda rel: hf.allowed_path(str(home / "secrets" / rel), g.roots, refused=g.refused)   # noqa: E731
    assert ok("notes.txt") and ok("readme.md")
    assert not ok("fake.key") and not ok("cloud.json") and not ok("id_rsa") and not ok(".env") and not ok("private/inner.md")
    from api.services import harness_agent as ha

    rules = ha.settings_for(ha.Policy(ha.PRIVATE, roots=g.roots, refused=g.refused, deny=g.deny))["permissions"]["deny"]
    assert {"Read(//**/*.key)", "Read(//**/*.json)"} <= set(rules)
    assert {f"Read(/{root}/**/id_*)", f"Read(/{root}/**/.env*)", f"Read(/{root}/**/secret*)"} <= set(rules)
    # a name rule is scoped to the folder: never root independent, or a folder called `secrets` could not be read at all
    assert not {"Read(//**/secret*)", "Read(//**/id_*)", "Read(//**/.env*)", "Read(//**/credential*)"} & set(rules)
    assert hf.looks_like_key(FAKE_KEY) and not hf.looks_like_key("plain words")
    assert any(r.endswith("/secrets/**/.*)") for r in rules) and any(r.endswith("/secrets/**/private/**)") for r in rules)


def test_a_folder_added_by_hand_is_granted_even_when_the_rule_would_refuse_it_and_keeps_the_file_rules(home, bank):
    _layout(home)
    _put(home, {"code/docs/guide.md": "x", "code/docs/.hidden.md": "x", "code/docs/keys/a.md": "x", "code/docs/run.sh": "x",
                "code/docs/token.txt": "x"})
    assert _by_id(af.listing(bank, home=home))["code"].why == "tooling"
    rows, row = af.add(bank, str(home / "code" / "docs"), home=home)
    assert row["id"] == "code/docs" and row["state"] == "on" and row["added"] and row["granted"]
    g = af.listing(bank, home=home)
    assert str(home / "code" / "docs") in g.roots and str(home / "code") not in g.roots
    ok = lambda rel: hf.allowed_path(str(home / "code" / "docs" / rel), g.roots, refused=g.refused)   # noqa: E731
    assert ok("guide.md") and not ok(".hidden.md") and not ok("keys/a.md") and not ok("run.sh") and not ok("token.txt")
    assert "Read(//**/*.sh)" in g.deny
    # an added folder that is turned off is still listed; removing forgets it
    rows = af.set_state(bank, "code/docs", False)
    assert {r["id"]: r for r in rows}["code/docs"]["state"] == "off"
    assert "code/docs" not in {r["id"] for r in af.remove(bank, "code/docs")}
    with pytest.raises(af.FoldersError):
        af.remove(bank, "vault")        # a proposed folder is switched, never removed


def test_the_rules_judge_an_added_folders_own_name_never_its_parents(home, bank):
    """A folder below a parent called `cicada-stuff` or `secrets` is judged as what it is called and holds: the row shows its place."""
    _put(home, {"cicada-stuff/docs/a.md": "x", "secrets/inbox/a.md": "x", "Work/cicada-bench/a.md": "x"})
    _rows, row = af.add(bank, str(home / "cicada-stuff" / "docs"), home=home)
    assert row["id"] == "cicada-stuff/docs" and row["name"] == "cicada-stuff/docs" and row["state"] == "on" and not row["locked"]
    _rows, row = af.add(bank, str(home / "secrets" / "inbox"), home=home)
    assert row["state"] == "on" and row["why"] == ""
    with pytest.raises(af.FoldersError):
        af.add(bank, str(home / "Work" / "cicada-bench"), home=home)           # named for Cicada itself: its own


def test_adding_a_top_level_folder_the_rule_refuses_turns_it_on(home, bank):
    _layout(home)
    _rows, row = af.add(bank, str(home / "secrets"), home=home)
    assert row["id"] == "secrets" and row["state"] == "on" and not row["added"]
    _rows, again = af.add(bank, str(home / "Notes"), home=home)       # already on by default: nothing to remember
    assert again["state"] == "default"
    assert "Notes" not in json.loads((auth.cicada_home() / af.FILENAME).read_text())["folders"]


# --- what no choice opens ----------------------------------------------------------------------------------------------


def test_cicada_own_and_too_large_folders_cannot_be_turned_on(home, bank, monkeypatch):
    _put(home, {"cicada-bench/a.md": "x", "oldbank/entities/e.md": "x", "oldbank/episodes/x.md": "x", "Big/a.md": "x"})
    for i in range(30):
        _put(home, {f"Big/{i}.md": "x"})
    monkeypatch.setattr(hf, "MAX_ENTRIES", 10)
    for fid, why in (("cicada-bench", "cicada"), ("oldbank", "cicada"), ("Big", "too_large")):
        row = _by_id(af.listing(bank, home=home))[fid]
        assert row.locked and row.state == "refused" and row.why == why
        with pytest.raises(af.FoldersError) as e:
            af.set_state(bank, fid, True)
        assert e.value.status == 409
    # a stored decision from before cannot override it either
    (auth.cicada_home() / af.FILENAME).write_text(json.dumps({"folders": {"oldbank": {"state": "on", "added": False}}}))
    assert str(home / "oldbank") not in af.listing(bank, home=home).roots


def test_protected_folders_are_listed_closed(home, bank):
    _put(home, {"Documents/a.md": "x", "Desktop/a.md": "x", "Library/a.md": "x", "Notes/a.md": "x"})
    rows = _by_id(af.listing(bank, home=home))
    for name in ("Documents", "Desktop", "Library"):
        assert rows[name].state == "protected" and rows[name].locked and not rows[name].granted
    assert "macOS" in rows["Documents"].reason and rows["Library"].why == "system" and rows["Documents"].why == "protected"
    with pytest.raises(af.FoldersError):
        af.set_state(bank, "Documents", True)
    # the person's own shell (`attended`, the dry run) may read the user folders, never Library
    attended = _by_id(af.listing(bank, home=home, attended=True))
    assert attended["Documents"].granted and attended["Library"].state == "protected"


@pytest.mark.parametrize("make, expect", [
    (lambda h, t: str(t / "elsewhere"), "inside your home"),
    (lambda h, t: str(h), "inside your home"),
    (lambda h, t: str(h / ".hidden-folder"), "hidden"),
    (lambda h, t: str(h / "Notes" / ".git"), "hidden"),
    (lambda h, t: str(h / "Library" / "Mail"), "macOS"),
    (lambda h, t: str(h / "Documents" / "Notes"), "macOS"),
    (lambda h, t: str(h / "Notes" / "missing"), "not a folder"),
    (lambda h, t: str(h / "Notes" / "a.md"), "not a folder"),
    (lambda h, t: str(h / "link-out"), "link"),
    (lambda h, t: str(h / "link-out" / "inner"), "link"),
    (lambda h, t: str(h / "link-in" / "inner"), "link"),
    (lambda h, t: str(h / "oldbank"), "Cicada's own"),
    (lambda h, t: str(h / "Notes" / ".." / ".."), "inside your home"),
    (lambda h, t: "", "Choose a folder"),
    (lambda h, t: "relative/path", "full path"),
])
def test_an_added_path_is_refused_with_the_reason_in_words(home, bank, tmp_path, make, expect):
    _put(home, {"Notes/a.md": "x", "Library/Mail/m.md": "x", "Documents/Notes/a.md": "x",
                "oldbank/entities/e.md": "x", "oldbank/episodes/x.md": "x", ".hidden-folder/a.md": "x", "Notes/.git/HEAD": "x"})
    (tmp_path / "elsewhere" / "inner").mkdir(parents=True)
    (home / "link-out").symlink_to(tmp_path / "elsewhere")
    (home / "link-in").symlink_to(home / "Notes")
    (home / "Notes" / "inner").mkdir()
    with pytest.raises(af.FoldersError) as e:
        af.add(bank, make(home, tmp_path), home=home)
    assert expect in str(e.value)
    assert not (auth.cicada_home() / af.FILENAME).exists()          # a refusal leaves nothing behind


def test_an_added_path_inside_cicada_home_or_the_bank_or_holding_them_is_refused(home, bank, tmp_path, monkeypatch):
    inside = home / "Work"
    (inside / "bank").mkdir(parents=True)
    (inside / "bank" / "notes.md").write_text("x")
    cicada = home / "Work" / "cicada-data"
    cicada.mkdir()
    monkeypatch.setenv("CICADA_HOME", str(cicada))
    for target in (inside / "bank", cicada, inside):
        with pytest.raises(af.FoldersError) as e:
            af.add(inside / "bank", str(target), home=home)
        assert "Cicada's own" in str(e.value)


def test_an_added_folder_on_another_disk_or_too_large_to_walk_is_refused(home, bank, monkeypatch):
    _put(home, {"Notes/a.md": "x", "Big/a.md": "x"})
    for i in range(30):
        _put(home, {f"Big/{i}.md": "x"})
    monkeypatch.setattr(hf, "MAX_ENTRIES", 10)
    with pytest.raises(af.FoldersError) as e:
        af.add(bank, str(home / "Big"), home=home)
    assert "too large" in str(e.value)
    monkeypatch.setattr(hf, "_same_device", lambda a, b: False)
    with pytest.raises(af.FoldersError) as e:
        af.add(bank, str(home / "Notes"), home=home)
    assert "another disk" in str(e.value)


def test_a_tilde_path_is_the_homes_and_a_vanished_added_folder_drops_off_the_list(home, bank, monkeypatch):
    _put(home, {"Work/notes/a.md": "x"})
    monkeypatch.setenv("HOME", str(home))
    rows, row = af.add(bank, "~/Work/notes", home=home)
    assert row["id"] == "Work/notes"
    import shutil
    shutil.rmtree(home / "Work")
    assert "Work/notes" not in {f.id for f in af.listing(bank, home=home).folders}


# --- the run uses it ---------------------------------------------------------------------------------------------------------


def test_a_runs_grant_follows_the_stored_choice_on_every_call(home, bank, monkeypatch):
    """`harness_questions.home_grant` reads the file each time: the person's change reaches the next run with no restart."""
    from api.services import harness_questions as hq

    _layout(home)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    first = hq.home_grant(bank, attended=False)
    assert str(home / "vault") in first.roots and str(home / "secrets") not in first.roots
    af.set_state(bank, "vault", False)
    af.set_state(bank, "secrets", True)
    second = hq.home_grant(bank, attended=False)
    assert str(home / "secrets") in second.roots and str(home / "vault") not in second.roots


def test_the_dry_runs_lines_name_each_folder_its_state_and_reason(home, bank):
    _layout(home)
    af.set_state(bank, "Notes", False)
    lines = af.describe(af.listing(bank, home=home))
    text = "\n".join(lines)
    assert "vault: on (default)." in text and "Notes: off (you)." in text and "secrets: off. Its name says secrets" in text


def test_a_file_that_cannot_be_read_is_no_decisions(home):
    (auth.cicada_home()).mkdir(exist_ok=True)
    for text in ("not json", "[]", '{"folders": []}', '{"folders": {"a": 3, "b": {"state": "maybe"}}}'):
        (auth.cicada_home() / af.FILENAME).write_text(text)
        assert af.load() == {}


# --- the routes ------------------------------------------------------------------------------------------------------------


@pytest.fixture
def client(home, bank, monkeypatch):
    from fastapi.testclient import TestClient

    from api import config, main

    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    config.get_settings.cache_clear()
    try:
        yield TestClient(main.app)
    finally:
        config.get_settings.cache_clear()


def test_the_routes_list_change_add_and_remove(client, home):
    _layout(home)
    body = client.get("/settings/agent-folders").json()
    by = {f["id"]: f for f in body["folders"]}
    assert by["vault"]["state"] == "default" and by["vault"]["granted"] is True and by["secrets"]["state"] == "refused"
    assert all("path" not in f for f in body["folders"]) and str(home) not in json.dumps(body)
    body = client.put("/settings/agent-folders", json={"folder": "vault", "on": False}).json()
    assert {f["id"]: f for f in body["folders"]}["vault"]["state"] == "off"
    assert client.put("/settings/agent-folders", json={"folder": "nowhere", "on": True}).status_code == 404
    body = client.post("/settings/agent-folders", json={"path": str(home / "code" / "app")}).json()
    assert {f["id"]: f for f in body["folders"]}["code/app"]["added"] is True
    refusal = client.post("/settings/agent-folders", json={"path": str(home / ".ssh")})
    assert refusal.status_code == 400 and "hidden" in refusal.json()["detail"]
    body = client.post("/settings/agent-folders/remove", json={"folder": "code/app"}).json()
    assert "code/app" not in {f["id"] for f in body["folders"]}
    assert client.post("/settings/agent-folders/remove", json={"folder": "vault"}).status_code == 404


def test_a_locked_row_answers_409_with_its_reason(client, home):
    _put(home, {"Documents/a.md": "x"})
    r = client.put("/settings/agent-folders", json={"folder": "Documents", "on": True})
    assert r.status_code == 409 and "macOS" in r.json()["detail"]


def test_only_the_masters_token_may_change_the_list_and_a_copy_never_does():
    from api.services import replica_routes

    for method in ("PUT", "POST"):
        assert auth._master_only("/settings/agent-folders", method) and auth._master_only("/settings/agent-folders/remove", method)
    assert not auth._master_only("/settings/agent-folders", "GET")        # reading the list is open like the other settings
    for route in ("PUT /settings/agent-folders", "POST /settings/agent-folders", "POST /settings/agent-folders/remove"):
        assert replica_routes.ROUTES[route] == replica_routes.REFUSE


def test_the_list_is_in_the_cli_and_never_writable_from_it():
    from api.services import cli_map

    rows = {r.command: r for r in cli_map.ROWS}
    row = rows[("agent", "folders")]
    assert row.exposed and not row.mutates and row.via == "backend"
