"""The person chooses which folders Cicada's own agent may read (ruling 84, 2026-11-26): the rule proposes, the person disposes.

Invented folders only. The file-level rules (document kinds, no secret-shaped name, key-shaped text never stored) are proved to
hold for a folder the person turned on or added exactly as for one the rule chose.
"""
from __future__ import annotations

import json
import os
import re
import threading
import unicodedata
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
    assert refusal.status_code == 409 and "hidden" in refusal.json()["detail"]        # "you cannot choose this": the neighbouring routes' 409
    assert client.post("/settings/agent-folders", json={"path": ""}).status_code == 400    # no path at all is a malformed request
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
    assert auth._master_only("/settings/agent-folders", "GET")            # and so is reading it: the names say what is on this disk
    for route in ("PUT /settings/agent-folders", "POST /settings/agent-folders", "POST /settings/agent-folders/remove"):
        assert replica_routes.ROUTES[route] == replica_routes.REFUSE


def test_the_list_is_in_the_cli_and_never_writable_from_it():
    from api.services import cli_map

    rows = {r.command: r for r in cli_map.ROWS}
    row = rows[("agent", "folders")]
    assert row.exposed and not row.mutates and row.via == "backend"


# --- the class: a path or a name is compared whatever its casing and normal form (review of #950, blocker) ----------------------


def _case_sensitive_disk(tmp: Path) -> bool:
    (tmp / "cs-probe").mkdir()
    return not (tmp / "CS-PROBE").exists()


@pytest.mark.parametrize("typed", ["library", "LIBRARY", "LiBrArY", "library/Mail", "Library/mail", "documents/d", "DOCUMENTS/d",
                                   "downloads", "desktop", "Desktop", "PICTURES", "applications", "\uff4c\uff49\uff42\uff52\uff41\uff52\uff59"])
def test_a_differently_cased_protected_path_is_refused_like_the_exact_one(home, bank, typed):
    _put(home, {"Library/Mail/m.md": "x", "Library/Application Support/x.md": "x", "Documents/d/a.md": "x", "Downloads/a.md": "x",
                "Desktop/a.md": "x", "Pictures/a.md": "x", "Applications/a.md": "x", "Notes/a.md": "x"})
    with pytest.raises(af.FoldersError) as e:
        af.add(bank, str(home / typed), home=home)
    assert "macOS" in str(e.value) and e.value.status == 409
    assert not (auth.cicada_home() / af.FILENAME).exists()
    assert hf.location_problem(home, str(home / typed)) in ("protected", "missing")


def test_a_stored_decision_for_a_differently_cased_protected_folder_never_grants_it(home, bank):
    """A choice file from before the fix (or edited by hand) may name `library`: it is read as `Library`, and refused."""
    _put(home, {"Library/Application Support/x.md": "x", "Library/Mail/m.md": "x", "Notes/a.md": "x"})
    (auth.cicada_home()).mkdir(exist_ok=True)
    (auth.cicada_home() / af.FILENAME).write_text(json.dumps({"folders": {
        "library": {"state": "on", "added": True}, "LIBRARY/Mail": {"state": "on", "added": True}}}))
    g = af.listing(bank, home=home)
    assert not any(hf.fold(r).startswith(str(home).lower() + "/library") for r in g.roots)
    assert _by_id(g)["Library"].state == "protected" and "library/mail" not in {hf.fold(f.id) for f in g.folders}
    assert not hf.allowed_path(str(home / "Library" / "Application Support" / "x.md"), g.roots, refused=g.refused)
    assert not hf.allowed_path(str(home / "library" / "application support" / "x.md"), g.roots, refused=g.refused)


def test_the_stored_id_is_the_folders_true_name_and_one_folder_is_one_row(home, bank):
    _put(home, {"Work/My Notes/a.md": "x"})
    _rows, row = af.add(bank, str(home / "WORK" / "my notes"), home=home)
    assert row["id"] == "Work/My Notes"
    assert set(json.loads((auth.cicada_home() / af.FILENAME).read_text())["folders"]) == {"Work/My Notes"}
    af.add(bank, str(home / "work" / "MY NOTES"), home=home)               # the same folder again: still one decision, one row
    assert [r["id"] for r in af.rows(bank, home=home) if hf.fold_id(r["id"]) == hf.fold_id("work/my notes")] == ["Work/My Notes"]
    assert set(json.loads((auth.cicada_home() / af.FILENAME).read_text())["folders"]) == {"Work/My Notes"}
    # the app and the CLI may name it in any spelling
    rows = af.set_state(bank, "WORK/my notes", False)
    assert {r["id"]: r for r in rows}["Work/My Notes"]["state"] == "off"
    assert "Work/My Notes" not in {r["id"] for r in af.remove(bank, "work/MY NOTES")}


