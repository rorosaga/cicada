"""G95 (2026-11-03) — meeting transcripts from a watched folder: Hex, subtitles, JSON, text; one episode per meeting,
its own date, consolidated by Sleep (ruling 52). Whose words (52a): the recorder's `You`/`Me` lines are the person's
own, every other speaker's are theirs, the recorder's summary is its model's."""
from __future__ import annotations

import base64
import hashlib

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import bank_index, channel_registry, entity_extractor, evidence, folder_source as fs
from api.services import markdown_parser, meeting_transcripts as mt, promotion, source_overview

# Made-up meetings only (placeholders, never a real conversation).
HEX = """# Alpha planning

- **Date:** Tuesday, November 3, 2026, 4:01 PM
- **Duration:** 12:30
- **Attendees:** Bob Example, Carol Example

<!-- hex:notes -->
## Summary

They agreed to ship the alpha-project beta next week.

_Written on this Mac by Apple Intelligence; check it against the transcript._
<!-- /hex:notes -->

## Transcript

**You** · 00:00
Hi Bob, shall we start?

**Them** · 00:04
Yes. The beta is ready.
It just needs docs.

**You** · 01:15
Great, ship it next week.
"""
HEX_NAME = "2026-11-03 1601 Alpha planning.md"
HEX_OLD = """# Meeting — 2026-11-02 0930 Meeting

**[00:00] You:** Morning.

**[00:03] Them:** Morning, all set?
"""
VTT = """WEBVTT

00:00:01.000 --> 00:00:03.000
<v Alice Example>Hello there.</v>

00:00:03.500 --> 00:00:05.000
<v Alice Example>Second cue.</v>

00:00:06.000 --> 00:00:08.000
<v Bob Example>Hi Alice.</v>
"""
SRT = """1
00:00:01,000 --> 00:00:03,000
Alice: Hello there.

2
00:00:04,000 --> 00:00:06,000
Bob: Hi.
"""
OTTER = """Speaker 1  0:00
Welcome everyone.

Dana Example  0:12
Thanks for having me.
More words.
"""
PLAIN = """Alice: we should pick a date.
Bob: Friday works.
Alice: Friday then.
"""
JSON = ('{"segments":[{"start":0.0,"text":"hello","speaker":"SPEAKER_00"},'
        '{"start":2.5,"text":"hi back","speaker":"SPEAKER_01"}]}')
NOTES = "Just some notes about the call.\n\nSecond paragraph."
FOLDER = {"id": "meetings-abc123", "kind": "meetings"}


def _draft(name, text, folder=FOLDER, tz="Europe/Madrid"):
    return mt.draft_for_file(folder, name, text, mtime_iso="2026-11-03T18:00:00Z", sha="x", tz_name=tz)


def _markers(draft):
    return [t.speaker for t in draft.turns]


# --- Parsing ---------------------------------------------------------------------------------------------------------


def test_hex_markdown_is_one_meeting_with_its_speakers_and_its_model_summary():
    d = _draft(HEX_NAME, HEX)
    assert d.title == "Alpha planning"
    assert _markers(d) == ["assistant", "user", "speaker:them", "user"]
    assert d.turns[0].text.startswith("Summary (written by Hex)\n> They agreed")
    assert d.turns[2].text == "Yes. The beta is ready. It just needs docs."
    assert d.extra["meeting"] == {"recorder": "hex", "format": "hex", "speakers": ["You", "Them"],
                                  "own_labels": ["You"], "duration_s": 750,
                                  "summary_writer": "Written on this Mac by Apple Intelligence; check it against the "
                                                    "transcript.",
                                  "attendees": ["Bob Example", "Carol Example"]}
    assert d.extra["meeting"]["attendees"] == ["Bob Example", "Carol Example"] and "participants" not in d.extra
    assert d.extra["consent"] == "unknown" and d.extra["folder_kind"] == "meetings"
    assert d.source_id == "meetings:meetings-abc123:" + HEX_NAME
    assert d.queue_for_sleep is True   # owner 2026-11-03: Sleep consolidates meetings


def test_a_day_with_no_time_is_the_files_own_time_that_day_else_its_midday():
    # Saved 18:00 UTC on 2026-11-03 = 19:00 in Madrid, the named day: the file's own time.
    same = _draft("2026-11-03 call.srt", SRT)
    assert same.timestamp == "2026-11-03T18:00:00+00:00" and same.original_date == "2026-11-03"
    assert same.turns[0].ts == "00:00:01"   # no stated start: offsets stay offsets
    # Saved on another day: that day's midday, never its midnight (a reader west of the zone would see the day before).
    other = _draft("2026-11-01 call.srt", SRT)
    assert other.timestamp == "2026-11-01T11:00:00+00:00" and other.original_date == "2026-11-01"


def test_hex_file_name_is_local_wall_time_in_the_posted_zone():
    d = _draft(HEX_NAME, HEX)
    # 16:01 in Madrid on 2026-11-03 (CET, UTC+1) is 15:01 UTC; the id day is the meeting's own local day.
    assert d.timestamp == "2026-11-03T15:01:00+00:00" and d.original_date == "2026-11-03" and d.redate is True
    assert d.turns[3].ts == "2026-11-03T15:02:15+00:00"   # start + 01:15
    late = _draft("2026-11-03 2345 Late call.md", HEX.replace("4:01 PM", "11:45 PM"), tz="America/Los_Angeles")
    assert late.timestamp == "2026-11-04T07:45:00+00:00" and late.original_date == "2026-11-03"


