"""ROR-142 slice 2: the person is asked who a meeting's unnamed voice was, and their answer names it everywhere."""

from __future__ import annotations

import asyncio
import base64
import hashlib

import pytest
from fastapi import HTTPException

from api.services import (bank_index, episode_staging, folder_source as fs, inbox_tend, markdown_parser,
                          meeting_speakers as ms, meeting_transcripts as mt)

HEX = """# Planning call

- **Date:** Monday, November 23, 2026, 11:05 AM
- **Duration:** 10:00
- **Attendees:** Dana Example, Bob Example, Rodrigo Example

## Transcript

**Speaker 1** · 00:01
Welcome everyone, let's start with the recap of the pipeline.

**You** · 00:05
Hi both, happy to be here today.

**Speaker 2** · 00:09
Thanks. The ingestion part is finished and benchmarked.

**Speaker 1** · 00:15
Please keep the document short, concise and direct to the point.

**Speaker 2** · 00:20
I will. The golden set questions still need a review.

**Speaker 1** · 00:25
Do we reinvent the wheel or do we use the existing app here?

**Speaker 1** · 00:30
We will run the user study after the holidays, as agreed.

**Speaker 1** · 00:35
Send me the architecture figure of the whole pipeline please.

**Speaker 1** · 00:40
Good, that is everything for today, thank you both.
"""


def _file(rel, text, mtime=1_795_431_057.0):
    raw = text.encode("utf-8")
    return fs.IncomingFile(relpath=rel, mtime=mtime, sha256=hashlib.sha256(raw).hexdigest(),
                           content_b64=base64.b64encode(raw).decode())


@pytest.fixture
def bank(tmp_path):
    memory = tmp_path / "memory"
    for sub in ("episodes", "entities", "sources", "inbox"):
        (memory / sub).mkdir(parents=True)
    return memory


def _meeting(bank, text=HEX, rel="2026-11-23 1105 Planning call.md"):
    folder = fs.register(bank, label="Hex Meetings", path="/m", device="mac-1", kind="meetings", recorder="hex")
    fs.sync(bank, folder, [_file(rel, text)], [], tz_name="Europe/Madrid")
    bank_index.invalidate()
    path = next((bank / "episodes").glob("ep_*.md"))
    return folder, path


def _parsed(path):
    return markdown_parser.parse(path)


# --- The relabel ----------------------------------------------------------------------------------------------------


def test_a_relabel_moves_every_later_turn_stamp_and_is_a_revision(bank):
    _folder, path = _meeting(bank)
    before = _parsed(path)
    assert before.frontmatter.get("turns"), "the fixture's turns are timed"
    changed = episode_staging.relabel_in_place(path, "speaker:speaker-1", "speaker:dana-example")
    after = _parsed(path)
    assert changed == 6 and "speaker:speaker-1:" not in after.body and after.body.count("speaker:dana-example:") == 6
    for stamp in after.frontmatter["turns"]:
        assert after.body[stamp["offset"]:].startswith(f"{stamp['speaker']}: ")
    assert after.frontmatter["processed"] is False and after.frontmatter["revised"]["count"] == 1
    assert after.frontmatter["content_hash"] == episode_staging.content_hash(after.body)
    assert episode_staging.relabel_in_place(path, "speaker:nobody", "speaker:x") == 0


# --- The parser applies the person's answers ------------------------------------------------------------------------


def test_the_parser_names_an_answered_placeholder_and_never_a_name():
    folder = {"id": "f1", "recorder": "hex", "kind": "meetings"}
    d = mt.draft_for_file(folder, "a.md", HEX, mtime_iso="2026-11-23T10:00:00+00:00", sha="x",
                          speaker_names={"Speaker 1": "Dana Example", "You": "Mallory", "Dana": "Bob"})
    markers = {t.speaker for t in d.turns}
    assert "speaker:dana-example" in markers and "speaker:speaker-1" not in markers and "user" in markers
    assert d.extra["meeting"]["named_by_person"] == {"Speaker 1": "Dana Example"}
    assert "Dana Example" in d.extra["meeting"]["speakers"]


# --- The question ---------------------------------------------------------------------------------------------------


def test_one_question_per_voice_with_its_words_and_the_people_not_yet_named(bank):
    _folder, path = _meeting(bank)
    item = ms.ensure_question(bank, path.stem, "speaker:speaker-1", named=["Bob Example"], owner="Rodrigo Example")
    fm = _parsed(item).frontmatter
    assert fm["kind"] == "clarification" and fm["asks"] == ms.ASKS and fm["allow_other"] is True
    assert fm["question"].startswith("In “Planning call” (2026-11-23) you talked with Bob Example and someone else. "
                                     "Who was Speaker 1, the one who said “")
    assert [o["label"] for o in fm["options"]] == ["Dana Example", ms.DECLINE_LABEL]   # never Bob (named), never the person
    assert ms.ensure_question(bank, path.stem, "speaker:speaker-1") is None             # asked once
    assert ms.ensure_question(bank, path.stem, "speaker:speaker-2") is None             # two lines: not worth a question


def test_a_track_is_never_asked_about(bank):
    _folder, path = _meeting(bank, HEX.replace("**Speaker 1**", "**Them**"))
    assert ms.ensure_question(bank, path.stem, "speaker:them") is None


def test_sleep_asks_from_what_stage_1_left_unnamed(bank):
    _folder, path = _meeting(bank)
    record = ms.result_record([("speaker:speaker-1", False), ("speaker:speaker-2", False), ("speaker:them", True)],
                              [ms.Named("speaker:speaker-2", "Bob Example", "Bob Example, go ahead")])
    assert record == {"named": ["Bob Example"], "unnamed": ["speaker:speaker-1"]}
    asked = ms.ask_after_read(bank, [{"episode_id": path.stem, ms.RESULT_KEY: record}])
    assert len(asked) == 1 and _parsed(asked[0]).frontmatter["speaker_label"] == "Speaker 1"


