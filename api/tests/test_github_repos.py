"""G230: GitHub repositories on the graph — the tier-2 connector, the repository pages, the README preview, the doors.

Hermetic: no real account, no network. GitHub's API is a fake that answers with the recorded shapes in
`fixtures/connectors/github_api.json` (placeholders only) and records every request it was sent.
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import subprocess
from pathlib import Path

import pytest

from api.services import bank_index, history_index, markdown_parser, sleep_cycle, source_refresh, sync_state
from api.services import github_repos
from api.services.connections import secrets
from api.services.connectors import ADAPTERS, github, tier2

FIX = json.loads((Path(__file__).parent / "fixtures" / "connectors" / "github_api.json").read_text())
TOKEN = "placeholder-token-0123456789abcdef"


class FakeGitHub:
    """api.github.com as recorded: every request kept; ``fix`` is the account's state (copied, so a test edits it)."""

    def __init__(self, fix=None, *, status: int | None = None):
        self.fix = copy.deepcopy(fix or FIX)
        self.status = status
        self.calls: list[dict] = []

    async def __call__(self, method, url, *, headers, params=None, json=None):
        self.calls.append({"method": method, "url": url, "headers": dict(headers), "params": dict(params or {})})
        if self.status:
            return tier2.Response(self.status, {"message": "nope"}, {})
        assert url.startswith(github.API_BASE)
        path = url[len(github.API_BASE):]
        page = int((params or {}).get("page") or 1)
        if path == "user":
            return tier2.Response(200, self.fix["user"], {})
        if path == "user/repos":
            return tier2.Response(200, self.fix["owned"] if page == 1 else [], {})
        if path == "user/starred":
            assert headers.get("Accept") == "application/vnd.github.star+json"
            return tier2.Response(200, self.fix["starred"] if page == 1 else [], {})
        if path.startswith("repos/") and path.endswith("/readme"):
            if path == "repos/example-org/widget-kit/readme":
                return tier2.Response(200, self.fix["readme_widget_kit"], {})
            return tier2.Response(404, {"message": "Not Found"}, {})
        if path.startswith("repos/"):
            full = path[len("repos/"):]
            for row in [*self.fix["owned"], *(s["repo"] for s in self.fix["starred"])]:
                if row["full_name"] == full:
                    return tier2.Response(200, row, {})
            return tier2.Response(404, {"message": "Not Found"}, {})
        return tier2.Response(404, {"message": "Not Found"}, {})


