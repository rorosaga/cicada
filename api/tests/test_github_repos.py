"""G230: GitHub repositories on the graph — connecting by a code, the tier-2 sync, the repository pages and their first
markdown, a project's repositories, the README preview, the doors.

Hermetic: no real account, no network. GitHub's API is a fake that answers with the recorded shapes in
`fixtures/connectors/github_api.json` (placeholders only) and records every request it was sent; GitHub's sign-in
endpoints are a second fake (`FakeSignIn`).
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
from api.services.connectors import ADAPTERS, github, github_auth, tier2

FIX = json.loads((Path(__file__).parent / "fixtures" / "connectors" / "github_api.json").read_text())
TOKEN = "placeholder-token-0123456789abcdef"
SALT = "0123456789abcdef0123456789abcdef"


class FakeGitHub:
    """api.github.com as recorded: every request kept; ``fix`` is the account's state (copied, so a test edits it)."""

    def __init__(self, fix=None, *, status: int | None = None, installed: bool = True):
        self.fix = copy.deepcopy(fix or FIX)
        self.status = status
        self.installed = installed
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
        if path == "user/installations":
            return tier2.Response(200, self.fix["installations"] if self.installed else
                                  {"total_count": 0, "installations": []}, {})
        if path == "user/repos":
            # A GitHub App's user token sees the account's repositories only where the app is installed.
            return tier2.Response(200, self.fix["owned"] if page == 1 and self.installed else [], {})
        if path == "user/starred":
            assert headers.get("Accept") == "application/vnd.github.star+json"
            return tier2.Response(200, self.fix["starred"] if page == 1 else [], {})
        if path.startswith("repos/") and path.endswith("/readme"):
            if path == "repos/example-org/widget-kit/readme":
                return tier2.Response(200, self.fix["readme_widget_kit"], {})
            if path == "repos/bob-example/alpha-project/readme":
                return tier2.Response(200, self.fix["readme_alpha_project"], {})
            return tier2.Response(404, {"message": "Not Found"}, {})
        if path.startswith("repos/"):
            full = path[len("repos/"):]
            for row in [*self.fix["owned"], *(s["repo"] for s in self.fix["starred"])]:
                if row["full_name"] == full:
                    return tier2.Response(200, row, {})
            return tier2.Response(404, {"message": "Not Found"}, {})
        return tier2.Response(404, {"message": "Not Found"}, {})


class FakeSignIn:
    """github.com's two sign-in endpoints: ``answers`` are what the token endpoint says, one per poll, in order."""

    def __init__(self, answers=(), *, start=None):
        self.answers = list(answers)
        self.start = start or {"device_code": "dev-placeholder-code", "user_code": "ABCD-1234",
                               "verification_uri": "https://github.com/login/device", "expires_in": 900,
                               "interval": 5}
        self.calls: list[tuple[str, dict]] = []

    async def __call__(self, url, form):
        self.calls.append((url, dict(form)))
        if url.endswith(github_auth.DEVICE_CODE_PATH):
            return tier2.Response(200, self.start, {})
        return tier2.Response(200, self.answers.pop(0) if self.answers else {"error": "authorization_pending"}, {})


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
    for name in github.SECRET_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv(github_auth.CLIENT_ID_ENV, raising=False)
    github_auth.cancel()
    yield memory
    for name in github.SECRET_NAMES:
        os.environ.pop(name, None)
    github_auth.cancel()


def _connect():
    secrets.set_secret(github.TOKEN_ENV, TOKEN)


def _sync(memory, server):
    return asyncio.run(github.sync(memory, http_fn=server))


def _pages(memory) -> dict[str, dict]:
    out = {}
    for path in sorted((memory / "entities").glob("*.md")):
        parsed = markdown_parser.parse(path)
        block = parsed.frontmatter.get("github") or {}
        out[str(block.get("full_name") or path.stem)] = {"fm": parsed.frontmatter, "id": path.stem,
                                                         "body": parsed.body}
    return out


def _episodes(memory) -> list[dict]:
    return [markdown_parser.parse(p).frontmatter for p in sorted((memory / "episodes").glob("*.md"))]


def _files(memory) -> set[str]:
    return {str(p.relative_to(memory)) for p in memory.rglob("*") if p.is_file() and ".git" not in p.parts}


def _salted():
    from api.hooks import workspace_identity
    from api.services.auth import cicada_home

    cicada_home().mkdir(parents=True, exist_ok=True)
    (cicada_home() / workspace_identity.SALT_FILE).write_text(SALT)