def test_older_hex_lines_and_the_heading_tail():
    d = _draft("2026-11-02 0930 Meeting.md", HEX_OLD)
    assert d.title == "Meeting" and _markers(d) == ["user", "speaker:them"]
    assert d.extra["meeting"]["recorder"] is None   # no notes block, no Transcript header: a plain transcript


def test_subtitles_merge_a_speakers_cues_and_keep_the_first_time():
    vtt = _draft("call.vtt", VTT)
    assert [(t.speaker, t.text) for t in vtt.turns] == [
        ("speaker:alice-example", "Hello there. Second cue."), ("speaker:bob-example", "Hi Alice.")]
    assert vtt.turns[0].ts == "00:00:01"   # no start known: the offset, informational
    srt = _draft("call.srt", SRT)
    assert [(t.speaker, t.text) for t in srt.turns] == [("speaker:alice", "Hello there."), ("speaker:bob", "Hi.")]


@pytest.mark.parametrize("name, text, expected", [
    ("otter.txt", OTTER, [("speaker:speaker-1", "Welcome everyone."),
                          ("speaker:dana-example", "Thanks for having me. More words.")]),
    ("plain.txt", PLAIN, [("speaker:alice", "we should pick a date."), ("speaker:bob", "Friday works."),
                          ("speaker:alice", "Friday then.")]),
    ("whisper.json", JSON, [("speaker:speaker_00", "hello"), ("speaker:speaker_01", "hi back")]),
    ("notes.md", NOTES, [("speaker:unknown", "Just some notes about the call."),
                         ("speaker:unknown", "Second paragraph.")]),
])
def test_other_recorders_formats(name, text, expected):
    assert [(t.speaker, t.text) for t in _draft(name, text).turns] == expected


def test_a_file_with_no_transcript_is_none():
    assert _draft("manifest.json", '{"schema_version": 1, "status": "complete"}') is None
    assert _draft("empty.md", "   \n") is None


def _body(d):
    return "\n".join(f"{t.speaker}: {t.text}" for t in d.turns)


def test_only_the_recorders_own_label_is_the_persons_words():
    """Ruling 52a: `You` (Hex's microphone) and `Me` are the person's; `Them`, a named speaker, an unlabelled line and
    the recorder's summary never are — nor is a name, even one that might be the person's."""
    me = _draft("me.txt", "Me: I will send it.\nThem: thanks\nMe: sure\nDana Example: noted")
    assert _markers(me) == ["user", "speaker:them", "user", "speaker:dana-example"]
    assert me.extra["meeting"]["own_labels"] == ["Me"]
    for name, text in [("call.vtt", VTT), ("call.srt", SRT), ("otter.txt", OTTER), ("plain.txt", PLAIN),
                       ("w.json", JSON), ("notes.md", NOTES)]:
        d = _draft(name, text)
        assert "user" not in _markers(d) and "own_labels" not in d.extra["meeting"], name
    hex_body = _body(_draft(HEX_NAME, HEX))
    you = hex_body.index("Hi Bob")
    them = hex_body.index("The beta is ready")
    summary = hex_body.index("They agreed")
    assert evidence.speaker_kind(hex_body, you) == "user"
    assert evidence.speaker_kind(hex_body, them) == "speaker"
    assert evidence.speaker_kind(hex_body, summary) == "assistant"


def test_the_persons_lines_open_exchanges_and_the_summary_never_does():
    pairs = promotion.exchanges(_body(_draft(HEX_NAME, HEX)))
    person_words = [person for person, _ in pairs if person]
    assert any("Hi Bob" in p for p in person_words) and any("ship it next week" in p for p in person_words)
    assert not any("They agreed" in p for p in person_words)   # the recorder's model text is never an exchange


def test_an_email_never_becomes_a_speaker_or_a_participant():
    d = _draft("a.txt", "bob@example.com: hi\nAlice: hello\nAlice: again\nAlice: and again\n"
                        "Attendees: Alice, carol@example.com\n")
    assert all("example-com" not in m for m in _markers(d))


# --- The folder ------------------------------------------------------------------------------------------------------


def _file(rel, text, mtime=1_762_200_000.0):
    raw = text.encode("utf-8")
    return fs.IncomingFile(relpath=rel, mtime=mtime, sha256=hashlib.sha256(raw).hexdigest(),
                           content_b64=base64.b64encode(raw).decode())


@pytest.fixture
def bank(tmp_path):
    memory = tmp_path / "memory"
    for sub in ("episodes", "entities", "sources"):
        (memory / sub).mkdir(parents=True)
    return memory


def _episodes(bank):
    bank_index.invalidate()
    return {markdown_parser.parse(p).frontmatter.get("source_id"): markdown_parser.parse(p)
            for p in (bank / "episodes").glob("ep_*.md")}


def _paths(bank):
    return {markdown_parser.parse(p).frontmatter.get("source_id"): p for p in (bank / "episodes").glob("ep_*.md")}