# --- The answer -----------------------------------------------------------------------------------------------------


class _Settings:
    def __init__(self, bank):
        self.memory_path = bank


def _resolve(bank, item, **request):
    from api.models.schemas import InboxResolveRequest
    from api.services import inbox_service

    parsed = markdown_parser.parse(item)
    return asyncio.run(inbox_service._resolve_speaker(item, parsed, InboxResolveRequest(**request), _Settings(bank)))


def test_a_typed_name_names_the_voice_now_and_on_every_later_sync(bank, monkeypatch):
    from api.services import owner_identity

    monkeypatch.setattr(owner_identity, "owner_name", lambda *a, **k: "Rodrigo Example")
    folder, path = _meeting(bank)
    item = ms.ensure_question(bank, path.stem, "speaker:speaker-1")
    episode_id, skipped, lines = _resolve(bank, item, action="answer", answer="Dana Example")
    assert episode_id == path.stem and not skipped and not item.exists()
    assert any(ln.startswith(f"episodes/{path.stem}.md: updated") for ln in lines)
    body = _parsed(path).body
    assert body.count("speaker:dana-example:") == 6 and "speaker:speaker-1" not in body
    assert ms.names_for(bank, _parsed(path).frontmatter["source_id"]) == {"Speaker 1": "Dana Example"}
    hash_after = _parsed(path).frontmatter["content_hash"]
    # The recorder's file edited later (a line added): the name holds, nothing reverts to "Speaker 1".
    fs.sync(bank, folder, [_file("2026-11-23 1105 Planning call.md", HEX + "\n**Speaker 1** · 00:45\nOne more thing.\n")],
            [], tz_name="Europe/Madrid")
    bank_index.invalidate()
    body = _parsed(path).body
    assert "speaker:speaker-1" not in body and "speaker:dana-example: One more thing." in body
    assert _parsed(path).frontmatter["content_hash"] != hash_after


def test_an_option_names_the_voice_and_the_person_themselves_is_refused(bank, monkeypatch):
    from api.services import owner_identity

    monkeypatch.setattr(owner_identity, "owner_name", lambda *a, **k: "Rodrigo Example")
    _folder, path = _meeting(bank)
    item = ms.ensure_question(bank, path.stem, "speaker:speaker-1", owner="Rodrigo Example")
    for bad in ("Rodrigo", "me", "Speaker 2"):
        with pytest.raises(HTTPException) as err:
            _resolve(bank, item, action="answer", answer=bad)
        assert err.value.status_code == 400 and item.exists()
    _resolve(bank, item, action="resolve", option_key="name:0")
    assert "speaker:dana-example:" in _parsed(path).body


def test_someone_i_dont_know_is_remembered_and_never_asked_again(bank):
    _folder, path = _meeting(bank)
    item = ms.ensure_question(bank, path.stem, "speaker:speaker-1")
    _episode, _skipped, lines = _resolve(bank, item, action="resolve", option_key=ms.DECLINE_KEY)
    assert lines == [f"{ms.NAMES_FILE}: updated (trigger: inbox/clarification/resolved:{ms.DECLINE_KEY})"]
    assert "speaker:speaker-1:" in _parsed(path).body
    assert ms.ensure_question(bank, path.stem, "speaker:speaker-1") is None


# --- Nothing but the person settles it ------------------------------------------------------------------------------


def test_tending_leaves_it_to_the_person_and_retires_it_only_when_the_meeting_is_gone(bank):
    _folder, path = _meeting(bank)
    item = ms.ensure_question(bank, path.stem, "speaker:speaker-1")
    fm = _parsed(item).frontmatter
    assert inbox_tend.policy(bank, item, fm) == (None, "needs_person")
    path.unlink()
    decision, _why = inbox_tend.policy(bank, item, fm)
    assert decision is not None and decision.rule == "subject_gone"


# --- Through the app's own route, committed as the person's ---------------------------------------------------------


def test_the_question_is_served_and_an_answer_through_the_route_is_the_persons_commit(tmp_path, monkeypatch):
    import subprocess

    from fastapi.testclient import TestClient

    from api import config, main
    from api.services import inbox_service

    bank = tmp_path / "bank"
    for sub in ("episodes", "entities", "sources", "inbox"):
        (bank / sub).mkdir(parents=True)
    _folder, path = _meeting(bank)
    git = lambda *a: subprocess.run(["git", *a], cwd=bank, capture_output=True, text=True, check=True).stdout  # noqa: E731
    git("init", "-q"); git("config", "user.email", "t@example.com"); git("config", "user.name", "t")
    item = ms.ensure_question(bank, path.stem, "speaker:speaker-1")
    git("add", "-A"); git("commit", "-qm", "init")
    bank_index.invalidate()
    served = {i.id: i for i in inbox_service.load_inbox(bank)}
    assert item.stem in served and "Who was Speaker 1" in (served[item.stem].question or served[item.stem].title)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    monkeypatch.setenv("CICADA_API_AUTH", "off")
    config.get_settings.cache_clear()
    try:
        r = TestClient(main.app).post(f"/inbox/{item.stem}/resolve", json={"action": "answer", "answer": "Dana Example"})
    finally:
        config.get_settings.cache_clear()
    assert r.status_code == 200, r.text
    show = git("show", "--stat", "--format=%B", "HEAD~1")   # HEAD is the state snapshot after it
    assert "Cicada-Author: user" in show and ms.NAMES_FILE in show and f"episodes/{path.stem}.md" in show
    assert git("status", "--porcelain").strip() == ""