def _project(memory, eid, **fm):
    markdown_parser.write(memory / "entities" / f"{eid}.md",
                          {"name": fm.pop("name", eid), "type": "project", "status": "active", **fm}, "A project.\n")
    bank_index.invalidate(memory)


# --- the sync ------------------------------------------------------------------------------------------------------


def test_github_is_a_tier_two_connector_off_until_connected(bank):
    assert ADAPTERS["github"] is github and github.TIER == 2 and not github.is_connected()
    result = _sync(bank, FakeGitHub())
    assert result["status"] == "skipped" and result["reason"] == "not connected"
    assert github.READS.startswith("Read-only") and "personal-access-tokens" not in github.READS   # said once


def test_a_first_sync_makes_a_page_for_each_of_your_repositories_and_quiet_pages_for_your_stars(bank):
    from api.services import quiet_pages

    _connect()
    result = _sync(bank, FakeGitHub())
    assert result["status"] == "ok", result
    episodes = _episodes(bank)
    owned = [e for e in episodes if e.get("origin") == github.ORIGIN_OWNED]
    # The record GitHub keeps (staged, tombstoned when gone) and the page's own save — every one index-only.
    assert sorted(e["source_id"] for e in owned if e.get("source_id")) == ["github:owned:501", "github:owned:502"]
    assert all(history_index.is_index_only(e) and e["processed"] is True for e in owned)
    pages = _pages(bank)
    assert set(pages) == {"bob-example/alpha-project", "bob-example/side-notes", "example-org/widget-kit",
                          "ada-example/tiny-lib"}
    assert not any(p["fm"].get("type") == "project" for p in pages.values())          # a repository is not a project
    alpha = pages["bob-example/alpha-project"]
    assert alpha["fm"]["type"] == "media" and alpha["fm"]["media"]["kind"] == "repository"
    assert alpha["fm"]["github"]["owned"] is True and alpha["fm"].get("origin") == github.ORIGIN_OWNED
    # Its first markdown: what it is, a summary of its README, its link, language and topics.
    body = alpha["body"]
    assert body.startswith("## Summary\nNotes on an example project.")
    assert "Alpha Project keeps notes on an example project in plain markdown files, one per idea." in body
    assert "- [bob-example/alpha-project](https://github.com/bob-example/alpha-project)" in body
    assert "- Language: Python" in body and "- Topics: notes" in body
    assert "pip install" not in body and "badge" not in body and "](https://example.com" not in body
    side = pages["bob-example/side-notes"]
    assert side["body"].startswith("## Summary\nScratch notes.") and "- Private" in side["body"]   # no README: no summary
    # The README it was read for is the page's preview too, outside every bank.
    kept = github_repos.read_readme(bank.name, alpha["id"])
    assert kept and "Alpha Project" in kept["text"] and github_repos.readme_state(kept) == "fresh"
    # Quiet until the person mentions it, like any import.
    assert quiet_pages.page_is_quiet(bank, alpha["id"])
    kit = pages["example-org/widget-kit"]["fm"]
    assert kit["type"] == "media" and kit["media"]["kind"] == "repository"
    assert kit["github"]["starred"] is True and kit["github"]["starred_at"].startswith("2026-09-12T08:30")
    assert pages["example-org/widget-kit"]["body"].startswith("## Summary\nSaved repository")   # a star stays a save
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
    assert not alpha["fm"]["media"].get("thumbnail")
    saves = [e for e in episodes if e.get("origin") == github.ORIGIN_STARRED]
    assert len(saves) == 2 and all(history_index.is_index_only(e) for e in saves)
    assert "2 of your repositories got their page." in (sync_state.read_sync_state(bank)["github"].get("words") or "")


def test_the_sync_asks_only_its_own_account_endpoints_read_only_and_a_readme_only_for_a_new_page(bank):
    _connect()
    server = FakeGitHub()
    _sync(bank, server)
    assert server.calls and all(c["method"] == "GET" for c in server.calls)
    assert {c["url"] for c in server.calls} == {github.API_BASE + p for p in (
        "user", "user/repos", "user/starred", "repos/bob-example/alpha-project/readme",
        "repos/bob-example/side-notes/readme")}
    assert all(c["headers"]["Authorization"] == f"Bearer {TOKEN}" for c in server.calls)
    assert set().union(*(c["params"] for c in server.calls)) <= {"per_page", "page", "affiliation", "sort"}
    for path in bank.rglob("*"):
        if path.is_file() and ".git" not in path.parts:
            assert TOKEN not in path.read_text(encoding="utf-8", errors="replace"), path
    cursor = json.loads(next((bank.parent / "home" / "connectors").glob("github-*.json")).read_text())
    assert "bob-example" not in json.dumps(cursor)        # the account is a hash, never the login
    again = FakeGitHub()
    _sync(bank, again)
    assert not [c for c in again.calls if c["url"].endswith("/readme")]   # the pages exist: no README read


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