def test_a_decomposed_accent_is_the_same_name_as_the_composed_one(home, bank):
    composed, decomposed = "Caf\u00e9 Notes", unicodedata.normalize("NFD", "Caf\u00e9 Notes")
    assert composed != decomposed and hf.fold(composed) == hf.fold(decomposed)
    _put(home, {f"Work/{composed}/a.md": "x"})
    _rows, row = af.add(bank, str(home / "Work" / decomposed), home=home)
    assert row["id"] == f"Work/{composed}" or unicodedata.normalize("NFD", row["id"]) == f"Work/{decomposed}"
    # a decomposed accent inside a name that says secrets is the same word
    assert hf.secret_named("\uff33\uff25\uff23\uff32\uff25\uff34\uff33") and hf.secret_file("ID_RSA") and hf.secret_file("Id_Rsa")
    assert hf.fold("\u212a\u0045\u0059.PEM") == "key.pem"
    assert hf.secret_file("\u212a\u0045\u0059.PEM")


@pytest.mark.skipif(os.environ.get("CICADA_TEST_CASE_SENSITIVE") == "off", reason="needs a case-sensitive disk")
def test_on_a_case_sensitive_disk_a_second_folder_differing_in_case_is_its_own_unless_it_is_a_protected_name(home, bank, tmp_path):
    if not _case_sensitive_disk(tmp_path):
        pytest.skip("this disk is case-insensitive: the case that needs two folders cannot be made (the other tests cover it)")
    _put(home, {"Notes/a.md": "x", "notes/b.md": "x", "Library/a.md": "x", "library/b.md": "x"})
    _rows, row = af.add(bank, str(home / "notes"), home=home)
    assert row["id"] == "notes" and {r["id"] for r in af.rows(bank, home=home)} >= {"Notes", "notes"}
    af.set_state(bank, "notes", False)                  # each keeps its own decision
    by = _by_id(af.listing(bank, home=home))
    assert by["notes"].state == "off" and by["Notes"].state == "default"
    assert set(json.loads((auth.cicada_home() / af.FILENAME).read_text())["folders"]) == {"notes"}
    af.set_state(bank, "Notes", False)
    assert set(json.loads((auth.cicada_home() / af.FILENAME).read_text())["folders"]) == {"notes", "Notes"}
    with pytest.raises(af.FoldersError):                 # a protected name is protected in every casing: the safe side of a doubt
        af.add(bank, str(home / "library"), home=home)
    assert by["library"].state == "protected" and by["Library"].state == "protected"


def _glob(rule: str, path: str) -> bool:
    """A permission rule's path pattern as a case-sensitive glob: ``//`` an absolute path, ``**/`` any folders, ``*`` and ``?`` within one name."""
    inner = rule[len("Read("):-1]
    inner = inner[1:] if inner.startswith("//") else inner
    out, i = "", 0
    while i < len(inner):
        if inner.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif inner.startswith("**", i):
            out, i = out + ".*", i + 2
        else:
            c = inner[i]
            out += "[^/]*" if c == "*" else "[^/]" if c == "?" else re.escape(c)
            i += 1
    return re.fullmatch(out, path.lstrip("/")) is not None or re.fullmatch(out, path) is not None


