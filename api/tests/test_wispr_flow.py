"""G134 — Wispr Flow, backend half (R-N1 … R-N3; R-LS21 … R-LS24)."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import bank_index, channel_registry, evidence, markdown_parser, source_overview, sync_service
from api.services import wispr_flow as wf
from api.services.claims import parse_claims

CANARIES = {c: f"CANARY-{c}" for c in wf.FORBIDDEN_COLUMNS}


def _meeting(mid="m-1", **row):
    base = {"id": mid, "title": "alpha-project sync", "createdAt": "2026-09-01T10:00:00Z",
            "modifiedAt": "2026-09-01T11:00:00Z", "endedAt": "2026-09-01T10:45:00Z", "isDeleted": 0,
            "finalized": 1, "isTourDemo": 0, "transcriptDeletedAt": None,
            "participantNames": json.dumps(["Ada Example", "bob-example", "carol@example.com"]),
            "speakerMap": json.dumps({"1": "bob-example", "2": "Ada Example"}),
            "notes": "<p>Decided to ship the draft.</p>", "summary": "We agreed to ship on Friday.", **CANARIES}
    base.update(row)
    return {"row": base, "utterances": [
        {"timestamp": "2026-09-01T10:01:00Z", "text": "I will send the deck",
         "speaker": {"id": 1, "name": None, "source": "system"}, "audioOffset": "CANARY-nd"},
        {"timestamp": "2026-09-01T10:02:00Z", "text": "Thanks, the code is 482913",
         "speaker": {"id": 2, "name": "Ada Example"}},
    ]}


def _payload(**overrides):
    base = {"meetings": [_meeting()],
            "notes": [{"id": "n-1", "title": "Idea", "content": "Try a folder source.", "createdAt": 1756717200000,
                       "modifiedAt": 1756717300000, "isDeleted": 0, **CANARIES}],
            "todos": [{"meetingId": "m-1", "title": "Send the deck", "status": "open", "isDeleted": 0},
                      {"meetingId": "m-1", "title": "Old task", "status": "done", "isDeleted": 0}],
            "history": None, "deleted_meeting_ids": [], "deleted_note_ids": []}
    base.update(overrides)
    return base


@pytest.fixture
def bank(tmp_path):
    memory = tmp_path / "memory"
    for sub in ("episodes", "entities", "sources"):
        (memory / sub).mkdir(parents=True)
    return memory


def _by_source(bank):
    bank_index.invalidate()
    out = {}
    for p in (bank / "episodes").glob("ep_*.md"):
        parsed = markdown_parser.parse(p)
        out[parsed.frontmatter["source_id"]] = parsed
    return out


def _settings(**kw):
    return {"enabled": True, "include_dictation": False, "owner_speaker_names": [], **kw}


def test_the_whitelists_never_name_a_forbidden_column():
    allowed = set(wf.MEETING_COLUMNS + wf.NOTE_COLUMNS + wf.TODO_COLUMNS + wf.HISTORY_COLUMNS + wf.UTTERANCE_KEYS)
    assert not allowed & set(wf.FORBIDDEN_COLUMNS)


def test_a_meeting_keeps_its_speakers_and_only_its_whitelisted_words(bank):
    wf.ingest(bank, _payload(), _settings(owner_speaker_names=["Ada Example"]))
    meeting = _by_source(bank)["wispr:meeting:m-1"]
    body, fm = meeting.body, meeting.frontmatter
    assert body.startswith("assistant: Summary (written by Wispr Flow)\nWe agreed to ship on Friday.")
    assert "speaker:bob-example: I will send the deck" in body       # R-N2: a colleague is never `user`
    assert "user: Thanks, the code is [redacted]" in body            # R-LS22 by name; R-N3 scrub
    assert "- Send the deck" in body and "Old task" not in body
    assert (fm["origin"], fm["consent"], fm["wispr_kind"]) == ("wispr-flow", "unknown", "meeting")
    assert fm["participants"] == ["Ada Example", "bob-example"]       # the email is dropped
    # The G118 `turns` sidecar (R-PB4): an entry only for a timed turn — the two
    # utterances — while the Reader still sees all five turns from the markers.
    assert [t["speaker"] for t in fm["turns"]] == ["speaker:bob-example", "user"]
    assert [t["offset"] for t in fm["turns"]] == evidence.turn_starts(body)[3:]
    assert [t.role for t in evidence.turns(body, stamps=evidence.turn_stamps(fm))] == [
        "assistant", "assistant", "assistant", "speaker", "user"]
    assert evidence.speaker_kind(body, body.index("I will send")) == "speaker"
    assert evidence.speaker_kind(body, body.index("Thanks")) == "user"
    everything = "".join(p.read_text() for p in (bank / "episodes").glob("*.md"))
    assert "CANARY" not in everything and "carol@example.com" not in everything


def test_without_a_listed_name_nobody_in_a_meeting_is_the_owner(bank):
    wf.ingest(bank, _payload(), _settings())
    body = _by_source(bank)["wispr:meeting:m-1"].body
    assert "speaker:ada-example: Thanks" in body and "\nuser:" not in body


@pytest.mark.parametrize("row", [{"isDeleted": 1}, {"isTourDemo": 1}, {"finalized": 0}])
def test_deleted_demo_and_unfinished_meetings_are_never_memory(bank, row):
    wf.ingest(bank, _payload(meetings=[_meeting(**row)]), _settings())
    assert "wispr:meeting:m-1" not in _by_source(bank)


def test_an_edited_meeting_updates_in_place_and_a_deleted_one_is_stamped(bank):
    wf.ingest(bank, _payload(), _settings())
    first = _by_source(bank)["wispr:meeting:m-1"].frontmatter["id"]
    report = wf.ingest(bank, _payload(meetings=[_meeting(summary="We moved it to Monday.",
                                                         modifiedAt="2026-09-02T09:00:00Z")]), _settings())
    assert report["updated"] == 1
    again = _by_source(bank)["wispr:meeting:m-1"]
    assert again.frontmatter["id"] == first and again.frontmatter["processed"] is False
    wf.ingest(bank, _payload(meetings=[], notes=[], deleted_meeting_ids=["m-1"]), _settings())
    assert _by_source(bank)["wispr:meeting:m-1"].frontmatter["source_deleted_at"]


def test_a_scratchpad_note_is_the_owners_words_with_its_own_date(bank):
    wf.ingest(bank, _payload(meetings=[]), _settings())
    note = _by_source(bank)["wispr:note:n-1"]
    assert note.body == "Try a folder source." and note.frontmatter["timestamp"] == "2025-09-01T09:00:00+00:00"
    assert evidence.speaker_kind(note.body, 0) == "user"


def test_dictation_is_refused_unless_opted_in_then_one_episode_per_day(bank):
    rows = [{"timestamp": "2026-09-01T09:00:00Z", "formattedText": "Hello", "editedText": "Hello there.",
             "app": "com.apple.mail", "numWords": 2, **CANARIES},
            {"timestamp": "2026-09-01T09:05:00Z", "formattedText": "My vault code is 123456",
             "app": "com.1password.1password", "numWords": 5},
            {"timestamp": "2026-09-01T09:10:00Z", "formattedText": "Second thought.", "app": "com.apple.Notes",
             "numWords": 2},
            {"timestamp": "2026-09-02T08:00:00Z", "formattedText": "Next day", "app": "com.apple.Notes", "numWords": 2}]
    assert wf.ingest(bank, _payload(meetings=[], notes=[], history=rows), _settings())["dictation_refused"] == 4
    assert not any(k.startswith("wispr:dictation:") for k in _by_source(bank))
    wf.ingest(bank, _payload(meetings=[], notes=[], history=rows[:1]), _settings(include_dictation=True))
    wf.ingest(bank, _payload(meetings=[], notes=[], history=rows[1:]), _settings(include_dictation=True))
    days = _by_source(bank)
    first = days["wispr:dictation:2026-09-01"]
    # R-LS23: the second post merged into the day the first post created (one episode, rebuilt
    # from its own marker lines and `turns` sidecar); the password-manager line was dropped.
    assert first.body == "user: Hello there.\nuser: Second thought."
    assert first.frontmatter["dictation_apps"] == ["com.apple.Notes", "com.apple.mail"]
    assert len([k for k in days if k.startswith("wispr:dictation:")]) == 2
    assert days["wispr:dictation:2026-09-02"].body == "user: Next day"
    assert "CANARY" not in "".join(p.read_text() for p in (bank / "episodes").glob("*.md"))


def test_open_todos_become_committed_to_claims_on_the_owner_page_only(bank):
    assert wf.ingest(bank, _payload(), _settings())["todos_skipped_no_owner"] == 1
    markdown_parser.write(bank / "entities" / "owner.md", {"name": "Owner", "type": "person", "owner": True},
                          "## Summary\nx")
    wf.ingest(bank, _payload(meetings=[_meeting(modifiedAt="2026-09-03T09:00:00Z", summary="Changed.")]), _settings())
    (claim,) = [c for c in parse_claims(markdown_parser.parse(bank / "entities" / "owner.md").body)
                if c.predicate == "committed-to"]
    assert (claim.object, claim.observer, claim.source_trust, claim.origin) == (
        "Send the deck", "agent", "agent_extracted", "wispr-flow")
    assert claim.evidence[0].kind == "assistant"


def test_the_channel_row_and_the_voice_card(bank):
    wf.save_settings(bank, enabled=True, include_dictation=False, owner_speaker_names=[])
    wf.ingest(bank, _payload(), _settings())
    from api.services import sync_state
    sync_state.record_sync(bank, wf.CHANNEL_ID, count=2)
    rows = channel_registry.build_channels(bank, telegram_enabled=False)
    row = next(r for r in rows if r["id"] == "wispr-flow")
    assert row["actions"] == ["sync", "manage"] and row["count_noun"] == "capture"
    bank_index.invalidate()
    card = next(r for r in source_overview.build_overview(bank, channels=rows) if r["id"] == "wispr-flow")
    assert (card["kind"], card["mark"], card["episodes"]) == ("voice", "wispr-flow", 2)


@pytest.fixture
def client(bank, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    yield TestClient(main.app)
    config.get_settings.cache_clear()


def test_the_routes(client, bank):
    assert client.get("/capture/local-source/wispr-flow/settings").json() == {
        "enabled": False, "includeDictation": False, "ownerSpeakerNames": []}
    body = {"meetings": [_meeting()], "notes": [], "todos": [], "deletedMeetingIds": [], "deletedNoteIds": []}
    assert client.post("/capture/local-source/wispr-flow", json=body).status_code == 409
    before = sync_service.components(bank)["sources"]
    saved = client.put("/capture/local-source/wispr-flow/settings",
                       json={"enabled": True, "includeDictation": False, "ownerSpeakerNames": ["Ada Example", "x@example.com"]}).json()
    assert saved["ownerSpeakerNames"] == ["Ada Example"]
    assert sync_service.components(bank)["sources"] != before  # R-LS29
    r = client.post("/capture/local-source/wispr-flow", json=body).json()
    assert r["created"] == 1 and r["meetingsSeen"] == 1
    assert any(ch["id"] == "wispr-flow" for ch in client.get("/sources/channels").json()["channels"])
    # The wire is camelCase; `ingest` reads snake_case keys — a deletion must reach the stager
    # (a bare `req.model_dump()` in the route drops it silently: CamelModel dumps by alias).
    gone = dict(body, meetings=[], deletedMeetingIds=["m-1"])
    assert client.post("/capture/local-source/wispr-flow", json=gone).json()["tombstoned"] == 1


def _owner_page(bank):
    markdown_parser.write(bank / "entities" / "owner.md", {"name": "Owner", "type": "person", "owner": True},
                          "## Summary\nx")


def _todo_claims(bank):
    return [c for c in parse_claims(markdown_parser.parse(bank / "entities" / "owner.md").body)
            if c.predicate == "committed-to"]


def test_a_sync_during_sleep_stages_the_meeting_and_defers_its_todos(bank):
    """L final review, finding 5: the owner's page is Stage 5's to rewrite, so a
    sync mid-cycle stages the episode and leaves the claims for later — then the
    next sync outside a cycle writes them from the STORED episode."""
    _owner_page(bank)
    wf.save_settings(bank, enabled=True, include_dictation=False, owner_speaker_names=[])
    out = wf.ingest(bank, _payload(), _settings(), defer_todos=True)
    assert out["created"] == 2 and out["todo_claims"] == 0 and out["todos_pending"] == 1
    assert "entities/owner.md" not in out["paths"] and "sources/wispr_flow.json" in out["paths"]
    assert _todo_claims(bank) == [] and wf.load_todos_pending(bank) == ["wispr:meeting:m-1"]
    # The person's settings survive the pending list, and a settings save keeps it.
    assert wf.load_settings(bank)["enabled"] is True
    wf.save_settings(bank, enabled=True, include_dictation=False, owner_speaker_names=["Ada Example"])
    assert wf.load_todos_pending(bank) == ["wispr:meeting:m-1"]

    later = wf.ingest(bank, _payload(meetings=[], notes=[], todos=[]), _settings())
    assert later["todo_claims"] == 1 and later["todos_pending"] == 0
    assert "entities/owner.md" in later["paths"]
    assert [c.object for c in _todo_claims(bank)] == ["Send the deck"]
    assert wf.load_todos_pending(bank) == []


def test_the_sleep_tail_replays_deferred_todos(bank):
    _owner_page(bank)
    wf.ingest(bank, _payload(), _settings(), defer_todos=True)
    report = wf.replay_pending_todos(bank)
    assert (report["replayed"], report["written"]) == (1, 1)
    assert "entities/owner.md" in report["paths"]
    assert wf.replay_pending_todos(bank) == {"replayed": 0, "written": 0, "paths": []}


def test_the_route_defers_todos_while_sleep_runs(client, bank, monkeypatch):
    from types import SimpleNamespace

    from api.services import sleep_cycle

    _owner_page(bank)
    client.put("/capture/local-source/wispr-flow/settings",
               json={"enabled": True, "includeDictation": False, "ownerSpeakerNames": []})
    body = {"meetings": [_meeting()], "notes": [], "deletedMeetingIds": [], "deletedNoteIds": [],
            "todos": [{"meetingId": "m-1", "title": "Send the deck", "status": "open", "isDeleted": 0}]}
    monkeypatch.setattr(sleep_cycle, "get_sleep_state", lambda: SimpleNamespace(status="running"))
    r = client.post("/capture/local-source/wispr-flow", json=body).json()
    assert (r["todoClaims"], r["todosPending"]) == (0, 1)
    # Adding a folder writes a project page: refused, in words, while a cycle runs.
    refused = client.post("/sources/folders", json={"label": "alpha-project", "path": "/Users/example/alpha-project"})
    assert refused.status_code == 409 and "folder:" not in refused.json()["detail"]
    monkeypatch.setattr(sleep_cycle, "get_sleep_state", lambda: SimpleNamespace(status="idle"))
    r = client.post("/capture/local-source/wispr-flow", json=dict(body, meetings=[], todos=[])).json()
    assert (r["todoClaims"], r["todosPending"]) == (1, 0)