def test_a_resync_updates_in_place_keeps_your_words_and_deletes_nothing(bank):
    _connect()
    _sync(bank, FakeGitHub())
    alpha = _pages(bank)["bob-example/alpha-project"]
    page = bank / "entities" / f"{alpha['id']}.md"
    markdown_parser.write(page, alpha["fm"], alpha["body"] + "\n\n## Notes\nThe person's own line.")
    before = _files(bank)
    later = FakeGitHub()
    later.fix["starred"][0]["repo"]["description"] = "A bigger kit of widgets."
    later.fix["owned"][0]["description"] = "Notes, renamed."
    del later.fix["starred"][1]                          # unstarred on GitHub
    del later.fix["owned"][1]                            # deleted or transferred on GitHub
    result = _sync(bank, later)
    assert result["status"] == "ok", result
    assert _files(bank) == before                        # nothing removed, nothing new
    pages = _pages(bank)
    assert pages["example-org/widget-kit"]["fm"]["github"]["description"] == "A bigger kit of widgets."
    assert pages["bob-example/alpha-project"]["fm"]["github"]["description"] == "Notes, renamed."
    assert "The person's own line." in pages["bob-example/alpha-project"]["body"]          # the words are kept
    gone = pages["ada-example/tiny-lib"]["fm"]["github"]
    assert gone["starred"] is False and gone["unstarred_on"]
    assert "bob-example/side-notes" in pages                                               # its page stays
    owned = {e["source_id"]: e for e in _episodes(bank) if e.get("source_id", "").startswith("github:owned:")}
    assert owned["github:owned:502"].get("source_deleted_at") and not owned["github:owned:501"].get("source_deleted_at")
    words = sync_state.read_sync_state(bank)["github"].get("words") or ""
    assert "no longer starred" in words and "page stays" in words
    assert [r["full_name"] for r in github_repos.owned(bank)] == ["bob-example/alpha-project"]


def test_a_list_cut_short_tombstones_nothing(bank, monkeypatch):
    _connect()
    _sync(bank, FakeGitHub())
    monkeypatch.setattr(github, "MAX_PAGES", 1)
    monkeypatch.setattr(github, "PER_PAGE", 1)          # every list now reads as longer than the cap
    result = _sync(bank, FakeGitHub())
    assert result["status"] == "ok"
    assert not any(e.get("source_deleted_at") for e in _episodes(bank))
    assert all(p["fm"]["github"].get("starred") for p in _pages(bank).values() if not p["fm"]["github"].get("owned"))


def test_a_refused_token_is_said_in_words_and_nothing_is_written(bank):
    _connect()
    before = _files(bank)
    result = _sync(bank, FakeGitHub(status=401))
    assert result["status"] == "error" and "Connect GitHub again" in result["error"]
    assert _files(bank) - before <= {"sync_state.json"}


def test_a_demo_bank_takes_nothing(bank):
    _connect()
    (bank / "_bank.yaml").write_text("kind: demo\n")
    assert _sync(bank, FakeGitHub())["reason"] == "the demo memory is open"
    assert not list((bank / "entities").glob("*.md"))


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
    assert len(pages) == 4


def test_an_older_bank_gets_a_page_for_each_suggestion_row_on_its_next_sync(bank):
    """Existing banks (#583/#587): the person's own repositories were index-only rows with no page; the next sync
    makes their pages — one write each — and never one the person removed."""
    _connect()
    real = github_repos.apply_owned
    github_repos.apply_owned = lambda *a, **k: {"paths": [], "created": 0, "updated": 0}
    try:
        _sync(bank, FakeGitHub())
    finally:
        github_repos.apply_owned = real
    assert set(_pages(bank)) == {"example-org/widget-kit", "ada-example/tiny-lib"}      # the old shape
    result = _sync(bank, FakeGitHub())
    assert result["new"] == 2 and {"bob-example/alpha-project", "bob-example/side-notes"} <= set(_pages(bank))


def test_a_sync_never_remakes_a_page_you_removed_or_merged(bank):
    _connect()
    _sync(bank, FakeGitHub())
    pages = _pages(bank)
    (bank / "entities" / f"{pages['bob-example/side-notes']['id']}.md").unlink()
    bank_index.invalidate(bank)
    server = FakeGitHub()
    assert _sync(bank, server)["status"] == "ok"
    assert "bob-example/side-notes" not in _pages(bank)
    assert not [c for c in server.calls if c["url"].endswith("/readme")]       # nothing read for a page not made