def test_upper_case_variants_of_secret_names_are_denied_like_the_lower_case_ones(home, bank):
    """The harness's deny patterns are case-sensitive: a folder holding `ID_RSA`, `.ENV`, `Secrets/`, `KEY.PEM` is only safe when a rule
    names each spelling found in the complete walk (or a pattern that matches it)."""
    from api.services import harness_agent as ha

    _put(home, {"Docs/readme.md": "x", "Docs/ID_RSA": "k", "Docs/.ENV": "k", "Docs/Secrets/inner.md": "x", "Docs/KEY.PEM": "k",
                "Docs/Secrets.md": "x", "Docs/my-passwords.md": "x", "Docs/X.JSON": "{}", "Docs/CREDENTIALS.TXT": "x",
                "Docs/Wallet/a.md": "x", "Docs/PRIVATE/a.md": "x", "Docs/sub/Token List.txt": "x", "Docs/sub/ok.md": "x"})
    g = af.listing(bank, home=home)
    assert str(home / "Docs") in g.roots
    rules = ha.settings_for(ha.Policy(ha.PRIVATE, roots=g.roots, refused=g.refused, deny=g.deny))["permissions"]["deny"]
    denied = lambda rel: any(r.startswith("Read(") and _glob(r, str(home / "Docs" / rel)) for r in rules)   # noqa: E731
    for rel in ("ID_RSA", ".ENV", "Secrets/inner.md", "Secrets/anything-later.md", "KEY.PEM", "Secrets.md", "my-passwords.md", "X.JSON",
                "CREDENTIALS.TXT", "Wallet/a.md", "PRIVATE/a.md", "sub/Token List.txt"):
        assert denied(rel), rel
        assert not hf.allowed_path(str(home / "Docs" / rel), g.roots, refused=g.refused), rel
    assert not denied("readme.md") and not denied("sub/ok.md")
    assert hf.allowed_path(str(home / "Docs" / "readme.md"), g.roots, refused=g.refused)


def test_a_folder_that_is_a_notes_vault_in_any_case_and_holds_ID_RSA_is_not_one(home, bank):
    _put(home, {"Vault/a.md": "x", "Vault/b.md": "x", "Vault/ID_RSA": "k"})
    assert _by_id(af.listing(bank, home=home))["Vault"].why == "secrets"
    _put(home, {"vaults/a.md": "x", "vaults/b.md": "x", "vaults/KEY.PEM": "k"})
    assert _by_id(af.listing(bank, home=home))["vaults"].why == "secrets"


def test_a_refused_path_is_refused_in_any_casing(home, bank, tmp_path):
    bank_in_home = home / "Work" / "bank"
    bank_in_home.mkdir(parents=True)
    (bank_in_home / "n.md").write_text("x")
    refused = (str(bank_in_home),)
    assert hf.under(str(bank_in_home / "n.md"), str(bank_in_home)) and hf.under(str(home / "work" / "BANK" / "n.md"), str(bank_in_home))
    assert not hf.allowed_path(str(bank_in_home / "n.md"), (str(home / "Work"),), refused=refused)
    assert not hf.allowed_path(str(home / "work" / "BANK" / "n.md"), (str(home / "Work"),), refused=refused)


# --- L1: a folder inside a granted one under a name that one's rules refuse -----------------------------------------------------


def test_a_folder_below_a_granted_one_under_a_secret_name_is_not_added_and_says_why(home, bank):
    _put(home, {"Notes/a.md": "x", "Notes/secrets/inbox/b.md": "x", "Notes/ideas/c.md": "x"})
    with pytest.raises(af.FoldersError) as e:
        af.add(bank, str(home / "Notes" / "secrets"), home=home)
    assert "Inside a folder that is on" in str(e.value) and e.value.status == 409
    with pytest.raises(af.FoldersError):
        af.add(bank, str(home / "Notes" / "secrets" / "inbox"), home=home)
    assert not (auth.cicada_home() / af.FILENAME).exists()
    _rows, row = af.add(bank, str(home / "Notes" / "ideas"), home=home)       # an ordinary folder below a granted one is only redundant
    assert row["state"] == "on" and row["granted"]