def test_a_hex_folder_registers_with_its_bundle_excluded_and_no_project(bank):
    folder = fs.register(bank, label="Hex Meetings", path="/Users/example/Documents/Hex Meetings", device="mac-1",
                         kind="meetings", recorder="hex")
    assert folder["kind"] == "meetings" and folder["recorder"] == "hex"
    assert "audio/**" in folder["exclude"] and "**/*.vtt" in folder["include"]
    assert folder["authorship"] == [] and folder["project_id"] is None
    assert fs.channel_for(folder) == f"meetings:{folder['id']}"
    assert fs.folder_id_of(fs.channel_for(folder)) == folder["id"]
    # A re-pick never flips the kind.
    again = fs.register(bank, label="Hex Meetings", path="/Users/example/Documents/Hex Meetings", device="mac-1")
    assert again["id"] == folder["id"] and again["kind"] == "meetings"
    notes = fs.register(bank, label="alpha-project", path="/Users/example/alpha-project", device="mac-1")
    assert notes["kind"] == "notes" and fs.channel_for(notes) == f"folder:{notes['id']}"


def test_a_meeting_is_staged_queued_edited_in_place_renamed_and_tombstoned(bank):
    folder = fs.register(bank, label="Hex Meetings", path="/m", device="mac-1", kind="meetings", recorder="hex")
    out = fs.sync(bank, folder, [_file(HEX_NAME, HEX), _file("manifest.json", '{"a": 1}')], [],
                  tz_name="Europe/Madrid")
    assert out["created"] == 1 and out["files_new"] == 1
    assert out["errors"] == [{"relpath": "manifest.json", "reason": "not a meeting transcript"}]
    sid = mt.source_id(folder["id"], HEX_NAME)
    ep = _episodes(bank)[sid]
    fm = ep.frontmatter
    assert fm["processed"] is False and fm["timestamp"] == "2026-11-03T15:01:00+00:00"
    assert _paths(bank)[sid].name.startswith("ep_2026-11-03_")
    assert "evidence_kind" not in fm and fm["meeting"]["own_labels"] == ["You"]
    assert ep.body.startswith("assistant: Summary (written by Hex)")
    assert "user: Hi Bob, shall we start?" in ep.body and "speaker:them: Yes. The beta is ready." in ep.body
    first_id = _paths(bank)[sid].stem
    # The same bytes: nothing moves.
    assert fs.sync(bank, folder, [_file(HEX_NAME, HEX)], [], tz_name="Europe/Madrid")["files_unchanged"] == 1
    # An edited transcript (Hex rewrites its summary block in place): the same episode, re-queued.
    edited = HEX.replace("next week.\n\n_Written", "on Friday.\n\n_Written")
    assert fs.sync(bank, folder, [_file(HEX_NAME, edited)], [], tz_name="Europe/Madrid")["updated"] == 1
    ep = _episodes(bank)[sid]
    assert _paths(bank)[sid].stem == first_id and "on Friday." in ep.body and ep.frontmatter["processed"] is False
    # The edit says it is one (owner 2026-11-03: a re-ingested item is an update): never consolidated yet, so no
    # consolidated body to supersede — only the count and the body it replaced.
    revised = ep.frontmatter["revised"]
    assert revised["count"] == 1 and revised["previous_hash"] == fm["content_hash"]
    assert "consolidated_hash" not in revised
    # Sleep reads it, then the transcript changes again: the record names the body Sleep consolidated.
    path = _paths(bank)[sid]
    read = markdown_parser.parse(path)
    markdown_parser.write(path, {**read.frontmatter, "processed": True, "processed_by": "sleep"}, read.body)
    consolidated = read.frontmatter["content_hash"]
    again = edited.replace("It just needs docs.", "It just needs docs and a demo.")
    assert fs.sync(bank, folder, [_file(HEX_NAME, again)], [], tz_name="Europe/Madrid")["updated"] == 1
    revised = _episodes(bank)[sid].frontmatter["revised"]
    assert revised["count"] == 2 and revised["consolidated_hash"] == consolidated == revised["previous_hash"]
    assert _episodes(bank)[sid].frontmatter["processed"] is False and _paths(bank)[sid].stem == first_id
    # A third edit before Sleep reads it again keeps pointing at the body Sleep consolidated.
    third = again.replace("and a demo.", "and a demo video.")
    fs.sync(bank, folder, [_file(HEX_NAME, third)], [], tz_name="Europe/Madrid")
    revised = _episodes(bank)[sid].frontmatter["revised"]
    assert revised["count"] == 3 and revised["consolidated_hash"] == consolidated != revised["previous_hash"]
    # Deleted in the folder: tombstoned, never unlinked.
    assert fs.sync(bank, folder, [], [HEX_NAME])["tombstoned"] == 1
    assert _episodes(bank)[sid].frontmatter.get("source_deleted_at")


def test_a_meeting_folder_never_takes_authorship_rules(bank):
    folder = fs.register(bank, label="Calls", path="/c", device="mac-1", kind="meetings")
    fs.sync(bank, folder, [_file("call.srt", SRT)], [])
    fs.update(bank, folder["id"], authorship=[{"glob": "**", "authorship": "user"}])
    assert fs.get_folder(bank, folder["id"])["authorship"] == []
    assert fs.reapply_authorship(bank, folder["id"])["paths"] == []
    ep = next(iter(_episodes(bank).values()))
    assert "evidence_kind" not in ep.frontmatter