def test_not_installed_the_stars_come_in_and_no_record_is_tombstoned(bank, monkeypatch):
    _connect()
    _sync(bank, FakeGitHub())
    monkeypatch.setenv(github_auth.HOW_ENV, github_auth.HOW_APP)          # signed in with the app, not installed
    result = _sync(bank, FakeGitHub(installed=False))
    assert result["status"] == "ok"
    assert not any(e.get("source_deleted_at") for e in _episodes(bank))
    assert github.NOT_INSTALLED_WORDS in (sync_state.read_sync_state(bank)["github"].get("words") or "")
    assert github_auth.account()["installed"] is False


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


def test_a_readme_summary_is_its_first_paragraph_of_prose():
    md = github_repos.decode_readme(FIX["readme_alpha_project"])
    assert github_repos.readme_summary(md) == ("Alpha Project keeps notes on an example project in plain markdown "
                                               "files, one per idea. It is a placeholder for tests.")
    assert github_repos.readme_summary("# Title\n\n![x](y)\n\n- a list\n- of things\n") == ""
    long = "Word " * 300 + "end."
    assert len(github_repos.readme_summary(long)) <= github_repos.SUMMARY_CHARS + 1


# --- a project's repositories ----------------------------------------------------------------------------------------


def test_a_project_links_its_own_checkouts_repository_by_the_hooks_salted_origin_hash(bank):
    from api.hooks import workspace_identity

    _salted()
    hashed = github_repos.remote_hash("https://github.com/bob-example/alpha-project", SALT)
    assert hashed == workspace_identity.remote_hash(
        workspace_identity.normalise_remote(b"git@github.com:bob-example/alpha-project.git"), SALT)
    _project(bank, "renamed-thing", name="Renamed thing", born={"origin": "repo", "repo": {"remote": hashed}})
    _project(bank, "side-notes")
    _connect()
    assert _sync(bank, FakeGitHub())["status"] == "ok"
    pages = _pages(bank)
    alpha = pages["bob-example/alpha-project"]
    fm = markdown_parser.parse(bank / "entities" / "renamed-thing.md").frontmatter
    [row] = fm["repositories"]
    assert row["entity"] == alpha["id"] and row["how"] == "origin" and row["by"] == "cicada"
    assert row["url"] == "https://github.com/bob-example/alpha-project"
    assert alpha["fm"]["github"]["projects"] == ["renamed-thing"]                     # the page links back
    # Cicada's inference is its own commit, never folded into the person's sync.
    assert "Cicada-Author: cicada" in _git(bank, "log", "-1", "--format=%B")
    assert "renamed-thing.md" in _git(bank, "show", "--name-only", "--format=", "HEAD")
    # A name alone is a suggestion, never a link.
    side = markdown_parser.parse(bank / "entities" / "side-notes.md").frontmatter
    assert "repositories" not in side
    [suggested] = [r for r in github_repos.with_matches(bank, github_repos.owned(bank))
                   if r["full_name"] == "bob-example/side-notes"]
    assert suggested["project"]["how"] == "name" and suggested["projects"] == []
    assert "bob-example" not in (bank / "entities" / "side-notes.md").read_text()


def test_two_projects_on_one_remote_link_neither(bank):
    _salted()
    hashed = github_repos.remote_hash("https://github.com/bob-example/alpha-project", SALT)
    for eid in ("one-thing", "other-thing"):
        _project(bank, eid, born={"origin": "repo", "repo": {"remote": hashed}})
    _connect()
    _sync(bank, FakeGitHub())
    assert not any("repositories" in markdown_parser.parse(bank / "entities" / f"{e}.md").frontmatter
                   for e in ("one-thing", "other-thing"))


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


def _synced(api):
    _connect()
    assert api.post("/sources/connectors/github/sync").json()["status"] == "ok"
    return {r["fullName"]: r for r in api.get("/sources/github/repos").json()["owned"]}