def _git(memory: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=memory, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def bank(tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    for sub in ("episodes", "entities", "sources"):
        (memory / sub).mkdir(parents=True)
    for args in (("init", "-q"), ("config", "user.email", "t@example.com"), ("config", "user.name", "t")):
        _git(memory, *args)
    (memory / ".gitkeep").write_text("")
    _git(memory, "add", "-A")
    _git(memory, "commit", "-q", "-m", "start")
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(sleep_cycle, "is_writing", lambda: False)
    monkeypatch.delenv(github.TOKEN_ENV, raising=False)
    yield memory
    os.environ.pop(github.TOKEN_ENV, None)


def _connect():
    secrets.set_secret(github.TOKEN_ENV, TOKEN)


def _sync(memory, server):
    return asyncio.run(github.sync(memory, http_fn=server))


def _pages(memory) -> dict[str, dict]:
    out = {}
    for path in sorted((memory / "entities").glob("*.md")):
        parsed = markdown_parser.parse(path)
        block = parsed.frontmatter.get("github") or {}
        out[str(block.get("full_name") or path.stem)] = {"fm": parsed.frontmatter, "id": path.stem}
    return out


def _episodes(memory) -> list[dict]:
    return [markdown_parser.parse(p).frontmatter for p in sorted((memory / "episodes").glob("*.md"))]


def _files(memory) -> set[str]:
    return {str(p.relative_to(memory)) for p in memory.rglob("*") if p.is_file() and ".git" not in p.parts}


# --- the sync ------------------------------------------------------------------------------------------------------


def test_github_is_a_tier_two_connector_off_until_a_token_is_pasted(bank):
    assert ADAPTERS["github"] is github and github.TIER == 2 and not github.is_connected()
    result = _sync(bank, FakeGitHub())
    assert result["status"] == "skipped" and result["reason"] == "not connected"
    assert github.READS.startswith("Read-only") and "personal-access-tokens" not in github.READS   # said once


def test_a_first_sync_offers_owned_repositories_and_saves_starred_ones_as_quiet_pages(bank):
    _connect()
    server = FakeGitHub()
    result = _sync(bank, server)
    assert result["status"] == "ok", result
    episodes = _episodes(bank)
    owned = [e for e in episodes if e.get("origin") == github.ORIGIN_OWNED]
    assert sorted(e["source_id"] for e in owned) == ["github:owned:501", "github:owned:502"]
    # A repository the person owns is a record GitHub keeps: index-only, never read by a model, and no page.
    assert all(history_index.is_index_only(e) and e["processed"] is True and e["processed_by"] == "index"
               for e in owned)
    pages = _pages(bank)
    assert set(pages) == {"example-org/widget-kit", "ada-example/tiny-lib"}       # starred only; owned mint nothing
    assert not any(p["fm"].get("type") == "project" for p in pages.values())
    kit = pages["example-org/widget-kit"]["fm"]
    assert kit["type"] == "media" and kit["media"]["kind"] == "repository"
    assert kit["github"]["starred"] is True and kit["github"]["starred_at"].startswith("2026-09-12T08:30")
    # The repository's own GitHub link is its trusted source, kept by the sync — never visited by Cicada's fetcher.
    [source] = kit["sources"]
    assert source["ref"] == "https://github.com/example-org/widget-kit" and source["predicate"] == "website"
    assert source["added_by"] == "user" and source["kept_by"] == "github"
    assert not source_refresh.tracked(source) and source_refresh.checker(source) is None
    from datetime import date

    from api.services import page_blocks

    assert page_blocks.source_state(source, date.today()) == "kept"
    # The organisation's avatar is the picture; a personal account's never is.
    assert kit["media"]["thumbnail"].startswith("https://avatars.githubusercontent.com/u/2002")
    assert not pages["ada-example/tiny-lib"]["fm"]["media"].get("thumbnail")
    # A star is a save from a platform's list: indexed, never a conversation, never the person's words.
    saves = [e for e in episodes if e.get("origin") == github.ORIGIN_STARRED]
    assert len(saves) == 2 and all(history_index.is_index_only(e) for e in saves)
    assert sync_state.read_sync_state(bank)["github"]["count"] == 4


def test_the_sync_asks_only_its_own_account_endpoints_read_only_with_the_token(bank):
    _connect()
    server = FakeGitHub()
    _sync(bank, server)
    assert server.calls and all(c["method"] == "GET" for c in server.calls)
    assert {c["url"] for c in server.calls} == {github.API_BASE + p for p in ("user", "user/repos", "user/starred")}
    assert all(c["headers"]["Authorization"] == f"Bearer {TOKEN}" for c in server.calls)
    assert set().union(*(c["params"] for c in server.calls)) <= {"per_page", "page", "affiliation", "sort"}
    for path in bank.rglob("*"):
        if path.is_file() and ".git" not in path.parts:
            assert TOKEN not in path.read_text(encoding="utf-8", errors="replace"), path
    cursor = json.loads(next((bank.parent / "home" / "connectors").glob("github-*.json")).read_text())
    assert "bob-example" not in json.dumps(cursor)        # the account is a hash, never the login


def test_an_unchanged_resync_writes_and_commits_nothing(bank):
    _connect()
    _sync(bank, FakeGitHub())
    head = _git(bank, "rev-parse", "HEAD")
    later = FakeGitHub()
    for row in later.fix["owned"]:
        row["stargazers_count"] += 5                     # moves every day; never a page rewrite
    result = _sync(bank, later)
    assert result["status"] == "ok" and result["new"] == 0 and result["updated"] == 0, result
    assert _git(bank, "rev-parse", "HEAD") == head


def test_a_resync_updates_in_place_and_deletes_nothing(bank):
    _connect()
    _sync(bank, FakeGitHub())
    before = _files(bank)
    later = FakeGitHub()
    later.fix["starred"][0]["repo"]["description"] = "A bigger kit of widgets."
    del later.fix["starred"][1]                          # unstarred on GitHub
    del later.fix["owned"][1]                            # deleted or transferred on GitHub
    result = _sync(bank, later)
    assert result["status"] == "ok", result
    assert _files(bank) == before                        # nothing removed, nothing new
    pages = _pages(bank)
    assert pages["example-org/widget-kit"]["fm"]["github"]["description"] == "A bigger kit of widgets."
    gone = pages["ada-example/tiny-lib"]["fm"]["github"]
    assert gone["starred"] is False and gone["unstarred_on"]
    owned = {e["source_id"]: e for e in _episodes(bank) if e.get("origin") == github.ORIGIN_OWNED}
    assert owned["github:owned:502"].get("source_deleted_at") and not owned["github:owned:501"].get("source_deleted_at")
    words = sync_state.read_sync_state(bank)["github"].get("words") or ""
    assert "no longer starred" in words and "page stays" in words
    from api.services import channel_registry

    row = channel_registry._connector_channel("github", "GitHub", sync_state.read_sync_state(bank), "repository",
                                              connected=True)
    assert row["detail"].endswith("1 repository is no longer starred on GitHub; its page stays.")
    assert [r["full_name"] for r in github_repos.owned(bank)] == ["bob-example/alpha-project"]


def test_a_list_cut_short_tombstones_nothing(bank, monkeypatch):
    _connect()
    _sync(bank, FakeGitHub())
    monkeypatch.setattr(github, "MAX_PAGES", 1)
    monkeypatch.setattr(github, "PER_PAGE", 1)          # every list now reads as longer than the cap
    result = _sync(bank, FakeGitHub())
    assert result["status"] == "ok"
    assert not any(e.get("source_deleted_at") for e in _episodes(bank))
    assert all(p["fm"]["github"].get("starred") for p in _pages(bank).values())


def test_a_refused_token_is_said_in_words_and_nothing_is_written(bank):
    _connect()
    before = _files(bank)
    result = _sync(bank, FakeGitHub(status=401))
    assert result["status"] == "error" and "github.com/settings/personal-access-tokens" in result["error"]
    assert _files(bank) - before <= {"sync_state.json"}


def test_a_demo_bank_takes_nothing(bank):
    _connect()
    (bank / "_bank.yaml").write_text("kind: demo\n")
    assert _sync(bank, FakeGitHub())["reason"] == "the demo memory is open"


def test_a_bookmarked_github_link_becomes_the_repository_page_not_a_second_one(bank):
    from api.services import media_ingestor

    idx = media_ingestor.load_url_index(bank)
    item = media_ingestor.RawItem(url="https://github.com/example-org/widget-kit", title="widget-kit",
                                  origin="chrome-bookmark")
    made = media_ingestor.write_prepared(media_ingestor.PreparedItem(item, None), bank, idx)
    media_ingestor.save_url_index(bank, idx)
    _connect()
    _sync(bank, FakeGitHub())
    pages = _pages(bank)
    assert pages["example-org/widget-kit"]["id"] == made.media_entity_id
    assert len(pages) == 2


# --- URLs and the README preview ------------------------------------------------------------------------------------


@pytest.mark.parametrize("text,want", [
    ("https://github.com/example-org/widget-kit", "example-org/widget-kit"),
    ("https://github.com/example-org/widget-kit/tree/main/src", "example-org/widget-kit"),
    ("https://www.github.com/example-org/widget-kit.git", "example-org/widget-kit"),
    ("git@github.com:example-org/widget-kit.git", "example-org/widget-kit"),
    ("github.com/example-org/widget-kit", "example-org/widget-kit"),
    ("example-org/widget-kit", "example-org/widget-kit"),
    ("https://github.com/example-org", None),
    ("https://gitlab.com/example-org/widget-kit", None),
    ("https://github.com/settings/tokens", None),
    ("https://user:pw@github.com/example-org/widget-kit", None),
    ("https://github.com:8443/example-org/widget-kit", None),
    ("not a link", None),
])
def test_parse_repo_takes_only_a_repository(text, want):
    assert github.parse_repo(text) == want


def test_a_readme_preview_is_words_only():
    raw = github_repos.decode_readme(FIX["readme_widget_kit"])
    text, truncated = github_repos.preview_text(raw)
    assert "# Widget Kit" in text and "pip install widget-kit" in text and "example apps" in text
    assert "<" not in text and "](" not in text and "example.invalid" not in text and "comment" not in text
    assert not truncated
    long_text, cut = github_repos.preview_text("line\n" * 5000)
    assert cut and len(long_text) <= github_repos.PREVIEW_CHARS + 2


def test_a_record_off_github_never_becomes_a_page():
    row = copy.deepcopy(FIX["owned"][0])
    row["html_url"] = "https://elsewhere.example/bob-example/alpha-project"
    assert github_repos.Repo.from_api(row) is None
    row = copy.deepcopy(FIX["starred"][0]["repo"])
    row["owner"]["avatar_url"] = "https://elsewhere.example/a.png"
    assert github_repos.Repo.from_api(row).picture is None


def test_the_transport_refuses_any_other_host():
    with pytest.raises(tier2.base.ConnectorError):
        asyncio.run(github.guarded_transport("GET", "https://elsewhere.example/user", headers={}))
    with pytest.raises(tier2.base.ConnectorError):
        asyncio.run(github.client("", transport=FakeGitHub()).get("https://elsewhere.example/user"))


# --- projects --------------------------------------------------------------------------------------------------------


def _project(memory, eid, **fm):
    markdown_parser.write(memory / "entities" / f"{eid}.md",
                          {"name": fm.pop("name", eid), "type": "project", "status": "active", **fm}, "A project.\n")
    bank_index.invalidate(memory)


def test_an_owned_repository_matches_its_project_by_the_hooks_salted_origin_hash(bank):
    from api.hooks import workspace_identity
    from api.services.auth import cicada_home

    salt = "0123456789abcdef0123456789abcdef"
    (cicada_home()).mkdir(parents=True, exist_ok=True)
    (cicada_home() / workspace_identity.SALT_FILE).write_text(salt)
    hashed = github_repos.remote_hash("https://github.com/bob-example/alpha-project", salt)
    assert hashed == workspace_identity.remote_hash(
        workspace_identity.normalise_remote(b"git@github.com:bob-example/alpha-project.git"), salt)
    _project(bank, "renamed-thing", name="Renamed thing", born={"origin": "repo", "repo": {"remote": hashed}})
    _project(bank, "side-notes")
    rows = {r["full_name"]: r for r in github_repos.with_matches(bank, [
        {"full_name": "bob-example/alpha-project"}, {"full_name": "bob-example/side-notes"},
        {"full_name": "bob-example/nothing"}])}
    assert rows["bob-example/alpha-project"]["project"] == {"project": "renamed-thing", "name": "Renamed thing",
                                                           "how": "origin"}
    assert rows["bob-example/side-notes"]["project"]["how"] == "name"     # a suggestion only
    assert rows["bob-example/nothing"]["project"] is None
    assert "bob-example" not in (bank / "entities" / "renamed-thing.md").read_text()   # nothing written


# --- the doors -------------------------------------------------------------------------------------------------------


@pytest.fixture
def api(bank, monkeypatch):
    from fastapi.testclient import TestClient

    from api import config, main

    server = FakeGitHub()
    monkeypatch.setattr(github, "TRANSPORT", server)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    monkeypatch.setenv("CICADA_ALLOW_LOGO_FETCH", "on")
    config.get_settings.cache_clear()
    client = TestClient(main.app)
    client.server = server
    yield client
    config.get_settings.cache_clear()


def test_a_pasted_link_adds_the_repository_with_its_readme_kept_outside_the_bank(api, bank):
    answer = api.post("/sources/github/repos", json={"url": "https://github.com/example-org/widget-kit/issues"})
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["fullName"] == "example-org/widget-kit" and body["created"] is True
    eid = body["entityId"]
    fm = markdown_parser.parse(bank / "entities" / f"{eid}.md").frontmatter
    assert fm["github"]["added"] is True and fm["media"]["kind"] == "repository"
    # The person's own save: its episode is read by Sleep like any link they save.
    [episode] = [e for e in _episodes(bank) if e.get("media_entity_id") == eid]
    assert episode["origin"] == github_repos.ADDED_ORIGIN and not history_index.is_index_only(episode)
    assert "Repository added" in _git(bank, "log", "-1", "--format=%s")
    # The README: through the official API, kept outside every bank, words only.
    assert any(c["url"].endswith("repos/example-org/widget-kit/readme") for c in api.server.calls)
    assert not any("pip install widget-kit" in p.read_text(errors="replace") for p in bank.rglob("*")
                   if p.is_file() and ".git" not in p.parts)
    assert list((bank.parent / "home" / "readmes").rglob("*.json"))
    card = api.get(f"/entities/{eid}/repository").json()
    assert card["readme"]["state"] == "fresh" and "# Widget Kit" in card["readme"]["text"]
    assert card["fullName"] == "example-org/widget-kit" and card["url"] == "https://github.com/example-org/widget-kit"
    # Added again: the same page, never a second.
    again = api.post("/sources/github/repos", json={"url": "example-org/widget-kit"}).json()
    assert again["entityId"] == eid and again["created"] is False


def test_a_link_that_is_not_a_repository_is_refused_in_words(api):
    answer = api.post("/sources/github/repos", json={"url": "https://example.com/a"})
    assert answer.status_code == 422 and "github.com/owner/name" in answer.json()["detail"]
    missing = api.post("/sources/github/repos", json={"url": "https://github.com/bob-example/no-such"})
    assert missing.status_code == 404 and "GitHub connected" in missing.json()["detail"]


def test_a_repository_with_no_readme_says_so(api, bank):
    eid = api.post("/sources/github/repos", json={"url": "ada-example/tiny-lib"}).json()["entityId"]
    assert api.get(f"/entities/{eid}/repository").json()["readme"]["state"] == "none"


def test_the_readme_is_not_fetched_on_open_while_the_picture_gate_is_off(api, bank, monkeypatch):
    eid = api.post("/sources/github/repos", json={"url": "ada-example/tiny-lib"}).json()["entityId"]
    for path in (bank.parent / "home" / "readmes").rglob("*.json"):
        path.unlink()
    monkeypatch.setenv("CICADA_ALLOW_LOGO_FETCH", "off")
    calls = len(api.server.calls)
    assert api.get(f"/entities/{eid}/repository").json()["readme"]["state"] == "missing"
    assert len(api.server.calls) == calls


def test_the_lists_and_make_it_a_project(api, bank):
    _connect()
    assert api.post("/sources/connectors/github/sync").json()["status"] == "ok"
    lists = api.get("/sources/github/repos").json()
    assert lists["connected"] is True
    assert [r["fullName"] for r in lists["owned"]] == ["bob-example/alpha-project", "bob-example/side-notes"]
    assert {r["fullName"] for r in lists["starred"]} == {"example-org/widget-kit", "ada-example/tiny-lib"}
    made = api.post("/sources/github/repos/project", json={"fullName": "bob-example/alpha-project"})
    assert made.status_code == 200, made.text
    pid = made.json()["project"]
    fm = markdown_parser.parse(bank / "entities" / f"{pid}.md").frontmatter
    assert fm["type"] == "project" and fm["mine"]["via"] == "app" and fm["github"]["owned"] is True
    assert any(s["predicate"] == "repo" and s["ref"] == "https://github.com/bob-example/alpha-project"
               for s in fm["sources"])
    row = next(r for r in api.get("/sources/github/repos").json()["owned"] if r["fullName"].endswith("alpha-project"))
    assert row["project"] == {"project": pid, "name": "alpha-project", "how": "linked"}
    card = api.get(f"/entities/{pid}/repository").json()
    assert card["project"]["project"] == pid
    # The person's own repository added by its link: its page knows it is theirs and which project it is.
    page = api.post("/sources/github/repos", json={"url": "bob-example/alpha-project"}).json()["entityId"]
    mine = api.get(f"/entities/{page}/repository").json()
    assert mine["owned"] is True and mine["project"] == {"project": pid, "name": "alpha-project", "how": "linked"}
    # A starred repository someone else owns never gets a same-name suggestion.
    _project(bank, "widget-kit")
    kit = next(r for r in api.get("/sources/github/repos").json()["starred"] if r["fullName"].endswith("widget-kit"))
    assert api.get(f"/entities/{kit['entityId']}/repository").json()["project"] is None
    # Linking to an existing page instead; a page that is not a project is refused.
    _project(bank, "notes-project")
    linked = api.post("/sources/github/repos/project",
                      json={"fullName": "bob-example/side-notes", "project": "notes-project"})
    assert linked.status_code == 200 and linked.json() == {"project": "notes-project", "created": False}
    assert api.post("/sources/github/repos/project",
                    json={"fullName": "bob-example/side-notes", "project": "nope"}).status_code == 404


def test_disconnect_forgets_the_token_and_the_readmes_and_keeps_the_pages(api, bank):
    _connect()
    eid = api.post("/sources/github/repos", json={"url": "example-org/widget-kit"}).json()["entityId"]
    readmes = bank.parent / "home" / "readmes"
    assert list(readmes.rglob("*.json"))
    gone = api.delete("/sources/connectors/github/credentials").json()
    assert gone["connected"] is False and not secrets.has_secret(github.TOKEN_ENV)
    assert not list(readmes.rglob("*.json"))
    assert (bank / "entities" / f"{eid}.md").exists()


def test_the_demo_bank_refuses_every_write_door(api, bank):
    (bank / "_bank.yaml").write_text("kind: demo\n")
    assert api.post("/sources/github/repos", json={"url": "example-org/widget-kit"}).status_code == 409
    assert api.post("/sources/github/repos/project", json={"fullName": "bob-example/alpha-project"}).status_code == 409
    assert not list((bank / "entities").glob("*.md"))


def test_the_cli_commands_call_the_backends_routes_as_the_person(monkeypatch):
    from types import SimpleNamespace

    from api import cli_app
    from api.services import cli_map

    rows = {r.name: r for r in cli_map.ROWS}
    assert not rows["github repos"].mutates
    assert rows["github add"].person and rows["github add"].via == "backend"
    assert rows["github project"].person and [a.prop for a in rows["github project"].args] == ["full_name", "project"]
    sent: list[tuple] = []
    asked: list[str] = []

    def fake_call(boot, method, path, **kw):
        sent.append((method, path, kw.get("body")))
        if path == "/sources/github/repos" and method == "GET":
            return {"connected": True, "owned": [{"fullName": "bob-example/alpha-project", "private": True,
                                                  "project": {"project": "alpha", "name": "alpha", "how": "origin"}}],
                    "starred": [{"fullName": "example-org/widget-kit", "starred": True, "entityId": "widget-kit"}]}
        if path == "/sources/github/repos":
            return {"fullName": "example-org/widget-kit", "entityId": "widget-kit", "created": True}
        return {"project": "alpha", "created": False}

    monkeypatch.setattr(cli_app, "call", fake_call)
    monkeypatch.setattr(cli_app, "require_person", asked.append)
    boot = SimpleNamespace(probe={})
    listed = cli_app.cmd_github_repos(boot, SimpleNamespace())
    assert "bob-example/alpha-project [private] — your project alpha (alpha)" in listed.text
    assert "example-org/widget-kit (starred) — widget-kit" in listed.text
    added = cli_app.cmd_github_add(boot, SimpleNamespace(url="example-org/widget-kit"))
    assert added.text == "Added example-org/widget-kit (widget-kit)."
    linked = cli_app.cmd_github_project(boot, SimpleNamespace(full_name="bob-example/alpha-project", project="alpha"))
    assert linked.text == "Linked bob-example/alpha-project to your project alpha."
    assert sent[-1] == ("POST", "/sources/github/repos/project",
                        {"fullName": "bob-example/alpha-project", "via": "cli", "project": "alpha"})
    assert len(asked) == 2                               # both writes refuse from an agent's shell
    # Owner 2026-11-03 ("i'd rather it said 'Add as a project'"): one of yours is added as a project, and the help
    # says which command is for whose repository.
    monkeypatch.setattr(cli_app, "call", lambda boot, method, path, **kw: {"project": "alpha-project", "created": True})
    made = cli_app.cmd_github_project(boot, SimpleNamespace(full_name="bob-example/alpha-project", project=None))
    assert made.text == "Added bob-example/alpha-project as your project alpha-project."
    assert rows["github project"].summary.startswith("Add a repository you own as a project")
    assert "`cicada github project`" in rows["github add"].summary


# --- review of #583: the real size cap, rate limits, a replayed add, a stale link row ---------------------------------


def _realistic_star(n: int) -> dict:
    """A starred row the size GitHub really sends (~6.1 KB: every URL template on the repository and its owner)."""
    full = f"example-org/repo-{n:03d}"
    api = f"https://api.github.com/repos/{full}"
    repo = copy.deepcopy(FIX["starred"][0]["repo"])
    repo.update({"id": 10_000 + n, "name": full.split("/")[1], "full_name": full,
                 "html_url": f"https://github.com/{full}", "description": "A kit of widgets. " * 18,
                 "topics": [f"topic-{i}" for i in range(20)]})
    for key in ("forks", "keys", "collaborators", "teams", "hooks", "issue_events", "events", "assignees", "branches",
                "tags", "blobs", "git_tags", "git_refs", "trees", "statuses", "languages", "stargazers", "contributors",
                "subscribers", "subscription", "commits", "git_commits", "comments", "issue_comment", "contents",
                "compare", "merges", "archive", "downloads", "issues", "pulls", "milestones", "notifications",
                "labels", "releases", "deployments", "git", "ssh", "clone", "svn", "mirror"):
        repo[f"{key}_url"] = f"{api}/{key}{{/sha}}{{?since,until,path,author,committer,per_page,page}}"
    owner = repo["owner"]
    for key in ("followers", "following", "gists", "starred", "subscriptions", "organizations", "repos", "events",
                "received_events", "html", "url"):
        owner[f"{key}_url"] = f"https://api.github.com/users/example-org/{key}{{/other_user}}{{/gist_id}}"
    repo["license"] = {"key": "mit", "name": "MIT License", "spdx_id": "MIT",
                       "url": "https://api.github.com/licenses/mit", "node_id": "MDc6TGljZW5zZTEz"}
    return {"starred_at": "2026-09-12T08:30:00Z", "repo": repo}


@pytest.fixture
def real_cap(monkeypatch):
    """GitHub's answers through `guarded_transport` itself — its byte cap, its JSON read, its status mapping — with
    httpx's network swapped for a mock; `net_guard`'s DNS check answered yes for api.github.com only."""
    import httpx

    from api.services import net_guard

    async def fetchable(url):
        return url.startswith(github.API_BASE)

    monkeypatch.setattr(net_guard, "is_fetchable_url_async", fetchable)
    replies = {}

    def handler(request):
        status, body, headers = replies["fn"](request)
        return httpx.Response(status, json=body, headers=headers)

    monkeypatch.setattr(github, "HTTPX_TRANSPORT", httpx.MockTransport(handler))
    return replies


def test_a_full_page_of_real_sized_rows_fits_the_byte_cap(real_cap):
    row_bytes = len(json.dumps(_realistic_star(0)).encode())
    assert row_bytes >= 6_000                                            # the measured size of a real starred row
    assert 100 * row_bytes > github.MAX_BYTES >= github.PER_PAGE * row_bytes * 1.3   # 100 a page could never fit

    def star_pages(request):
        page = int(request.url.params.get("page"))
        rows = [_realistic_star(n) for n in range(github.PER_PAGE)] if page == 1 else []
        return 200, rows, {}

    real_cap["fn"] = star_pages
    rows, done = asyncio.run(github.read_starred(github.client("placeholder")))
    assert done and len(rows) == github.PER_PAGE
    assert github.PER_PAGE * github.MAX_PAGES >= 3000                     # the same 3,000 items a list may hold
    # And the page size GitHub allows, through the same cap: refused in words, never a partial read.
    real_cap["fn"] = lambda request: (200, [_realistic_star(n) for n in range(100)], {})
    with pytest.raises(tier2.Refused) as exc:
        asyncio.run(github.client("placeholder").get("user/starred", per_page=100, page=1))
    assert "more than Cicada reads" in exc.value.words


def test_a_secondary_rate_limit_is_a_rate_limit_never_a_refused_token(real_cap):
    for headers, body in (({"retry-after": "1"}, {"message": "slow down"}),
                          ({}, {"message": "You have exceeded a secondary rate limit."}),
                          ({"x-ratelimit-remaining": "0"}, {"message": "API rate limit exceeded"})):
        real_cap["fn"] = lambda request, h=headers, b=body: (403, b, h)
        client = tier2.Client(github, "placeholder", sleep=lambda s: asyncio.sleep(0))
        with pytest.raises(tier2.Refused) as exc:
            asyncio.run(client.get("user"))
        assert exc.value.kind == "rate" and exc.value.words == github.RATE_WORDS
        assert "again from the start" in exc.value.words and "refused the token" not in exc.value.words
    real_cap["fn"] = lambda request: (403, {"message": "Resource not accessible by personal access token"}, {})
    with pytest.raises(tier2.Refused) as exc:
        asyncio.run(github.client("placeholder").get("user"))
    assert exc.value.kind == "sign-in"


def test_a_replayed_add_writes_nothing_new(api, bank):
    """A copy's outbox may resend the same add days later (`test_tx_outbox.SAME_BY_CONTENT`): the same page, no
    second episode, no commit."""
    first = api.post("/sources/github/repos", json={"url": "example-org/widget-kit"}).json()
    files, head = _files(bank), _git(bank, "rev-parse", "HEAD")
    again = api.post("/sources/github/repos", json={"url": "https://github.com/example-org/widget-kit"})
    assert again.status_code == 200 and again.json() == {**first, "created": False}
    assert _files(bank) == files and _git(bank, "rev-parse", "HEAD") == head


def test_a_link_row_whose_page_is_gone_gets_the_page_again(api, bank):
    eid = api.post("/sources/github/repos", json={"url": "example-org/widget-kit"}).json()["entityId"]
    (bank / "entities" / f"{eid}.md").unlink()
    bank_index.invalidate(bank)
    again = api.post("/sources/github/repos", json={"url": "example-org/widget-kit"})
    assert again.status_code == 200, again.text
    body = again.json()
    assert body["created"] is True and (bank / "entities" / f"{body['entityId']}.md").exists()


def test_a_sync_never_brings_back_a_page_the_person_merged_away(api, bank):
    """Re-review of #583: the person folds a starred repository's page into a `tool` page (the merge deletes it and
    leaves a redirect); the next sync follows the redirect and leaves the tool page alone — never a second page."""
    _connect()
    assert api.post("/sources/connectors/github/sync").json()["status"] == "ok"
    kit = next(r for r in api.get("/sources/github/repos").json()["starred"] if r["fullName"].endswith("widget-kit"))
    markdown_parser.write(bank / "entities" / "widget-kit-tool.md",
                          {"name": "Widget Kit", "type": "tool", "status": "active"}, "A kit the person uses.\n")
    _git(bank, "add", "-A")
    _git(bank, "commit", "-q", "-m", "tool page")
    bank_index.invalidate(bank)
    merged = api.post(f"/entities/{kit['entityId']}/merge", json={"into": "widget-kit-tool"})
    assert merged.status_code == 200, merged.text
    assert not (bank / "entities" / f"{kit['entityId']}.md").exists()
    tool_before = (bank / "entities" / "widget-kit-tool.md").read_text()
    entities_before = sorted(p.name for p in (bank / "entities").glob("*.md"))
    assert api.post("/sources/connectors/github/sync").json()["status"] == "ok"
    assert sorted(p.name for p in (bank / "entities").glob("*.md")) == entities_before
    assert (bank / "entities" / "widget-kit-tool.md").read_text() == tool_before
    # The person's own add of the same link lands on the page they merged it into, never a second page.
    again = api.post("/sources/github/repos", json={"url": "example-org/widget-kit"}).json()
    assert again["entityId"] == "widget-kit-tool" and again["created"] is False
    assert sorted(p.name for p in (bank / "entities").glob("*.md")) == entities_before


def test_a_sync_never_remakes_a_page_removed_with_no_redirect(api, bank):
    _connect()
    api.post("/sources/connectors/github/sync")
    kit = next(r for r in api.get("/sources/github/repos").json()["starred"] if r["fullName"].endswith("widget-kit"))
    (bank / "entities" / f"{kit['entityId']}.md").unlink()
    bank_index.invalidate(bank)
    assert api.post("/sources/connectors/github/sync").json()["status"] == "ok"
    assert not (bank / "entities" / f"{kit['entityId']}.md").exists()
