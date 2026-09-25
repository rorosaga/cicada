"""Round 4 (G160 first slice; decisions addendum 3): Chrome's OPEN tab groups — the backend half. The app reads the
profile's `Sessions/` file and posts each group's title, colour and its tabs' titles and links; each group is one
snapshot episode through the G20 stager, scrubbed, rewritten in place when it changes, tombstoned when it closes,
committed once per sync as the person. Synthetic groups on example.com only."""
from __future__ import annotations

import subprocess

import pytest
from fastapi.testclient import TestClient

from _synthetic_bank import _bank
from api import config, main
from api.services import bank_index, demo_guard, markdown_parser, source_overview, tab_groups


@pytest.fixture
def client(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    yield TestClient(main.app), memory
    config.get_settings.cache_clear()


def _group(title="alpha-project", color="blue", key="aa" * 16, saved=None, tabs=None, collapsed=False):
    return {"key": key, "title": title, "color": color, "collapsed": collapsed, "savedGuid": saved,
            "tabs": tabs if tabs is not None else [
                {"title": "Design doc", "url": "https://example.com/alpha/doc"},
                {"title": "Issue 12", "url": "https://example.com/alpha/issues/12"},
            ]}


def _post(c, groups, browser="chrome", profile="Default"):
    return c.post("/sources/tab-groups/sync", json={"browser": browser, "profile": profile, "groups": groups})


def _episodes(memory):
    out = {}
    for path in sorted((memory / "episodes").glob("*.md")):
        parsed = markdown_parser.parse(path)
        sid = str(parsed.frontmatter.get("source_id") or "")
        if sid.startswith(tab_groups.SOURCE_PREFIX):
            out[sid] = parsed
    return out


def _head(memory):
    return subprocess.run(["git", "-C", str(memory), "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=True).stdout.strip()


def test_a_first_sync_stages_one_episode_per_group_and_commits_once_as_the_person(client):
    c, memory = client
    r = _post(c, [_group(), _group(title="Papers to read", color="green", key="bb" * 16)])
    assert r.status_code == 200, r.text
    assert r.json() == {"created": 2, "updated": 0, "unchanged": 0, "tombstoned": 0, "groups": 2, "tabs": 4,
                        "bank": memory.name}
    episodes = _episodes(memory)
    alpha = next(ep for ep in episodes.values() if ep.body.startswith("# Tab group: alpha-project"))
    assert alpha.frontmatter["origin"] == "chrome-tab-group" and alpha.frontmatter["source"] == "tab-group"
    assert alpha.frontmatter["tab_group_color"] == "blue" and alpha.frontmatter["processed"] is False
    assert alpha.body.startswith("# Tab group: alpha-project\n\n**Browser:** Chrome\n**Colour:** blue\n**Open tabs:** 2")
    assert "- Design doc — https://example.com/alpha/doc" in alpha.body
    log = subprocess.run(["git", "-C", str(memory), "log", "-1", "--format=%B"], capture_output=True, text=True,
                         check=True).stdout
    assert log.startswith("Tab groups sync") and "capture/tab-groups" in log and "Cicada-Author: user" in log


def test_the_same_snapshot_again_changes_nothing_and_folding_a_group_is_not_a_change(client):
    c, memory = client
    _post(c, [_group()])
    before = _head(memory)
    body = _post(c, [_group(collapsed=True)]).json()
    assert (body["unchanged"], body["updated"]) == (1, 0)
    assert _head(memory) == before


def test_a_new_tab_rewrites_the_groups_episode_in_place_and_requeues_it(client):
    c, memory = client
    _post(c, [_group()])
    [(sid, first)] = _episodes(memory).items()
    first_id = first.frontmatter["id"]
    tabs = _group()["tabs"] + [{"title": "Notes", "url": "https://example.com/alpha/notes"}]
    assert _post(c, [_group(tabs=tabs)]).json()["updated"] == 1
    [(sid2, second)] = _episodes(memory).items()
    assert (sid2, second.frontmatter["id"], second.frontmatter["processed"]) == (sid, first_id, False)
    assert "**Open tabs:** 3" in second.body


def test_identity_is_the_saved_guid_else_title_and_colour_else_the_session_token():
    assert tab_groups.identity({"savedGuid": "g-1", "title": "alpha", "color": "blue"}) == "saved:g-1"
    named = tab_groups.identity({"title": "  Alpha   Project ", "color": "blue", "key": "k1"})
    assert named == tab_groups.identity({"title": "alpha project", "color": "blue", "key": "k2"}), "a restart keeps it"
    assert named != tab_groups.identity({"title": "alpha project", "color": "red", "key": "k1"})
    assert tab_groups.identity({"title": "", "color": "grey", "key": "cc" * 16}) == "token:" + "cc" * 16


def test_a_saved_group_keeps_its_episode_through_a_rename(client):
    c, memory = client
    _post(c, [_group(saved="guid-1")])
    body = _post(c, [_group(title="alpha-project v2", saved="guid-1")]).json()
    assert (body["updated"], body["created"], body["tombstoned"]) == (1, 0, 0)


def test_a_closed_group_is_tombstoned_only_for_the_browser_and_profile_posted_and_comes_back(client):
    c, memory = client
    _post(c, [_group(), _group(title="Other", key="bb" * 16)])
    _post(c, [_group(title="Work profile", key="dd" * 16)], profile="Profile 1")
    assert _post(c, [_group()]).json()["tombstoned"] == 1
    episodes = _episodes(memory)
    closed = [ep for ep in episodes.values() if ep.frontmatter.get("source_deleted_at")]
    assert [("Other" in ep.body) for ep in closed] == [True], "Profile 1's group is untouched"
    assert _post(c, [_group(), _group(title="Other", key="bb" * 16)]).json()["tombstoned"] == 0
    assert not any(ep.frontmatter.get("source_deleted_at") for ep in _episodes(memory).values())


def test_only_web_pages_are_kept_a_fragment_goes_and_secrets_are_scrubbed(client):
    c, memory = client
    tabs = [
        {"title": "Settings", "url": "chrome://settings"},
        {"title": "A file", "url": "file:///tmp/alpha.txt"},
        {"title": "Video", "url": "https://example.com/watch?v=abc123#t=40"},
        {"title": "Callback", "url": "https://example.com/cb?token=" + "a1" * 20},
    ]
    _post(c, [_group(title="alpha sk-" + "Z" * 24, tabs=tabs), _group(title="Empty", key="ee" * 16,
                                                                          tabs=[{"title": "New tab", "url": "chrome://newtab"}])])
    [(sid, ep)] = _episodes(memory).items()
    assert "chrome://" not in ep.body and "file://" not in ep.body
    assert "https://example.com/watch?v=abc123" in ep.body and "#t=40" not in ep.body, "the query stays, the fragment goes"
    assert "a1a1a1" not in ep.body and "Z" * 24 not in ep.body and "Z" * 24 not in ep.frontmatter["title"]


@pytest.mark.parametrize("payload", [
    {"browser": "arc", "profile": "Default", "groups": []},
    {"browser": "chrome", "profile": "../Default", "groups": []},
])
def test_a_request_the_backend_cannot_trust_is_refused(client, payload):
    c, memory = client
    assert c.post("/sources/tab-groups/sync", json=payload).status_code == 422
    assert _episodes(memory) == {}


def test_too_many_groups_is_refused(client, monkeypatch):
    c, memory = client
    monkeypatch.setattr(tab_groups, "MAX_GROUPS", 1)
    assert _post(c, [_group(), _group(key="bb" * 16)]).status_code == 413


def test_a_demo_bank_is_refused_and_nothing_is_written(client, monkeypatch):
    c, memory = client
    monkeypatch.setattr(demo_guard, "is_demo", lambda path: True)
    assert _post(c, [_group()]).status_code == 409
    assert _episodes(memory) == {}


def test_the_channel_appears_once_synced_with_its_tabs(client):
    c, _ = client

    def rows():
        return {ch["id"]: ch for ch in c.get("/sources/channels").json()["channels"]}

    assert "chrome-tab-groups" not in rows()
    _post(c, [_group(), _group(title="Papers", key="bb" * 16)])
    row = rows()["chrome-tab-groups"]
    assert (row["label"], row["connected"], row["count"], row["countNoun"], row["actions"]) == (
        "Chrome tab groups", True, 2, "tab group", ["sync", "manage"])
    assert row["parts"] == [{"key": "tabs", "count": 4}]
    assert "chrome-tab-groups" in {spec.id for spec in source_overview.CATALOG}