def test_a_project_lists_two_repositories_by_the_persons_link_and_each_links_back(api, bank):
    _project(bank, "alpha-project", name="alpha-project")
    owned = _synced(api)
    assert all(r["entityId"] for r in owned.values())                                    # every one has its page
    assert owned["bob-example/alpha-project"]["project"]["how"] == "name"               # a suggestion only
    for full in ("bob-example/alpha-project", "bob-example/side-notes"):
        linked = api.post("/sources/github/repos/project", json={"fullName": full, "project": "alpha-project"})
        assert linked.status_code == 200 and linked.json() == {"project": "alpha-project", "created": False,
                                                               "linked": True}, linked.text
    assert "Repository linked to its project" in _git(bank, "log", "-1", "--format=%s")
    fm = markdown_parser.parse(bank / "entities" / "alpha-project.md").frontmatter
    assert [(r["url"], r["how"], r["by"]) for r in fm["repositories"]] == [
        ("https://github.com/bob-example/alpha-project", "user", "user"),
        ("https://github.com/bob-example/side-notes", "user", "user")]
    listed = api.get("/entities/alpha-project/repositories").json()
    assert [r["fullName"] for r in listed["repos"]] == ["bob-example/alpha-project", "bob-example/side-notes"]
    assert all(r["entityId"] and r["how"] == "user" for r in listed["repos"])
    assert not {r["entityId"] for r in listed["candidates"]} & {r["entityId"] for r in listed["repos"]}
    for full in ("bob-example/alpha-project", "bob-example/side-notes"):
        card = api.get(f"/entities/{owned[full]['entityId']}/repository").json()
        assert [p["project"] for p in card["projects"]] == ["alpha-project"]
        assert "alpha-project" not in [c["project"] for c in card["candidates"]]
        assert _pages(bank)[full]["fm"]["github"]["projects"] == ["alpha-project"]
    assert api.get("/entities/alpha-project/repository").status_code == 404           # a project is not a repository
    lists = api.get("/sources/github/repos").json()
    assert {p["project"] for r in lists["owned"] for p in r["projects"]} == {"alpha-project"}
    # The agent's view: both repositories, each with its page.
    from api.services import mcp_tools

    ctx = mcp_tools.ToolContext(memory_path=lambda: bank, session_id="ses_test", harness="claude-code")
    reply = mcp_tools.project(ctx, "alpha-project")
    assert "Repositories: bob-example/alpha-project (" in str(reply) and "bob-example/side-notes (" in str(reply)
    assert [r["full_name"] for r in reply.data["repositories"]] == ["bob-example/alpha-project",
                                                                    "bob-example/side-notes"]
    assert github_repos.repositories_line(bank, "alpha-project").startswith(
        "GitHub repositories: bob-example/alpha-project (page ")


def test_the_persons_unlink_is_remembered_and_no_automatic_link_puts_it_back(api, bank):
    _salted()
    hashed = github_repos.remote_hash("https://github.com/bob-example/alpha-project", SALT)
    _project(bank, "renamed-thing", born={"origin": "repo", "repo": {"remote": hashed}})
    _synced(api)
    assert markdown_parser.parse(bank / "entities" / "renamed-thing.md").frontmatter["repositories"]
    gone = api.post("/sources/github/repos/project", json={"fullName": "bob-example/alpha-project",
                                                           "project": "renamed-thing", "remove": True})
    assert gone.status_code == 200 and gone.json()["linked"] is False
    fm = markdown_parser.parse(bank / "entities" / "renamed-thing.md").frontmatter
    assert "repositories" not in fm and fm["repositories_removed"] == ["https://github.com/bob-example/alpha-project"]
    assert "projects" not in _pages(bank)["bob-example/alpha-project"]["fm"]["github"]
    assert api.post("/sources/connectors/github/sync").json()["status"] == "ok"
    assert "repositories" not in markdown_parser.parse(bank / "entities" / "renamed-thing.md").frontmatter
    # An agent cannot put it back either; the person's own link lifts the removal.
    eid = _pages(bank)["bob-example/alpha-project"]["id"]
    with pytest.raises(github_repos.LinkRefused):
        github_repos.link(bank, "renamed-thing", eid, by="claude-code", how="agent")
    assert github_repos.link(bank, "renamed-thing", eid)
    assert "repositories_removed" not in markdown_parser.parse(bank / "entities" / "renamed-thing.md").frontmatter


def test_a_new_project_from_a_repository_lists_it(api, bank):
    _synced(api)
    made = api.post("/sources/github/repos/project", json={"fullName": "bob-example/side-notes"})
    assert made.status_code == 200 and made.json()["created"] is True, made.text
    pid = made.json()["project"]
    fm = markdown_parser.parse(bank / "entities" / f"{pid}.md").frontmatter
    assert fm["type"] == "project" and fm["mine"]["via"] == "app" and "github" not in fm
    assert [r["url"] for r in fm["repositories"]] == ["https://github.com/bob-example/side-notes"]
    missing = api.post("/sources/github/repos/project", json={"fullName": "bob-example/no-such", "project": pid})
    assert missing.status_code == 404 and "Repositories come in with a GitHub sync" in missing.json()["detail"]
    assert api.post("/sources/github/repos/project",
                    json={"fullName": "bob-example/side-notes", "project": "nope"}).status_code == 404