def test_the_channel_row_and_the_overview_card_are_the_meeting_folders(bank):
    folder = fs.register(bank, label="Calls", path="/c", device="mac-1", kind="meetings")
    fs.sync(bank, folder, [_file("call.srt", SRT)], [])
    from api.services import sync_state

    sync_state.record_sync(bank, fs.channel_for(folder), count=1)
    channels = channel_registry.build_channels(bank, telegram_enabled=False)
    row = next(c for c in channels if c["id"] == f"meetings:{folder['id']}")
    assert row["label"] == "Calls" and row["count_noun"] == "meeting"
    assert not any(c["id"] == f"folder:{folder['id']}" for c in channels)
    bank_index.invalidate()
    overview = source_overview.build_overview(bank, channels=channels)
    card = next(o for o in overview if o["id"] == f"meetings:{folder['id']}")
    assert card["label"] == "Calls" and card["episodes"] == 1


def test_sleep_is_told_whose_lines_they_are():
    note = entity_extractor.meeting_note({"meeting": {"recorder": "hex", "own_labels": ["You"]}})
    assert note.startswith(entity_extractor.MEETING_NOTE_PREFIX) and "written by Hex" in note
    assert 'Lines starting "user:" are the person\'s own words (the recorder labelled them "You")' in note
    assert "someone else in the meeting" in note and "never the person's words" in note
    plain = entity_extractor.meeting_note({"meeting": {"recorder": None}})
    assert "None of its lines is marked as the person's own words" in plain and "meeting folder" in plain
    assert entity_extractor.meeting_note({"source": "claude-code"}) is None


# --- The routes ------------------------------------------------------------------------------------------------------