def test_a_folder_added_while_its_parent_was_off_closes_when_the_parent_is_turned_on_and_says_so(home, bank):
    _put(home, {"Notes/a.md": "x", "Notes/secrets/inbox/b.md": "x"})
    af.set_state(bank, "Notes", False)
    _rows, row = af.add(bank, str(home / "Notes" / "secrets"), home=home)
    assert row["state"] == "on" and row["granted"]
    assert str(home / "Notes" / "secrets") in af.listing(bank, home=home).roots
    af.set_state(bank, "Notes", True)
    g = af.listing(bank, home=home)
    row = _by_id(g)["Notes/secrets"]
    assert row.state == "refused" and row.why == "shadowed" and row.locked and not row.granted and "Inside a folder that is on" in row.reason
    assert str(home / "Notes" / "secrets") not in g.roots and str(home / "Notes") in g.roots
    assert not hf.allowed_path(str(home / "Notes" / "secrets" / "inbox" / "b.md"), g.roots, refused=g.refused)
    # the decision is kept: turn the parent off and the folder reads on its own again; removing it is always possible
    af.set_state(bank, "Notes", False)
    assert _by_id(af.listing(bank, home=home))["Notes/secrets"].granted
    af.set_state(bank, "Notes", True)
    assert "Notes/secrets" not in {r["id"] for r in af.remove(bank, "Notes/secrets")}


# --- L2: a link that leaves a vault ---------------------------------------------------------------------------------------------


def test_a_vault_holding_a_link_out_of_it_is_offered_off_with_the_reason(home, bank, tmp_path):
    _put(home, {"vault/a.md": "x", "vault/b.md": "x", "keys-elsewhere/id_rsa": "k", "keys-elsewhere/c.md": "x"})
    (home / "vault" / "link.md").symlink_to(home / "keys-elsewhere" / "c.md")
    row = _by_id(af.listing(bank, home=home))["vault"]
    assert row.state == "refused" and row.why == "vault_link" and not row.granted and not row.locked and "link" in row.reason
    (home / "vault" / "link.md").unlink()
    (home / "vault" / "folder-link").symlink_to(home / "keys-elsewhere")
    assert _by_id(af.listing(bank, home=home))["vault"].why == "vault_link"
    (home / "vault" / "folder-link").unlink()
    (home / "vault" / ".hidden-link").symlink_to(tmp_path)
    assert _by_id(af.listing(bank, home=home))["vault"].why == "vault_link"
    (home / "vault" / ".hidden-link").unlink()
    (home / "vault" / "inside.md").symlink_to(home / "vault" / "a.md")           # a link that stays inside is no leak
    assert _by_id(af.listing(bank, home=home))["vault"].state == "default"


def test_a_vault_with_a_link_out_turned_on_by_the_person_still_never_reads_through_the_link(home, bank):
    from api.services import harness_agent as ha

    _put(home, {"vault/a.md": "x", "keys-elsewhere/c.md": "x"})
    (home / "vault" / "link.md").symlink_to(home / "keys-elsewhere" / "c.md")
    (home / "vault" / "dirlink").symlink_to(home / "keys-elsewhere")
    af.set_state(bank, "vault", True)
    g = af.listing(bank, home=home)
    assert str(home / "vault") in g.roots and _by_id(g)["vault"].state == "on"
    rules = ha.settings_for(ha.Policy(ha.PRIVATE, roots=g.roots, refused=g.refused, deny=g.deny))["permissions"]["deny"]
    assert any(_glob(r, str(home / "vault" / "link.md")) for r in rules if r.startswith("Read("))
    assert any(_glob(r, str(home / "vault" / "dirlink" / "c.md")) for r in rules if r.startswith("Read("))
    assert not hf.allowed_path(str(home / "vault" / "link.md"), g.roots, refused=g.refused)


# --- L3: the file keeps what it does not know, and two changes at once both land -----------------------------------------------


def test_a_save_keeps_every_key_it_does_not_know(home, bank):
    _layout(home)
    (auth.cicada_home()).mkdir(exist_ok=True)
    (auth.cicada_home() / af.FILENAME).write_text(json.dumps({"version": 3, "note": {"x": 1}, "folders": {
        "Notes": {"state": "off", "added": False, "day": "2026-11-01", "colour": "blue"},
        "later": {"state": "maybe", "added": True}}}))
    af.set_state(bank, "vault", False)
    doc = json.loads((auth.cicada_home() / af.FILENAME).read_text())
    assert doc["version"] == 3 and doc["note"] == {"x": 1}
    assert doc["folders"]["Notes"]["colour"] == "blue" and doc["folders"]["later"] == {"state": "maybe", "added": True}
    assert doc["folders"]["vault"]["state"] == "off"


