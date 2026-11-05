"""A page for every recording, video, Voice Memo and photo the person adds (ROR-117 / G43, ruling 68): one writer
(``media_pages``), no model, the words kept outside the bank and drawn at view time, taken out in one commit.

Synthetic names and words only; the store is the real one under a scratch ``CICADA_HOME``, the bank a real git repo.
"""
from __future__ import annotations

import hashlib
import subprocess
import time

import pytest

from _synthetic_bank import _bank
from api.services import demo_guard, git_service, markdown_parser, media_files, media_pages, quiet_pages
from api.services import write_admission

WORDS = "We settled the zebra-crossing budget on Tuesday."


@pytest.fixture
def bank(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    return _bank(tmp_path)


def sha(n: int) -> str:
    return hashlib.sha256(str(n).encode()).hexdigest()


def add(bank, n=1, *, name=None, kind="audio", words=WORDS, by="Speech model A", **kw):
    segs = [{"start": 0, "end": 4, "text": words}, {"start": 5, "end": 9, "text": "And then lunch."}] if words else []
    return media_files.record_media(bank, name=name or f"Standup {n}.m4a", kind=kind, sha256=sha(n), size=10,
                                    duration_s=65, language="en", segments=segs,
                                    transcribed_by=by if segs else None, **kw)["id"]


def page_of(bank, fid):
    return markdown_parser.parse(bank / "entities" / f"{media_pages.page_for(bank, fid)}.md")


def git(bank, *args):
    return subprocess.run(["git", "-C", str(bank), *args], check=True, capture_output=True, text=True).stdout


def commits(bank):
    return int(git(bank, "rev-list", "--count", "HEAD").strip())


# --------------------------------------------------------------------------- the page


def test_an_added_item_gets_one_page_with_what_belongs_in_git_and_never_its_words(bank):
    fid = add(bank)
    out = media_pages.sync(bank)
    assert out["created"] == 1
    parsed = page_of(bank, fid)
    fm = parsed.frontmatter
    assert fm["type"] == "media" and fm["name"] == "Standup 1" and fm["aliases"] == ["Standup 1.m4a"]
    assert fm["media"]["kind"] == "file" and fm["media"]["file_id"] == fid and fm["media"]["media_type"] == "recording"
    assert fm["media"]["duration_s"] == 65 and fm["media"]["transcribed_by"] == "Speech model A"
    assert fm["media"]["recorded_at"] and "url" not in fm["media"]
    assert fm["source_episodes"] == [] and fm["decay_class"] == "evergreen"
    assert "## Summary" in parsed.body and "## Why it matters" in parsed.body
    page_path = bank / "entities" / f"{media_pages.page_for(bank, fid)}.md"
    assert "zebra" not in page_path.read_text(), "the transcript never enters the page"
    assert "zebra" not in git(bank, "log", "-p", "--all"), "nor git history"
    assert media_pages.is_file_page(fm) and media_pages.file_id_of(fm) == fid


def test_a_second_sync_writes_and_commits_nothing(bank):
    add(bank)
    media_pages.sync(bank)
    before = commits(bank)
    assert media_pages.sync(bank) == {"created": 0, "updated": 0, "retired": 0, "pending": 0}
    assert commits(bank) == before


def test_the_same_bytes_added_again_reuse_the_page_and_two_files_never_share_one(bank):
    first = add(bank, 1, name="Standup.m4a")
    media_pages.sync(bank)
    again = add(bank, 1, name="Standup.m4a", words="A better transcript about gardens.", by="Speech model B")
    assert again == first
    other = add(bank, 2, name="Standup.m4a")
    out = media_pages.sync(bank)
    assert out["created"] == 1 and out["updated"] == 1
    assert media_pages.page_for(bank, first) != media_pages.page_for(bank, other)
    assert page_of(bank, first).frontmatter["media"]["transcribed_by"] == "Speech model B"
    ids = [p.stem for p in (bank / "entities").glob("file-*.md")]
    assert len(ids) == 2 and len(set(ids)) == 2


def test_a_voice_memo_is_dated_by_its_own_recording_and_a_photo_has_no_words(bank):
    memo = media_files.record_media(bank, name="Memo", kind="audio", sha256=sha(5), source="voice_memos",
                                    source_key="memo-1", recorded_at="2026-03-02T10:00:00Z", duration_s=30)["id"]
    photo = add(bank, 6, name="IMG_0001.jpg", kind="image", words="")
    media_pages.sync(bank)
    memo_fm = page_of(bank, memo).frontmatter
    assert memo_fm["media"]["recorded_at"] == "2026-03-02T10:00:00+00:00"
    photo_fm = page_of(bank, photo).frontmatter
    assert photo_fm["media"]["media_type"] == "photo" and "transcribed_by" not in photo_fm["media"]
    assert photo_fm["tags"] == ["photo"]


def test_a_page_the_person_renamed_keeps_their_name_and_a_removed_page_is_not_made_again(bank):
    fid, gone = add(bank, 1), add(bank, 2)
    media_pages.sync(bank)
    parsed = page_of(bank, fid)
    parsed.frontmatter["name"] = "The Tuesday call"
    markdown_parser.write(bank / "entities" / f"{media_pages.page_for(bank, fid)}.md", parsed.frontmatter, parsed.body)
    (bank / "entities" / f"{media_pages.page_for(bank, gone)}.md").unlink()
    add(bank, 1, words="New words here.")
    out = media_pages.sync(bank)
    assert out["created"] == 0
    assert page_of(bank, fid).frontmatter["name"] == "The Tuesday call"
    assert not list((bank / "entities").glob("file-standup-2*.md"))


# --------------------------------------------------------------------------- quiet, names, rails


def test_the_page_is_quiet_until_a_conversation_mentions_it_and_a_name_lands_on_it(bank):
    fid = add(bank)
    media_pages.sync(bank)
    page = media_pages.page_for(bank, fid)
    assert quiet_pages.page_is_quiet(bank, page)
    from api.services import entity_resolver

    existing = [{"id": page, "frontmatter": page_of(bank, fid).frontmatter}]
    match = entity_resolver._find_direct_candidate_match(
        {"name": "Standup 1", "type": "event"}, entity_resolver.existing_by_name(existing), {})
    assert match is not None and match["candidate"]["id"] == page, "a later mention lands here, never on a second page"
    parsed = page_of(bank, fid)
    parsed.frontmatter["source_episodes"] = ["ep_2026-09-01_001"]
    markdown_parser.write(bank / "entities" / f"{page}.md", parsed.frontmatter, parsed.body)
    assert not quiet_pages.page_is_quiet(bank, page)


def test_decay_class_is_the_one_resolver_and_stage_one_never_makes_media():
    from api.services import decay_policy, entity_types

    assert decay_policy.default_class_for("media", source="media").value == "evergreen"
    assert entity_types.producible("media") != "media"


def test_a_demo_bank_gets_no_page(bank, monkeypatch):
    add(bank)
    monkeypatch.setattr(demo_guard, "is_demo", lambda mp: True)
    assert media_pages.sync(bank)["created"] == 0
    assert not list((bank / "entities").glob("file-*.md"))
    assert media_pages.start_sync(bank) is False


def test_sleep_holding_the_pages_loses_nothing(bank, monkeypatch):
    fid = add(bank)
    with monkeypatch.context() as sleeping:
        sleeping.setattr(write_admission, "holding", lambda: True)
        with pytest.raises(write_admission.SleepHolding):
            media_pages.sync(bank)
    assert not list((bank / "entities").glob("file-*.md"))
    assert media_pages.sync(bank)["created"] == 1 and media_pages.page_for(bank, fid)


def _recording_and_person(bank):
    """A recording page named as a person, and a person page of the same title with a different id."""
    fid = add(bank, name="Alice Smith.m4a")
    media_pages.sync(bank)
    page = media_pages.page_for(bank, fid)
    recording = {"id": page, "frontmatter": page_of(bank, fid).frontmatter}
    person = {"id": "alice-smith-2", "frontmatter": {"name": "Alice Smith", "type": "person", "status": "active"}}
    return recording, person


def test_a_person_mention_never_joins_a_recording_page_named_as_they_are(bank):
    from api.services import entity_resolver as er

    recording, person = _recording_and_person(bank)
    mention = {"name": "Alice Smith", "type": "person"}
    same_title = {"alice smith": [recording]}
    for kw in ({}, {"same_title": same_title}):
        assert er._find_direct_candidate_match(mention, er.existing_by_name([recording]), {}, {}, **kw) is None
    close = {"name": "Alice Smyth", "type": "person"}
    assert er._find_direct_candidate_match(close, er.existing_by_name([recording]), {}, {}) is None
    # The recording's `clip.m4a`-style alias is no person's name either.
    assert er._alias_index(er.existing_by_name([recording])).get("alice smith.m4a")
    assert er._answered_match({"name": "Alice Smith.m4a", "type": "person"},
                              er._alias_index(er.existing_by_name([recording]))) is None
    # A concept or media mention naming the recording still lands on it where the type allows.
    event = er._find_direct_candidate_match({"name": "Alice Smith", "type": "event"}, er.existing_by_name([recording]), {})
    assert event is not None and event["candidate"]["id"] == recording["id"]


def test_a_person_page_keeps_the_name_whatever_the_order_beside_a_recording_page(bank):
    from api.services import entity_resolver as er

    recording, person = _recording_and_person(bank)
    mention = {"name": "Alice Smith", "type": "person"}
    for pages in ([recording, person], [person, recording]):
        assert er.existing_by_name(pages)["alice smith"]["id"] == person["id"]
        match = er._find_direct_candidate_match(mention, er.existing_by_name(pages), {}, {},
                                                {"alice smith": pages})
        assert match is not None and match["candidate"]["id"] == person["id"]


def _resolve(bank, existing, kind):
    import asyncio
    from types import SimpleNamespace

    from api.services import entity_resolver as er

    ep = "ep_2026-10-15_001"
    entity = {"name": "Alice Smith", "type": kind, "confidence": 0.9, "description": "A colleague.",
              "source_episode": ep, "source_episode_timestamp": "2026-10-15T10:00:00Z"}
    settings = SimpleNamespace(memory_path=bank, litellm_model="fake", litellm_disambiguation_model="fake",
                               sleep_promotion_threshold=2, sleep_resolve_concurrency=1)

    async def no_judge(**_kw):
        return "different"

    return asyncio.run(er.resolve([{"episode_id": ep, "origin": "chat", "entities": [entity], "relationships": []}],
                                  existing, settings))


def test_stage_two_leaves_a_recording_page_out_of_a_persons_name(bank, monkeypatch):
    from api.services import entity_resolver as er

    monkeypatch.setattr(er.SqliteVecIndexer, "_rebuild_pending_index", lambda self, entries: None)
    monkeypatch.setattr(er, "_llm_judge_same_entity", lambda **kw: _no(kw))
    recording, person = _recording_and_person(bank)
    for pages in ([recording, person], [person, recording]):
        out = _resolve(bank, pages, "person")
        assert recording["id"] not in {c["id"] for c in out["changes"]}
        assert out["name_to_id"].get("alice smith") != recording["id"]
        assert [c["id"] for c in out["changes"]] == [person["id"]]
    alone = _resolve(bank, [recording], "person")
    assert recording["id"] not in {c["id"] for c in alone["changes"]}
    assert alone["name_to_id"].get("alice smith") != recording["id"]


async def _no(_kw):
    return "different"


# --------------------------------------------------------------------------- the cost


def test_a_thousand_items_catch_up_in_a_few_commits(bank, capsys):
    for n in range(1, 1001):
        media_files.record_media(bank, name=f"Recording {n}.m4a", kind="audio", sha256=sha(n), size=1,
                                 duration_s=60, segments=[{"start": 0, "end": 1, "text": f"words {n}"}],
                                 transcribed_by="Speech model A")
    before = commits(bank)
    started = time.perf_counter()
    out = media_pages.sync(bank)
    took = time.perf_counter() - started
    assert out["created"] == 1000 and commits(bank) - before == 1000 // media_pages.BATCH
    started = time.perf_counter()
    assert media_pages.sync(bank)["created"] == 0
    again = time.perf_counter() - started
    with capsys.disabled():
        print(f"\nmedia_pages 1,000 items: first sync {took:.1f}s in {commits(bank) - before} commits; "
              f"second {again:.2f}s")


# --------------------------------------------------------------------------- taking it out


def test_a_retire_source_removes_the_page_in_one_commit_and_history_keeps_it(bank):
    gone, kept = (media_files.record_media(bank, name=f"Memo {k}", kind="audio", sha256=sha(k), source="voice_memos",
                                           source_key=f"memo-{k}", recorded_at="2026-03-02T10:00:00Z",
                                           segments=[{"start": 0, "end": 1, "text": WORDS}])["id"] for k in (1, 2))
    media_pages.sync(bank)
    gone_page = media_pages.page_for(bank, gone)
    assert media_files.retire_source(bank, "voice_memos", {"memo-2"}) == 1
    before = commits(bank)
    out = media_pages.sync(bank)
    assert out["retired"] == 1 and commits(bank) - before == 1
    assert not (bank / "entities" / f"{gone_page}.md").exists() and media_pages.page_for(bank, kept)
    message = git(bank, "log", "-1", "--format=%B")
    assert f"entities/{gone_page}.md: deleted" in message and "Cicada-Author: cicada" in message
    assert "Memo 1" in git(bank, "log", "-p", "--all", "--", f"entities/{gone_page}.md"), "history keeps the page"
    assert "zebra" not in git(bank, "log", "-p", "--all")


def test_a_sleep_run_holding_the_pages_defers_a_retirement_without_losing_it(bank, monkeypatch):
    fid = add(bank)
    media_pages.sync(bank)
    page = media_pages.page_for(bank, fid)
    assert media_files.delete(bank, fid, by=git_service.USER_AUTHOR)
    with monkeypatch.context() as sleeping:
        sleeping.setattr(write_admission, "holding", lambda: True)
        with pytest.raises(write_admission.SleepHolding):
            media_pages.sync(bank)
    assert (bank / "entities" / f"{page}.md").exists()
    assert media_pages.sync(bank)["retired"] == 1
    assert not (bank / "entities" / f"{page}.md").exists()
    assert "Cicada-Author: user" in git(bank, "log", "-1", "--format=%B")


def _wait_for_runner(bank):
    key = str(bank.resolve())
    runner = media_pages._RUNNERS[key]
    if runner.thread is not None:
        runner.thread.join(10)
    assert runner.thread is None or not runner.thread.is_alive()
    return runner


@pytest.fixture
def runners():
    media_pages._RUNNERS.clear()
    yield media_pages._RUNNERS
    for r in media_pages._RUNNERS.values():
        if r.timer is not None:
            r.timer.cancel()
    media_pages._RUNNERS.clear()


def test_the_last_file_deleted_while_sleep_holds_is_retired_by_a_later_start_sync(bank, monkeypatch, runners):
    fid = add(bank)
    media_pages.sync(bank)
    page = media_pages.page_for(bank, fid)
    assert media_files.delete(bank, fid, by=git_service.USER_AUTHOR) and not media_files.any_files(bank)
    with monkeypatch.context() as sleeping:
        sleeping.setattr(write_admission, "holding", lambda: True)
        assert media_pages.sync_or_later(bank) is None
    # The retry was armed although no runner existed for the bank yet.
    assert runners[str(bank.resolve())].timer is not None
    assert (bank / "entities" / f"{page}.md").exists()
    assert media_pages.start_sync(bank) is True, "a queued retirement outlives an empty store"
    _wait_for_runner(bank)
    assert not (bank / "entities" / f"{page}.md").exists() and not media_pages._journal(bank)


def test_a_crash_after_the_store_delete_is_retired_by_the_next_startup(bank, runners):
    fid = add(bank)
    media_pages.sync(bank)
    page = media_pages.page_for(bank, fid)
    media_pages.queue_retirement(bank, [fid], by=git_service.USER_AUTHOR)
    import shutil

    shutil.rmtree(media_files.root(bank) / fid)          # the process dies here
    assert not media_files.any_files(bank) and (bank / "entities" / f"{page}.md").exists()
    assert media_pages.start_sync(bank) is True
    _wait_for_runner(bank)
    assert not (bank / "entities" / f"{page}.md").exists()
    assert media_pages.start_sync(bank) is False, "nothing stored and nothing queued does nothing"


# --------------------------------------------------------------------------- the routes


def _client(bank, monkeypatch):
    from fastapi.testclient import TestClient

    from api import config, main
    from api.services import image_index

    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    config.get_settings.cache_clear()
    monkeypatch.setattr(image_index, "start_refresh", lambda mp, **kw: True)
    monkeypatch.setattr(media_pages, "start_sync", lambda mp, **kw: True)
    return TestClient(main.app)


def test_the_transcript_route_serves_the_words_and_delete_takes_the_page_out(bank, monkeypatch):
    c = _client(bank, monkeypatch)
    with c:
        fid = add(bank)
        media_pages.sync(bank)
        got = c.get(f"/files/{fid}/transcript")
        assert got.status_code == 200
        body = got.json()
        assert body["segments"][0] == {"start": 0.0, "end": 4.0, "text": WORDS}
        assert body["transcribedBy"] == "Speech model A" and body["wordsBy"] == "the recording"
        assert c.get("/files/0123456789abcdef/transcript").status_code == 404
        listed = c.get("/files").json()["files"]
        assert listed[0]["page"] == media_pages.page_for(bank, fid)
        page = media_pages.page_for(bank, fid)
        entity = c.get(f"/entities/{page}").json()
        assert entity["media"]["fileId"] == fid and entity["media"]["url"] == "" and entity["media"]["kind"] == "file"
        assert c.delete(f"/files/{fid}").json() == {"deleted": fid}
        assert not (bank / "entities" / f"{page}.md").exists()
        assert c.get(f"/files/{fid}/transcript").status_code == 404
        assert "Cicada-Author: user" in git(bank, "log", "-1", "--format=%B")
        assert "zebra" not in git(bank, "log", "-p", "--all")
        assert c.delete(f"/files/{fid}").status_code == 404


def test_the_post_asks_for_a_page_and_never_waits_for_it(bank, monkeypatch):
    c = _client(bank, monkeypatch)
    asked = []
    monkeypatch.setattr(media_pages, "start_sync", lambda mp, **kw: asked.append(kw) or True)
    with c:
        body = {"name": "talk.m4a", "kind": "audio", "sha256": sha(9), "durationS": 5,
                "segments": [{"start": 0, "end": 1, "text": "Hi."}]}
        assert c.post("/files/media", json=body).status_code == 200
        assert asked and asked[0]["delay_s"] == media_pages.SETTLE_S
        assert not list((bank / "entities").glob("file-*.md")), "the request wrote no page"


# --------------------------------------------------------------------------- agents and contributors


class Ctx:
    skipped_inbox_ids = ()
    state_hint_sent = True
    is_cli = False
    read_surface = "test"

    def __init__(self, bank, *, remote, sources):
        self.is_remote, self.raw_excerpts, self._bank = remote, sources, bank

    def memory_path(self):
        return self._bank

    def can(self, _name):
        return True


def test_recall_detail_says_how_much_transcript_and_never_returns_it(bank):
    from api.services import mcp_tools

    fid = add(bank)
    media_pages.sync(bank)
    page = media_pages.page_for(bank, fid)
    local = str(mcp_tools.recall_detail(Ctx(bank, remote=False, sources=True), page))
    assert "2 segments" in local and "1:05" in local and "zebra" not in local and "lunch" not in local
    with_scope = str(mcp_tools.recall_detail(Ctx(bank, remote=True, sources=True), page))
    assert "2 segments" in with_scope and "zebra" not in with_scope
    without = str(mcp_tools.recall_detail(Ctx(bank, remote=True, sources=False), page))
    assert "segments" not in without and "zebra" not in without and "lunch" not in without


def test_the_transcriber_is_a_contributor_only_when_a_transcript_and_a_name_exist(bank):
    from api.services import provenance

    with_words, without = add(bank, 1), add(bank, 2, words="")
    media_pages.sync(bank)
    got = provenance.entity_provenance(bank, bank / "entities" / f"{media_pages.page_for(bank, with_words)}.md")
    named = [c for c in got.contributors if c.role == "transcribed"]
    assert [c.author for c in named] == ["Speech model A"] and named[0].claims == 0 and named[0].commits == 0
    none = provenance.entity_provenance(bank, bank / "entities" / f"{media_pages.page_for(bank, without)}.md")
    assert not [c for c in none.contributors if c.role == "transcribed"]

