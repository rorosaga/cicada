"""G246 (ruling 81, plan Track K): "Keep as a page" on a saved post, and the way back.

One stamp (`kept_as_page`) on the post's own save, written under the episode lock, committed alone as the person, counted
by `saved_posts` as an earned sign. The route refuses a demo bank, waits Sleep's window out, and is dark: until the flip
(`saved_posts.HIDE_POSTS`) nothing is offered. Real writers (`POST /sources/save`) over a synthetic bank, a fake fetch.
"""
from __future__ import annotations

import subprocess

import pytest
from fastapi.testclient import TestClient

from _synthetic_bank import _bank
from api import config, main
from api.services import bank_index, graph_builder, keep_as_page, markdown_parser, media_ingestor, saved_posts, sleep_cycle

POST = "https://x.com/alex_example/status/1234567890123"
WORK = "https://example.com/an-article"


@pytest.fixture
def env(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    graph_builder.reset_cache()

    async def offline(url, client, from_bookmark_file=False):
        return media_ingestor.MediaMeta(title="A saved post", description="", site="x.com", media_type="url")

    monkeypatch.setattr(media_ingestor, "enrich", offline)
    client = TestClient(main.app)
    yield client, memory
    config.get_settings.cache_clear()
    bank_index.invalidate()
    graph_builder.reset_cache()


@pytest.fixture(autouse=True)
def _setting_pinned(monkeypatch):
    """The shipped setting is on (ruling 81, `saved_posts.HIDE_POSTS`); this file pins its own: off, unless a test asks
    for `on`. Never the default, which is not what these tests assert."""
    monkeypatch.setattr(saved_posts, "HIDE_POSTS", False)


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(saved_posts, "HIDE_POSTS", True)


def _git(memory, *args):
    return subprocess.run(["git", "-C", str(memory), *args], check=True, capture_output=True, text=True).stdout


def _save(client, url=POST):
    r = client.post("/sources/save", json={"url": url})
    assert r.status_code == 200, r.text
    return r.json()


def _episode(memory, url):
    from api.services import saved_why

    episode_id, page_id, path = saved_why.find_episode(memory, url)
    return episode_id, page_id, path


def _keep(client, url=POST, kept=True):
    return client.post("/sources/keep-as-page", json={"url": url, "kept": kept})


def _state(client, url=POST):
    r = client.get("/sources/keep-as-page", params={"url": url})
    assert r.status_code == 200, r.text
    return r.json()


# --------------------------------------------------------------------------------------------- the click


def test_keeping_a_post_stamps_its_save_commits_as_the_person_and_changes_nothing_else(env, on):
    client, memory = env
    _save(client)
    episode_id, page_id, path = _episode(memory, POST)
    assert page_id in saved_posts.verdict(memory).rows            # a row until the click
    before = markdown_parser.parse(path)
    r = _keep(client)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "kept" and body["state"] == "kept" and body["canUndo"] is True
    assert body["mediaEntityId"] == page_id and body["episodeId"] == episode_id
    after = markdown_parser.parse(path)
    assert after.frontmatter["kept_as_page"]["at"]
    # Frontmatter only: the words, their hash and the queue are untouched, so it costs no model read.
    assert after.body == before.body
    for key in ("processed", "content_hash", "origin", "media_entity_id"):
        assert after.frontmatter.get(key) == before.frontmatter.get(key), key
    message = _git(memory, "log", "-1", "--format=%B")
    assert message.startswith("Kept a saved post as a page") and "Cicada-Author: user" in message
    assert "trigger: user/keep_as_page" in message
    assert _git(memory, "show", "--name-only", "--format=", "HEAD").split() == [f"episodes/{episode_id}.md"]
    assert _git(memory, "status", "--porcelain").strip() == ""     # nothing left dirty
    assert page_id not in saved_posts.verdict(memory).rows and page_id in saved_posts.earned_ids(memory)


def test_a_kept_post_reappears_in_the_graph_at_the_next_read(env, on):
    client, memory = env
    _save(client)
    _, page_id, _ = _episode(memory, POST)
    graph = client.get("/graph").json()
    assert page_id not in {n["id"] for n in graph["nodes"]} and graph["hiddenPosts"] == 1
    _keep(client)
    graph = client.get("/graph").json()
    assert page_id in {n["id"] for n in graph["nodes"]} and graph["hiddenPosts"] == 0
    _keep(client, kept=False)
    graph = client.get("/graph").json()
    assert page_id not in {n["id"] for n in graph["nodes"]} and graph["hiddenPosts"] == 1


def test_keeping_twice_writes_and_commits_nothing_the_second_time(env, on):
    client, memory = env
    _save(client)
    assert _keep(client).json()["status"] == "kept"
    head = _git(memory, "rev-parse", "HEAD")
    again = _keep(client).json()
    assert again["status"] == "unchanged" and again["state"] == "kept"
    assert _git(memory, "rev-parse", "HEAD") == head


def test_a_work_has_its_page_already_so_there_is_nothing_to_keep(env, on):
    client, memory = env
    _save(client, WORK)
    _, _, path = _episode(memory, WORK)
    head = _git(memory, "rev-parse", "HEAD")
    r = _keep(client, WORK)
    assert r.status_code == 200 and r.json()["status"] == "unchanged" and r.json()["state"] == "none"
    assert "kept_as_page" not in markdown_parser.parse(path).frontmatter
    assert _git(memory, "rev-parse", "HEAD") == head
    assert _state(client, WORK)["state"] == "none"


def test_a_link_that_is_not_saved_or_not_a_link_is_refused_in_words(env, on):
    client, _ = env
    assert _keep(client, "https://x.com/alex_example/status/999").status_code == 404
    assert _keep(client, "not a link").status_code == 422


# --------------------------------------------------------------------------------------------- the way back


def test_back_to_a_row_is_allowed_while_nothing_else_earned_the_page(env, on):
    client, memory = env
    _save(client)
    episode_id, page_id, path = _episode(memory, POST)
    _keep(client)
    r = _keep(client, kept=False)
    assert r.status_code == 200 and r.json()["status"] == "undone" and r.json()["state"] == "row"
    assert "kept_as_page" not in markdown_parser.parse(path).frontmatter
    message = _git(memory, "log", "-1", "--format=%B")
    assert message.startswith("Sent a saved post back to a row") and "Cicada-Author: user" in message
    assert page_id in saved_posts.verdict(memory).rows
    # And the same control keeps it again.
    assert _keep(client).json()["status"] == "kept"


def test_back_to_a_row_is_refused_once_something_else_earned_the_page(env, on):
    client, memory = env
    _save(client)
    _, page_id, path = _episode(memory, POST)
    _keep(client)
    parsed = markdown_parser.parse(path)                            # the person wrote a note on it meanwhile
    markdown_parser.write(path, {**parsed.frontmatter, "has_note": True}, parsed.body)
    bank_index.invalidate()
    state = _state(client)
    assert state["state"] == "kept" and state["canUndo"] is False and state["becauseOf"] == ["note"]
    r = _keep(client, kept=False)
    assert r.status_code == 409 and "another reason" in r.json()["detail"]
    assert "kept_as_page" in markdown_parser.parse(path).frontmatter
    assert page_id not in saved_posts.verdict(memory).rows


def test_undoing_a_post_that_was_never_kept_is_a_no_op(env, on):
    client, memory = env
    _save(client)
    head = _git(memory, "rev-parse", "HEAD")
    r = _keep(client, kept=False)
    assert r.status_code == 200 and r.json()["status"] == "unchanged" and r.json()["state"] == "row"
    assert _git(memory, "rev-parse", "HEAD") == head


def test_a_repeat_saves_inherited_stamp_goes_with_the_way_back(env, on):
    client, memory = env
    _save(client)
    _, page_id, path = _episode(memory, POST)
    _keep(client)
    twin = path.with_name("ep_2026-11-22_001.md")                    # a later save of the same post carrying the stamp
    parsed = markdown_parser.parse(path)
    markdown_parser.write(twin, {**parsed.frontmatter, "id": "ep_2026-11-22_001"}, parsed.body)
    bank_index.invalidate()
    assert _keep(client, kept=False).json()["state"] == "row"
    assert "kept_as_page" not in markdown_parser.parse(twin).frontmatter


# --------------------------------------------------------------------------------------------- dark and guarded


def test_nothing_is_offered_while_the_constant_is_off_but_the_click_still_works(env):
    client, memory = env
    assert saved_posts.HIDE_POSTS is False
    _save(client)
    assert _state(client)["state"] == "none"                        # every post is a page today: nothing to keep
    graph = client.get("/graph").json()
    assert graph["hiddenPosts"] == 0
    assert _keep(client).json()["status"] == "kept"                 # the stamp itself is not behind the constant
    assert _state(client)["state"] == "none"


def test_the_state_names_what_the_card_may_draw(env, on):
    client, _ = env
    _save(client)
    row = _state(client)
    assert row["state"] == "row" and row["canUndo"] is False and row["becauseOf"] == []
    _keep(client)
    assert _state(client)["state"] == "kept" and _state(client)["canUndo"] is True
    assert _state(client, "https://x.com/alex_example/status/999")["state"] == "none"   # not saved: a read never fails


def test_include_posts_reports_nothing_hidden(env, on):
    client, _ = env
    _save(client)
    assert client.get("/graph", params={"include_posts": "true"}).json()["hiddenPosts"] == 0


def test_a_demo_bank_refuses_the_click_and_writes_nothing(env, monkeypatch):
    from api.services import demo_guard

    client, memory = env
    _save(client)
    _, _, path = _episode(memory, POST)
    monkeypatch.setattr(demo_guard, "is_demo", lambda _p: True)
    r = _keep(client)
    assert r.status_code == 409 and r.json()["detail"] == demo_guard.REFUSAL
    assert "kept_as_page" not in markdown_parser.parse(path).frontmatter


def test_the_click_waits_sleeps_window_out_and_writes_nothing_through_it(env, monkeypatch):
    client, memory = env
    _save(client)
    _, _, path = _episode(memory, POST)
    head = _git(memory, "rev-parse", "HEAD")
    monkeypatch.setattr(sleep_cycle, "is_writing", lambda: True)
    r = _keep(client)
    assert r.status_code == 409 and "Sleep is updating" in r.json()["detail"]
    assert "kept_as_page" not in markdown_parser.parse(path).frontmatter
    assert _git(memory, "rev-parse", "HEAD") == head


def test_the_stamp_is_not_a_page_write_so_no_page_changes(env, on):
    client, memory = env
    _save(client)
    _, page_id, _ = _episode(memory, POST)
    page = memory / "entities" / f"{page_id}.md"
    before = page.read_bytes()
    _keep(client)
    assert page.read_bytes() == before                              # nothing is rewritten on the page itself


def test_a_save_with_no_page_has_nothing_to_keep(env, on):
    client, memory = env
    _save(client)
    _, page_id, _ = _episode(memory, POST)
    (memory / "entities" / f"{page_id}.md").unlink()
    bank_index.invalidate()
    assert _keep(client).status_code == 404
    assert _state(client)["state"] == "none"
    with pytest.raises(keep_as_page.KeepError):
        keep_as_page.keep(memory, url=POST)