def test_a_trusted_agent_links_a_repository_page_and_any_other_only_proposes(api, bank):
    from api.services import mcp_tools

    _project(bank, "alpha-project")
    _synced(api)
    eid = _pages(bank)["bob-example/side-notes"]["id"]
    trusted = mcp_tools.ToolContext(memory_path=lambda: bank, session_id="ses_test", harness="claude-code")
    reply = str(mcp_tools.link_entity(trusted, "alpha-project", eid, reason="The notes live there."))
    assert "as one of its repositories" in reply
    [row] = markdown_parser.parse(bank / "entities" / "alpha-project.md").frontmatter["repositories"]
    assert row["how"] == "agent" and row["by"] == "claude-code" and row["session"] == "ses_test"
    assert "Cicada-Author: claude-code" in _git(bank, "log", "-1", "--format=%B")
    other = mcp_tools.ToolContext(memory_path=lambda: bank, session_id="ses_x", harness="cursor")
    assert "Proposed" in str(mcp_tools.link_entity(other, "alpha-project", _pages(bank)["bob-example/alpha-project"]["id"],
                                                   reason="Maybe."))
    assert len(markdown_parser.parse(bank / "entities" / "alpha-project.md").frontmatter["repositories"]) == 1


def test_there_is_no_hand_add_any_more(api):
    assert api.post("/sources/github/repos", json={"url": "example-org/widget-kit"}).status_code == 405


def test_the_readme_is_not_fetched_on_open_while_the_picture_gate_is_off(api, bank, monkeypatch):
    _synced(api)
    eid = _pages(bank)["ada-example/tiny-lib"]["id"]
    monkeypatch.setenv("CICADA_ALLOW_LOGO_FETCH", "off")
    calls = len(api.server.calls)
    assert api.get(f"/entities/{eid}/repository").json()["readme"]["state"] == "missing"
    assert len(api.server.calls) == calls
    monkeypatch.setenv("CICADA_ALLOW_LOGO_FETCH", "on")
    assert api.get(f"/entities/{eid}/repository").json()["readme"]["state"] == "none"   # it has none
    kit = api.get(f"/entities/{_pages(bank)['example-org/widget-kit']['id']}/repository").json()
    assert kit["readme"]["state"] == "fresh" and "# Widget Kit" in kit["readme"]["text"]
    assert not any("pip install widget-kit" in p.read_text(errors="replace") for p in bank.rglob("*")
                   if p.is_file() and ".git" not in p.parts)


def test_the_demo_bank_refuses_every_write_door(api, bank):
    (bank / "_bank.yaml").write_text("kind: demo\n")
    assert api.post("/sources/github/repos/project", json={"fullName": "bob-example/alpha-project"}).status_code == 409
    assert api.post("/sources/github/connect").status_code == 409
    assert api.post("/sources/github/connect/poll").status_code == 409
    assert api.post("/sources/github/connect/installation").status_code == 409
    assert api.post("/sources/connectors/github/sync").status_code == 409
    assert not list((bank / "entities").glob("*.md"))


# --- connecting by a code -------------------------------------------------------------------------------------------


@pytest.fixture
def sign_in(monkeypatch):
    clock = {"now": 1_000_000.0}
    monkeypatch.setattr(github_auth, "_now", lambda: clock["now"])
    monkeypatch.setenv(github_auth.CLIENT_ID_ENV, "Iv1.placeholder0000")
    fake = FakeSignIn([{"error": "authorization_pending"}, {"error": "slow_down", "interval": 10},
                       {"access_token": "ghu_placeholder", "refresh_token": "ghr_placeholder",
                        "expires_in": 28800, "token_type": "bearer"}])
    monkeypatch.setattr(github_auth, "POST", fake)
    fake.clock = clock
    return fake