def test_two_changes_at_once_both_land(home, bank, monkeypatch):
    """A reads the file (its last read before saving), B changes and saves, A saves: without a lock B's change is lost."""
    _layout(home)
    seen = []
    last_read = threading.Event()
    real_load = af.load

    def slow_load():
        got = real_load()
        if threading.current_thread().name == "A":
            seen.append(1)
            if len(seen) == 2:                            # the read a save is made from (the first only judges the row)
                last_read.set()
                threading.Event().wait(0.5)               # B runs now, unless the lock A holds keeps it out
        return got

    monkeypatch.setattr(af, "load", slow_load)
    errors: list[BaseException] = []

    def run(folder):
        try:
            af.set_state(bank, folder, False)
        except BaseException as exc:                   # noqa: BLE001
            errors.append(exc)

    a = threading.Thread(target=run, args=("vault",), name="A")
    b = threading.Thread(target=run, args=("Notes",), name="B")
    a.start()
    assert last_read.wait(5)
    b.start()
    a.join(10)
    b.join(10)
    assert not errors
    assert set(json.loads((auth.cicada_home() / af.FILENAME).read_text())["folders"]) == {"vault", "Notes"}


def test_a_change_waits_for_the_one_holding_the_file(home, bank):
    _layout(home)
    done = threading.Event()
    with af._edit() as folders:
        folders["Notes"] = {"state": "off", "added": False, "day": "2026-11-01"}
        t = threading.Thread(target=lambda: (af.set_state(bank, "vault", False), done.set()))
        t.start()
        assert not done.wait(0.4)                         # held out while the first change is open
    assert done.wait(10)
    t.join(10)
    assert set(json.loads((auth.cicada_home() / af.FILENAME).read_text())["folders"]) == {"vault", "Notes"}


# --- L5: reading the list is the server's own token's too -----------------------------------------------------------------------


def test_a_device_token_cannot_read_the_list_and_the_servers_own_token_can(client, home, monkeypatch):
    from api.services import device_tokens

    monkeypatch.setenv("CICADA_API_AUTH", "on")
    _layout(home)
    _dev, token = device_tokens.store().create("laptop-example")
    for method, body in (("get", None), ("put", {"folder": "vault", "on": False}), ("post", {"path": str(home / "Notes")})):
        r = getattr(client, method)("/settings/agent-folders", headers={"Authorization": f"Bearer {token}"}, **({"json": body} if body else {}))
        assert r.status_code == 403, method
    assert client.get("/settings/agent-folders").status_code == 401
    assert client.get("/settings/agent-folders", headers={"Authorization": f"Bearer {auth.get_token()}"}).status_code == 200


def test_a_path_spelled_as_the_disk_resolves_a_home_that_sits_behind_a_link_is_below_the_home(tmp_path, monkeypatch, bank):
    """The system folder panel answers with the resolved path (``/var/...`` for a home spelled ``/private/var/...``): the same folder, so
    a folder of it is added, a protected one is refused as protected (not as outside the home), and a path elsewhere stays outside."""
    real = tmp_path / "real"
    (real / "home" / "Notes" / "Project docs").mkdir(parents=True)
    (real / "home" / "Documents").mkdir()
    (real / "home" / "Notes" / "Project docs" / "p.md").write_text("x")
    (tmp_path / "other").mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    home = link / "home"                                    # the home as the backend knows it, behind a link
    cicada = tmp_path / "cicada-home"
    cicada.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CICADA_HOME", str(cicada))
    resolved = real / "home"                                # the spelling a panel answers with
    assert hf.resolve_location(home, str(resolved / "Notes" / "Project docs"))[0] == ""
    assert hf.resolve_location(home, str(resolved / "Documents"))[0] == "protected"
    assert hf.resolve_location(home, str(tmp_path / "other"))[0] == "outside"
    assert hf.resolve_location(home, str(resolved))[0] == "outside"          # the home itself is still no folder
    rows, row = af.add(bank, str(resolved / "Notes" / "Project docs"), home=home)
    assert row["id"] == "Notes/Project docs" and row["state"] == "on" and row["granted"]
    with pytest.raises(af.FoldersError) as exc:
        af.add(bank, str(resolved / "Documents"), home=home)
    assert exc.value.status == 409 and exc.value.args[0] == af.ADD_REFUSALS["protected"]