@pytest.fixture
def client(bank, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    yield TestClient(main.app), bank
    config.get_settings.cache_clear()


def test_the_routes(client):
    c, bank = client
    r = c.post("/sources/folders", json={"label": "Hex Meetings", "path": "/Users/example/Documents/Hex Meetings",
                                         "kind": "meetings", "recorder": "hex"})
    assert r.status_code == 200, r.text
    rec = r.json()
    fid = rec["id"]
    assert rec["kind"] == "meetings" and rec["recorder"] == "hex" and rec["channelId"] == f"meetings:{fid}"
    assert not list((bank / "entities").glob("*.md")), "a meeting folder anchors no project page"
    f = _file(HEX_NAME, HEX)
    body = {"files": [{"relpath": f.relpath, "mtime": f.mtime, "sha256": f.sha256, "contentB64": f.content_b64}],
            "deleted": [], "tzName": "Europe/Madrid"}
    pre = c.post(f"/sources/folders/{fid}/sync", params={"preview": "true"}, json=body).json()
    assert pre["preview"] is True and pre["filesNew"] == 1 and pre["papersFound"] == 0
    done = c.post(f"/sources/folders/{fid}/sync", params={"resolve": "true"}, json=body).json()
    assert done["created"] == 1
    (ep,) = _episodes(bank).values()
    assert ep.frontmatter["timestamp"] == "2026-11-03T15:01:00+00:00"
    assert any(ch["id"] == f"meetings:{fid}" for ch in c.get("/sources/channels").json()["channels"])
    assert c.get("/sources/folders").json()["folders"][0]["kind"] == "meetings"
    assert c.post("/sources/folders", json={"label": "x", "path": "/x", "kind": "podcasts"}).status_code == 422


def test_a_demo_bank_takes_no_meeting_folder_and_no_meeting(tmp_path, monkeypatch):
    from api.services import bank_registry, demo_guard

    root = tmp_path / "root"
    root.mkdir()
    slug = bank_registry.create_bank(root, "demo")
    demo = bank_registry.bank_dir(root, slug)
    demo_guard.write_manifest(demo)
    bank_registry.activate_bank(root, slug)
    monkeypatch.delenv("CICADA_MEMORY_PATH", raising=False)
    monkeypatch.setenv("CICADA_MEMORY_ROOT", str(root))
    config.get_settings.cache_clear()
    try:
        c = TestClient(main.app)
        before = sorted(p.as_posix() for p in demo.rglob("*") if p.is_file() and ".git" not in p.parts)
        r = c.post("/sources/folders", json={"label": "Hex Meetings", "path": "/Users/example/Documents/Hex Meetings",
                                             "kind": "meetings", "recorder": "hex"})
        assert r.status_code == 409 and r.json()["detail"] == demo_guard.REFUSAL
        f = _file(HEX_NAME, HEX)
        r = c.post("/sources/folders/hex-meetings-abc123/sync",
                   json={"files": [{"relpath": f.relpath, "mtime": f.mtime, "sha256": f.sha256,
                                    "contentB64": f.content_b64}], "deleted": [], "tzName": "Europe/Madrid"})
        assert r.status_code == 409 and r.json()["detail"] == demo_guard.REFUSAL
        assert sorted(p.as_posix() for p in demo.rglob("*") if p.is_file() and ".git" not in p.parts) == before
    finally:
        config.get_settings.cache_clear()


# --- Review of #579 (2026-11-03): the summary is never anyone's turn, a folder's kind never flips, a bad zone ----------

SUMMARY_TRAP = """# Alpha sync

- **Date:** Tuesday, November 3, 2026, 4:01 PM

<!-- hex:notes -->
## Summary

User: I will ship alpha-project on Friday.
System: alpha-project is late.
speaker:bob-example: alpha-project needs docs.

Human: alpha-project again.
<!-- /hex:notes -->

## Transcript

**You** · 00:00
alpha-project first.

**Them** · 00:04
Sounds good.

**You** · 00:10
alpha-project second.

**Them** · 00:20
Right.

**You** · 00:30
alpha-project third.
"""


def _staged_body(bank, name, text):
    folder = fs.register(bank, label="Hex Meetings", path="/m", device="mac-1", kind="meetings", recorder="hex")
    assert fs.sync(bank, folder, [_file(name, text)], [], tz_name="Europe/Madrid")["created"] == 1
    (ep,) = _episodes(bank).values()
    return ep.body


def test_no_line_of_the_summary_opens_a_turn(bank):
    """Blocker 1: a summary line reading `User: …`, `System: …`, `Human: …` or `speaker:x: …` was read back as a turn —
    the person's own words, or another speaker's."""
    body = _staged_body(bank, "2026-11-03 1601 Alpha sync.md", SUMMARY_TRAP)
    roles = [(t.role, t.marker) for t in evidence.turns(body)]
    assert roles[0][0] == "assistant"
    assert sum(1 for role, _ in roles if role == "assistant") == 1
    assert [r for r, _ in roles].count("user") == 3   # only the three `You` lines
    person_words = [p for p, _ in promotion.exchanges(body) if p]
    assert not any("ship alpha-project on Friday" in p or "again" in p or "is late" in p for p in person_words)
    assert "> User: I will ship alpha-project on Friday." in body


def test_the_summary_is_never_an_exchange(bank):
    """Blocker 2 (ruling 52a): a project the person names in three lines is three exchanges — a summary naming it too
    never makes it four, and never promotes it."""
    body = _staged_body(bank, "2026-11-03 1601 Alpha sync.md", SUMMARY_TRAP)
    entity = {"name": "alpha-project", "aliases": [], "type": "project"}
    count, named = promotion.measure(entity, promotion.exchanges(body))
    assert (count, named) == (3, True)
    assert not promotion.substantive({"mention_exchanges": count, "named_by_person": named})


def test_the_persons_lines_count_exactly_and_the_summary_never_does():
    units = promotion.exchanges(_body(_draft(HEX_NAME, HEX)))
    assert all(person for person, _ in units)          # every unit opens at a line of someone's, never the summary
    assert len(units) == 3                             # You, Them, You


def _pre_g95(bank, folder_id):
    """A folder registered before G95: no `kind` key in the registry."""
    import json

    path = bank / "sources" / fs.FOLDERS_FILENAME
    rows = json.loads(path.read_text())
    for row in rows if isinstance(rows, list) else rows.get("folders", []):
        if row.get("id") == folder_id:
            row.pop("kind", None)
            row.pop("recorder", None)
    path.write_text(json.dumps(rows))


def test_a_watched_notes_folder_never_becomes_a_meeting_folder(bank):
    """Blocker 3: an already-watched notes folder (one added before G95 has no `kind`) picked again as a meeting folder
    kept its id but turned `meetings` — its notes tombstoned, replaced by `speaker:unknown` meetings."""
    notes = fs.register(bank, label="alpha-project", path="/n", device="mac-1")
    _pre_g95(bank, notes["id"])
    fs.sync(bank, fs.get_folder(bank, notes["id"]), [_file("plan.md", "A plan for alpha-project.\n")], [])
    again = fs.register(bank, label="Meetings", path="/n", device="mac-1", kind="meetings", recorder="hex")
    assert again["id"] == notes["id"] and again["kind"] == "notes" and "recorder" not in again
    out = fs.sync(bank, again, [_file("plan.md", "A plan for alpha-project.\n")], [])
    assert out["tombstoned"] == 0 and out["created"] == 0
    (ep,) = _episodes(bank).values()
    assert not ep.frontmatter.get("source_deleted_at") and ep.frontmatter.get("folder_kind") != "meetings"


def test_the_route_refuses_a_kind_flip_and_writes_nothing(client):
    c, bank = client
    r = c.post("/sources/folders", json={"label": "alpha-project", "path": "/Users/example/alpha-project"})
    assert r.status_code == 200, r.text
    fid = r.json()["id"]
    _pre_g95(bank, fid)
    before = (bank / "sources" / fs.FOLDERS_FILENAME).read_text()
    r = c.post("/sources/folders", json={"label": "Meetings", "path": "/Users/example/alpha-project",
                                         "kind": "meetings", "recorder": "hex"})
    assert r.status_code == 409 and r.json()["detail"] == fs.KIND_REFUSAL["notes"]
    assert (bank / "sources" / fs.FOLDERS_FILENAME).read_text() == before
    m = c.post("/sources/folders", json={"label": "Calls", "path": "/Users/example/calls", "kind": "meetings"})
    r = c.post("/sources/folders", json={"label": "Calls", "path": "/Users/example/calls"})
    assert r.status_code == 409 and r.json()["detail"] == fs.KIND_REFUSAL["meetings"]
    assert c.get("/sources/folders").json()["folders"][-1]["kind"] == "meetings" == m.json()["kind"]


def test_a_zone_name_that_is_a_directory_is_no_failed_sync(client):
    c, bank = client
    from api.services import when

    assert when.zone("America") is not None   # IsADirectoryError before
    fid = c.post("/sources/folders", json={"label": "Calls", "path": "/Users/example/calls2", "kind": "meetings"}
                 ).json()["id"]
    f = _file(HEX_NAME, HEX)
    r = c.post(f"/sources/folders/{fid}/sync",
               json={"files": [{"relpath": f.relpath, "mtime": f.mtime, "sha256": f.sha256, "contentB64": f.content_b64}],
                     "deleted": [], "tzName": "America"})
    assert r.status_code == 200 and r.json()["created"] == 1, r.text


# --- G104 slice 3 · T1: one meeting, one episode ----------------------------------------------------------------------
# A recorder's corrected export lands as a SECOND file with the same stamp ("YYYY-MM-DD HHMM"); the newest copy is the
# meeting, every older copy is only remembered (made-up names and words throughout).

NAME_A = "2026-11-03 1601 Alpha planning.md"
NAME_B = "2026-11-03 1601 Alpha planning (corrected).md"
TEXT_A = HEX
TEXT_B = HEX.replace("They agreed to ship the alpha-project beta next week.", "They agreed to ship the alpha-project beta in May.")
T0 = 1_762_200_000.0


def _meeting_folder(bank):
    return fs.register(bank, label="Hex Meetings", path="/m", device="mac-1", kind="meetings", recorder="hex")


def _sync(bank, folder, files=(), deleted=()):
    return fs.sync(bank, folder, list(files), list(deleted), tz_name="Europe/Madrid")


def _live(bank):
    """Every meeting episode in the bank: ``[parsed episode]``, by id."""
    bank_index.invalidate()
    return sorted((markdown_parser.parse(p) for p in (bank / "episodes").glob("ep_*.md")),
                  key=lambda e: e.frontmatter["id"])


def _held(ep):
    return ep.frontmatter["relpath"]


def _replaced(ep):
    return [(r["relpath"], r["content_sha"]) for r in ep.frontmatter.get("replaced_files") or []]


def _sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def test_a_newer_copy_of_the_same_stamp_revises_the_episode_in_place(bank):
    folder = _meeting_folder(bank)
    _sync(bank, folder, [_file(NAME_A, TEXT_A, mtime=T0)])
    (first,) = _live(bank)
    out = _sync(bank, folder, [_file(NAME_B, TEXT_B, mtime=T0 + 60)])
    assert (out["created"], out["updated"], out["tombstoned"]) == (0, 1, 0)
    (ep,) = _live(bank)
    fm = ep.frontmatter
    assert fm["id"] == first.frontmatter["id"] and fm["processed"] is False
    assert "beta in May." in ep.body and "beta next week." not in ep.body
    assert fm["source_id"] == mt.source_id(folder["id"], NAME_B) and _held(ep) == NAME_B
    assert fm["content_sha"] == _sha(TEXT_B) and fm["revised"]["count"] == 1
    assert fm["previous_source_ids"] == [mt.source_id(folder["id"], NAME_A)]
    assert _replaced(ep) == [(NAME_A, _sha(TEXT_A))] and "source_deleted_at" not in fm
    assert fs.live_file_count(bank, folder["id"]) == 1


def test_an_older_copy_changes_no_word_and_is_only_remembered(bank):
    folder = _meeting_folder(bank)
    _sync(bank, folder, [_file(NAME_B, TEXT_B, mtime=T0 + 60)])
    before = _live(bank)[0]
    out = _sync(bank, folder, [_file(NAME_A, TEXT_A, mtime=T0)])
    assert (out["created"], out["updated"], out["files_unchanged"]) == (0, 0, 1)
    (ep,) = _live(bank)
    assert ep.body == before.body and "revised" not in ep.frontmatter and _held(ep) == NAME_B
    assert _replaced(ep) == [(NAME_A, _sha(TEXT_A))]
    # Posted again: nothing moves, nothing is drafted.
    again = _sync(bank, folder, [_file(NAME_A, TEXT_A, mtime=T0)])
    assert again["files_unchanged"] == 1 and again["updated"] == again["created"] == 0


@pytest.mark.parametrize("order", ["together", "old-first", "new-first", "reversed-together"])
def test_a_rescan_after_manifest_loss_leaves_one_episode_with_the_newer_copy(bank, order):
    folder = _meeting_folder(bank)
    a, b = _file(NAME_A, TEXT_A, mtime=T0), _file(NAME_B, TEXT_B, mtime=T0 + 60)
    batches = {"together": [[a, b]], "reversed-together": [[b, a]], "old-first": [[a], [b]], "new-first": [[b], [a]]}
    for batch in batches[order]:
        _sync(bank, folder, batch)
    (ep,) = _live(bank)
    assert _held(ep) == NAME_B and "in May." in ep.body and _replaced(ep) == [(NAME_A, _sha(TEXT_A))]
    # Whichever order it arrived in, the same files again change nothing.
    for batch in batches[order]:
        out = _sync(bank, folder, batch)
        assert out["created"] == out["updated"] == 0
    assert len(_live(bank)) == 1
    if order in ("together", "reversed-together", "new-first"):
        assert "revised" not in _live(bank)[0].frontmatter, "the correction was never read as a second revision"


def test_the_old_copy_posted_later_never_turns_the_correction_back_unless_its_bytes_changed(bank):
    folder = _meeting_folder(bank)
    _sync(bank, folder, [_file(NAME_A, TEXT_A, mtime=T0), _file(NAME_B, TEXT_B, mtime=T0 + 60)])
    # A sync tool touched the old file: same bytes, a newer time. It does not win.
    out = _sync(bank, folder, [_file(NAME_A, TEXT_A, mtime=T0 + 600)])
    assert out["updated"] == 0
    (ep,) = _live(bank)
    assert _held(ep) == NAME_B and "in May." in ep.body
    # The person edited the old file: its bytes changed and it is the newest, so it wins by the same rule.
    edited = TEXT_A.replace("beta is ready.", "beta is ready today.")
    assert _sync(bank, folder, [_file(NAME_A, edited, mtime=T0 + 700)])["updated"] == 1
    (ep,) = _live(bank)
    assert _held(ep) == NAME_A and "ready today." in ep.body
    assert _replaced(ep) == [(NAME_B, _sha(TEXT_B))] and ep.frontmatter["revised"]["count"] == 1


@pytest.mark.parametrize("first, second", [(NAME_A, NAME_B), (NAME_B, NAME_A)])
def test_equal_times_are_decided_by_the_greater_path_in_either_order(bank, first, second):
    folder = _meeting_folder(bank)
    text = {NAME_A: TEXT_A, NAME_B: TEXT_B}
    for name in (first, second):
        _sync(bank, folder, [_file(name, text[name], mtime=T0)])
    (ep,) = _live(bank)
    winner = max(NAME_A, NAME_B)
    assert _held(ep) == winner and _replaced(ep) == [(loser, _sha(text[loser]))
                                                     for loser in (NAME_A, NAME_B) if loser != winner]


def test_a_stamp_with_no_time_never_joins_and_a_notes_folder_is_unchanged(bank):
    folder = _meeting_folder(bank)
    plain_a, plain_b = "Alice: we should pick a date.\nBob: Friday works.\nAlice: Friday then.\n", PLAIN.replace("Friday then", "Monday then")
    _sync(bank, folder, [_file("2026-11-03 notes.md", plain_a), _file("2026-11-03 other.md", plain_b, mtime=T0 + 60)])
    assert len(_live(bank)) == 2
    notes = fs.register(bank, label="alpha-project", path="/n", device="mac-1")
    out = fs.sync(bank, notes, [_file("2026-11-03 1601 a.md", "first words"),
                                _file("2026-11-03 1601 b.md", "second words", mtime=T0 + 60)], [])
    assert out["created"] == 2 and all("replaced_files" not in e.frontmatter for e in _live(bank))


def test_a_file_that_is_no_transcript_never_replaces_a_meeting(bank):
    folder = _meeting_folder(bank)
    _sync(bank, folder, [_file(NAME_A, TEXT_A, mtime=T0)])
    out = _sync(bank, folder, [_file("2026-11-03 1601 manifest.json", '{"a": 1}', mtime=T0 + 60)])
    assert out["errors"] == [{"relpath": "2026-11-03 1601 manifest.json", "reason": "not a meeting transcript"}]
    (ep,) = _live(bank)
    assert _held(ep) == NAME_A and "replaced_files" not in ep.frontmatter


def test_deleting_the_held_copy_keeps_the_words_and_asks_for_the_next_newest_once(bank):
    folder = _meeting_folder(bank)
    _sync(bank, folder, [_file(NAME_A, TEXT_A, mtime=T0), _file(NAME_B, TEXT_B, mtime=T0 + 60)])
    out = _sync(bank, folder, [], [NAME_B])
    assert out["tombstoned"] == 0 and out["resend"] == [NAME_A] and out["files_deleted"] == 1
    (ep,) = _live(bank)
    assert "in May." in ep.body and "source_deleted_at" not in ep.frontmatter and ep.frontmatter["held_gone_at"]
    # Until it is posted every real sync keeps asking, so a lost answer is still answered later.
    assert _sync(bank, folder, [])["resend"] == [NAME_A]
    # The post of that path wins whatever its mtime and clears the marker: a revision back to its words.
    out = _sync(bank, folder, [_file(NAME_A, TEXT_A, mtime=T0)])
    assert out["resend"] == [] and out["updated"] == 1 and out["tombstoned"] == 0
    (ep,) = _live(bank)
    assert _held(ep) == NAME_A and "beta next week." in ep.body and "held_gone_at" not in ep.frontmatter
    assert ep.frontmatter["revised"]["count"] == 1 and "replaced_files" not in ep.frontmatter


def test_resend_names_one_path_per_meeting_the_newest_remaining(bank):
    folder = _meeting_folder(bank)
    name_c = "2026-11-03 1601 Alpha planning (draft).md"
    text_c = TEXT_A.replace("next week.", "in June.")
    _sync(bank, folder, [_file(NAME_A, TEXT_A, mtime=T0), _file(name_c, text_c, mtime=T0 + 30),
                         _file(NAME_B, TEXT_B, mtime=T0 + 60)])
    assert len(_live(bank)) == 1 and len(_replaced(_live(bank)[0])) == 2
    assert _sync(bank, folder, [], [NAME_B])["resend"] == [name_c]


def test_deleting_every_copy_tombstones_as_before_and_a_replaced_copy_alone_only_drops(bank):
    folder = _meeting_folder(bank)
    _sync(bank, folder, [_file(NAME_A, TEXT_A, mtime=T0), _file(NAME_B, TEXT_B, mtime=T0 + 60)])
    # A copy it replaced is deleted: dropped from the record, nothing else moves.
    before = _live(bank)[0]
    out = _sync(bank, folder, [], [NAME_A])
    assert (out["tombstoned"], out["updated"], out["resend"]) == (0, 0, [])
    (ep,) = _live(bank)
    assert "replaced_files" not in ep.frontmatter and ep.body == before.body and _held(ep) == NAME_B
    assert "held_gone_at" not in ep.frontmatter and "source_deleted_at" not in ep.frontmatter
    # Every copy gone, one pass at a time...
    _sync(bank, folder, [_file(NAME_A, TEXT_A, mtime=T0)], [])
    _sync(bank, folder, [], [NAME_B])
    assert _live(bank)[0].frontmatter["held_gone_at"]
    out = _sync(bank, folder, [], [NAME_A])
    assert out["tombstoned"] == 1 and out["resend"] == []
    assert _live(bank)[0].frontmatter["source_deleted_at"] and "in May." in _live(bank)[0].body
    # ... or in one.
    other = _meeting_folder(bank)
    two = "2026-11-04 0900 Beta sync.md"
    _sync(bank, other, [_file(two, TEXT_A.replace("2026-11-03", "2026-11-04"), mtime=T0)])
    assert _sync(bank, other, [], [two])["tombstoned"] == 1


def test_both_copies_deleted_in_one_pass_tombstone(bank):
    folder = _meeting_folder(bank)
    _sync(bank, folder, [_file(NAME_A, TEXT_A, mtime=T0), _file(NAME_B, TEXT_B, mtime=T0 + 60)])
    out = _sync(bank, folder, [], [NAME_A, NAME_B])
    assert out["tombstoned"] == 1 and out["resend"] == []


def test_the_rename_path_stays_first_and_a_replacement_takes_a_deleted_copys_episode(bank):
    folder = _meeting_folder(bank)
    _sync(bank, folder, [_file(NAME_A, TEXT_A, mtime=T0)])
    (first,) = _live(bank)
    # Deleted and posted again under a new name with the same bytes: a rename, no replaced copy.
    out = _sync(bank, folder, [_file(NAME_B, TEXT_A, mtime=T0 + 60)], [NAME_A])
    assert (out["renamed"], out["created"], out["tombstoned"]) == (1, 0, 0)
    (ep,) = _live(bank)
    assert ep.frontmatter["id"] == first.frontmatter["id"] and _held(ep) == NAME_B
    assert "replaced_files" not in ep.frontmatter and "revised" not in ep.frontmatter
    # A deleted and C (the same stamp, other bytes) posted in one pass: C takes A's episode, A is not tombstoned
    # and is not recorded as a copy to ask for (it is gone).
    name_c = "2026-11-03 1601 Alpha planning (final).md"
    out = _sync(bank, folder, [_file(name_c, TEXT_B, mtime=T0 + 120)], [NAME_B])
    assert (out["created"], out["updated"], out["tombstoned"], out["resend"]) == (0, 1, 0, [])
    (ep,) = _live(bank)
    assert ep.frontmatter["id"] == first.frontmatter["id"] and _held(ep) == name_c
    assert "source_deleted_at" not in ep.frontmatter and "replaced_files" not in ep.frontmatter
    assert mt.source_id(folder["id"], NAME_B) in ep.frontmatter["previous_source_ids"]


def test_two_episodes_made_before_the_rule_keep_their_own_files(bank):
    folder = _meeting_folder(bank)
    other = "2026-11-03 1602 Alpha planning.md"
    _sync(bank, folder, [_file(NAME_A, TEXT_A, mtime=T0), _file(other, TEXT_B, mtime=T0 + 5)])
    a, b = _live(bank)
    # The bug's leftover: a second live episode that carries the first one's stamp.
    twin = b.frontmatter | {"relpath": NAME_B, "source_id": mt.source_id(folder["id"], NAME_B)}
    markdown_parser.write(bank / "episodes" / f"{b.frontmatter['id']}.md", twin, b.body)
    assert len(_live(bank)) == 2
    out = _sync(bank, folder, [_file(NAME_A, TEXT_A.replace("beta is ready.", "beta is late."), mtime=T0 + 600)])
    assert out["updated"] == 1 and out["created"] == 0 and len(_live(bank)) == 2   # no guess which copy it belongs to


def test_the_route_carries_resend(client):
    c, bank = client
    fid = c.post("/sources/folders", json={"label": "Hex Meetings", "path": "/Users/example/Documents/Hex Meetings",
                                           "kind": "meetings", "recorder": "hex"}).json()["id"]

    def post(files, deleted=()):
        body = {"files": [{"relpath": f.relpath, "mtime": f.mtime, "sha256": f.sha256, "contentB64": f.content_b64}
                          for f in files], "deleted": list(deleted), "tzName": "Europe/Madrid"}
        return c.post(f"/sources/folders/{fid}/sync", json=body).json()

    post([_file(NAME_A, TEXT_A, mtime=T0), _file(NAME_B, TEXT_B, mtime=T0 + 60)])
    assert post([], [NAME_B])["resend"] == [NAME_A]
    assert post([_file(NAME_A, TEXT_A, mtime=T0)])["resend"] == []