def test_connect_by_code_keeps_the_token_outside_the_bank_and_offers_the_install(api, bank, sign_in):
    status = api.get("/sources/github/connect").json()
    assert status["available"] is True and status["connected"] is False
    started = api.post("/sources/github/connect")
    assert started.status_code == 200, started.text
    body = started.json()
    assert body["userCode"] == "ABCD-1234" and body["verificationUri"] == "https://github.com/login/device"
    assert "dev-placeholder-code" not in started.text                                  # the device code stays here
    assert api.post("/sources/github/connect/poll").json()["state"] == "pending"      # too soon: GitHub not asked
    assert len(sign_in.calls) == 1
    # A panel reopened mid-sign-in gets the same code back, in the wire's own shape.
    assert api.get("/sources/github/connect").json()["pending"] == {
        "userCode": "ABCD-1234", "verificationUri": "https://github.com/login/device",
        "expiresAt": body["expiresAt"], "interval": 5}
    for step in (5, 5, 10):
        sign_in.clock["now"] += step
        answer = api.post("/sources/github/connect/poll").json()
    assert answer["state"] == "connected", answer
    # The device flow is the client id alone: no secret is ever sent.
    assert all("client_secret" not in form and form["client_id"] == "Iv1.placeholder0000" for _, form in sign_in.calls)
    assert sign_in.calls[-1][1]["grant_type"] == github_auth.DEVICE_GRANT
    stored = secrets.load_secrets()
    assert stored[github.TOKEN_ENV] == "ghu_placeholder" and stored[github_auth.REFRESH_ENV] == "ghr_placeholder"
    assert stored[github_auth.HOW_ENV] == "app" and int(stored[github_auth.EXPIRES_ENV]) == 1_000_000 + 20 + 28800
    assert answer["status"]["how"] == "app" and answer["status"]["installed"] is True     # the fake has it installed
    for path in bank.rglob("*"):
        if path.is_file() and ".git" not in path.parts:
            assert "ghu_placeholder" not in path.read_text(errors="replace")
    # Not installed yet: the panel offers the install, and asks again after it.
    api.server.installed = False
    asked = api.post("/sources/github/connect/installation").json()
    assert asked["installed"] is False and asked["installUrl"] == "https://github.com/apps/cicada-memory/installations/new"
    api.server.installed = True
    assert api.post("/sources/github/connect/installation").json()["installed"] is True


def test_a_cancelled_or_expired_code_connects_nothing(api, bank, sign_in):
    sign_in.answers = [{"error": "access_denied"}]
    api.post("/sources/github/connect")
    sign_in.clock["now"] += 5
    denied = api.post("/sources/github/connect/poll").json()
    assert denied["state"] == "denied" and "cancelled" in denied["words"] and not github.is_connected()
    api.post("/sources/github/connect")
    sign_in.clock["now"] += 901
    assert api.post("/sources/github/connect/poll").json()["state"] == "expired"
    assert api.post("/sources/github/connect/poll").json()["state"] == "none"


def test_without_a_registered_app_the_token_is_the_fallback(api, monkeypatch):
    monkeypatch.setattr(github_auth, "CLIENT_ID", "")
    assert api.get("/sources/github/connect").json()["available"] is False
    refused = api.post("/sources/github/connect")
    assert refused.status_code == 409 and "Use a token instead" in refused.json()["detail"]
    fields = api.get("/sources/connectors/github").json()["fields"]
    assert [f["name"] for f in fields] == [github.TOKEN_ENV]                  # the token path stays, behind it


def test_a_token_about_to_lapse_is_renewed_with_the_client_id_alone(bank, sign_in):
    sign_in.answers = [{"access_token": "ghu_second", "refresh_token": "ghr_second", "expires_in": 28800}]
    github_auth.save({"access_token": "ghu_first", "refresh_token": "ghr_first", "expires_in": 100})
    asyncio.run(github_auth.fresh_token())
    [(url, form)] = sign_in.calls
    assert url.endswith(github_auth.TOKEN_PATH) and form == {"client_id": "Iv1.placeholder0000",
                                                             "grant_type": "refresh_token",
                                                             "refresh_token": "ghr_first"}
    assert secrets.load_secrets()[github.TOKEN_ENV] == "ghu_second"
    asyncio.run(github_auth.fresh_token())                                       # fresh now: nothing asked
    assert len(sign_in.calls) == 1


def test_revoke_forgets_every_part_of_the_sign_in_and_keeps_the_pages(api, bank, sign_in):
    sign_in.answers = [{"access_token": "ghu_placeholder", "refresh_token": "ghr_placeholder", "expires_in": 28800}]
    api.post("/sources/github/connect")
    sign_in.clock["now"] += 5
    assert api.post("/sources/github/connect/poll").json()["state"] == "connected"
    assert api.post("/sources/connectors/github/sync").json()["status"] == "ok"
    pages = sorted(p.name for p in (bank / "entities").glob("*.md"))
    readmes = bank.parent / "home" / "readmes"
    assert pages and list(readmes.rglob("*.json"))
    gone = api.delete("/sources/connectors/github/credentials").json()
    assert gone["connected"] is False
    assert not any(secrets.has_secret(n) for n in github.SECRET_NAMES)
    assert not list(readmes.rglob("*.json")) and github_auth.account() == {}
    assert sorted(p.name for p in (bank / "entities").glob("*.md")) == pages
    assert api.get("/sources/github/connect").json()["connected"] is False


def test_the_sign_in_transport_refuses_any_other_address():
    for url in ("https://elsewhere.example/login/device/code", "https://github.com/login/other",
                "http://github.com/login/device/code", "https://github.com/login/device/code?x=1"):
        with pytest.raises(tier2.base.ConnectorError):
            asyncio.run(github_auth.oauth_transport(url, {}))


def test_the_registration_link_asks_for_read_only_permissions_and_no_webhook():
    from urllib.parse import parse_qs, urlparse

    link = urlparse(github_auth.register_url())
    assert link.netloc == "github.com" and link.path == "/settings/apps/new"
    q = {k: v[0] for k, v in parse_qs(link.query).items()}
    assert {k: q[k] for k in ("metadata", "contents", "starring")} == {"metadata": "read", "contents": "read",
                                                                     "starring": "read"}
    assert q["webhook_active"] == "false" and q["public"] == "true"
    assert all(v == "read" for v in github_auth.MANIFEST["default_permissions"].values())
    assert not any(k.endswith("_url") or k == "callback_urls[]" for k in q)        # nothing to redirect to


def test_the_cli_commands_call_the_backends_routes_as_the_person(monkeypatch):
    from types import SimpleNamespace

    from api import cli_app
    from api.services import cli_map

    rows = {r.name: r for r in cli_map.ROWS}
    assert not rows["github repos"].mutates and "github add" not in rows
    assert rows["github connect"].person and rows["github connect"].mutates
    assert rows["github project"].person and [a.prop for a in rows["github project"].args] == [
        "full_name", "project", "remove"]
    sent: list[tuple] = []
    asked: list[str] = []
    polls = iter([{"state": "pending", "interval": 1},
                  {"state": "connected", "status": {"installed": False,
                                                    "installUrl": "https://github.com/apps/x/installations/new"}}])

    def fake_call(boot, method, path, **kw):
        sent.append((method, path, kw.get("body")))
        if path == "/sources/github/repos" and method == "GET":
            return {"connected": True, "owned": [{"fullName": "bob-example/alpha-project", "private": True,
                                                  "entityId": "media-alpha",
                                                  "projects": [{"project": "alpha", "name": "alpha", "how": "user"}]}],
                    "starred": [{"fullName": "example-org/widget-kit", "starred": True, "entityId": "widget-kit"}]}
        if path == "/sources/github/connect":
            return {"userCode": "ABCD-1234", "verificationUri": "https://github.com/login/device", "interval": 1,
                    "expiresAt": 0}
        if path == "/sources/github/connect/poll":
            return next(polls)
        return {"project": "alpha", "created": False}

    monkeypatch.setattr(cli_app, "call", fake_call)
    monkeypatch.setattr(cli_app, "require_person", asked.append)
    import time as _time

    monkeypatch.setattr(_time, "sleep", lambda s: None)
    boot = SimpleNamespace(probe={})
    listed = cli_app.cmd_github_repos(boot, SimpleNamespace())
    assert "bob-example/alpha-project [private] — media-alpha · in alpha (alpha)" in listed.text
    assert "example-org/widget-kit — widget-kit" in listed.text
    connected = cli_app.cmd_github_connect(boot, SimpleNamespace())
    assert connected.text.startswith("GitHub is connected. To bring in your own repositories, install Cicada")
    linked = cli_app.cmd_github_project(boot, SimpleNamespace(full_name="bob-example/alpha-project", project="alpha",
                                                              remove=False))
    assert linked.text == "Linked bob-example/alpha-project to your project alpha."
    assert sent[-1] == ("POST", "/sources/github/repos/project",
                        {"fullName": "bob-example/alpha-project", "via": "cli", "remove": False, "project": "alpha"})
    unlinked = cli_app.cmd_github_project(boot, SimpleNamespace(full_name="bob-example/alpha-project",
                                                                project="alpha", remove=True))
    assert unlinked.text.startswith("Unlinked bob-example/alpha-project from alpha")
    assert len(asked) == 3                               # every write refuses from an agent's shell


# --- review of #583: the real size cap, rate limits ------------------------------------------------------------------



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

