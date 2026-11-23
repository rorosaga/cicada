"""G244 (ruling 76) — an agent's edit of a raw source file is a contribution: recorded by hash, matched by content in
either order, kept on the episode, drawn as a span's ``corrected_by`` while the body is the one the edit made, and named
in the Corrections record. Made-up files and placeholder names only."""
from __future__ import annotations

import base64
import hashlib
import json
import subprocess
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from api import cli_app, config, main
from api.cli_types import Refusal
from api.services import (bank_index, corrections_record, episode_staging, evidence, markdown_parser, source_edits,
                          source_spans, transcript_capture)
from api.services import folder_source as fs
from api.services import meeting_transcripts as mt

SID = "11111111-2222-4333-8444-555555555555"
T0 = 1_762_200_000.0


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _file(rel, text, mtime=T0):
    raw = text.encode("utf-8")
    return fs.IncomingFile(relpath=rel, mtime=mtime, sha256=hashlib.sha256(raw).hexdigest(),
                           content_b64=base64.b64encode(raw).decode())


def _git(bank, *args):
    return subprocess.run(["git", *args], cwd=bank, check=True, capture_output=True, text=True).stdout


def _commit(bank, message="wip"):
    _git(bank, "add", "-A")
    _git(bank, "commit", "-q", "--allow-empty", "-m", message)


@pytest.fixture
def bank(tmp_path):
    memory = tmp_path / "memory"
    for sub in ("episodes", "entities", "sources"):
        (memory / sub).mkdir(parents=True)
    _git(memory, "init", "-q")
    _git(memory, "config", "user.email", "t@example.invalid")
    _git(memory, "config", "user.name", "t")
    (memory / ".gitignore").write_text("")
    _commit(memory, "init")
    bank_index.invalidate()
    return memory


@pytest.fixture
def folder(bank):
    return fs.register(bank, label="alpha-project", path="/Users/example/alpha-project", device="mac-1")


def _episodes(bank):
    bank_index.invalidate()
    return {markdown_parser.parse(p).frontmatter.get("source_id"): markdown_parser.parse(p)
            for p in sorted((bank / "episodes").glob("ep_*.md"))}


def _only(bank):
    (ep,) = _episodes(bank).values()
    return ep


def _edit(bank, folder, rel, text, *, harness="claude-code", session=SID, at=None, model=None, effort=None, tool="Edit"):
    edit = source_edits.clean(bank, folder_id=folder["id"], relpath=rel, sha256=_sha(text), harness=harness,
                              session_id=session, tool=tool, at=at)
    edit.model, edit.effort = model, effort
    return edit


V1 = "Intro line.\n\nThe plan is to ship in June.\n\nOwner: Bob Example.\n"
V2 = "Intro line.\n\nThe plan is to ship in July.\n\nOwner: Bob Example.\n"
V3 = "Intro line.\n\nThe plan is to ship in July.\n\nOwner: Carol Example.\n"


def _at(day=None):
    """An edit's time: now by default (a sync-first attach needs the version staged around the edit, review B1)."""
    if day is None:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    return datetime(2026, 11, day, 9, 30, tzinfo=timezone.utc).isoformat()


# --- the record, validated -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("kw, reason", [
    ({"folder_id": "no-such-folder"}, "unknown_folder"),
    ({"sha256": "abc"}, "bad_sha"),
    ({"sha256": "G" * 64}, "bad_sha"),
    ({"harness": "unknown"}, "bad_harness"),
    ({"harness": "Not A Harness!"}, "bad_harness"),
    ({"session_id": "has spaces"}, "bad_session"),
    ({"relpath": "../up.md"}, "bad_relpath"),
    ({"relpath": "/etc/passwd"}, "bad_relpath"),
])
def test_a_bad_record_is_refused_with_an_enum_reason(bank, folder, kw, reason):
    base = dict(folder_id=folder["id"], relpath="NOTES.md", sha256=_sha(V2), harness="claude-code", session_id=SID)
    with pytest.raises(source_edits.Refused) as exc:
        source_edits.clean(bank, **{**base, **kw})
    assert exc.value.reason == reason in source_edits.REFUSALS


def test_a_future_or_unreadable_time_is_now_and_a_session_may_be_absent(bank, folder):
    now = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)
    far = source_edits.clean(bank, folder_id=folder["id"], relpath="a.md", sha256=_sha(V2), harness="codex",
                             at="2099-01-01T00:00:00Z", now=now)
    junk = source_edits.clean(bank, folder_id=folder["id"], relpath="a.md", sha256=_sha(V2), harness="codex",
                              at="not a time", now=now)
    assert far.at == junk.at == now.isoformat(timespec="seconds") and far.session is None


# --- the record first: held until the sync stages the bytes ----------------------------------------------------------


def test_a_record_that_arrives_first_rides_the_sync_that_stages_its_bytes(bank, folder):
    fs.sync(bank, folder, [_file("NOTES.md", V1)], [])
    _commit(bank)
    edit = _edit(bank, folder, "NOTES.md", V2, at=_at())
    edit.model, edit.effort = "claude-opus-5-5", "high"
    out = source_edits.receive(bank, edit)
    assert (out.status, out.episodes) == ("held", [])
    assert source_edits.held_count(bank) == 1
    fs.sync(bank, folder, [_file("NOTES.md", V2, mtime=T0 + 60)], [])
    ep = _only(bank)
    (c,) = ep.frontmatter["contributions"]
    assert (c["harness"], c["model"], c["effort"], c["session"]) == ("claude-code", "claude-opus-5-5", "high", SID)
    assert c["content_hash"] == ep.frontmatter["content_hash"]
    lo, hi = c["ranges"][0]
    assert "July" in ep.body[lo:hi] and "Owner" not in ep.body[lo:hi] and "Intro" not in ep.body[lo:hi]
    assert source_edits.held_count(bank) == 0       # carried now: no longer waiting
    assert ep.frontmatter["revised"]["count"] == 1 and ep.frontmatter["evidence_kind"] == "user"


def test_a_record_for_other_bytes_or_another_file_is_never_taken(bank, folder):
    fs.sync(bank, folder, [_file("NOTES.md", V1), _file("OTHER.md", V1)], [])
    source_edits.receive(bank, _edit(bank, folder, "NOTES.md", V2))
    fs.sync(bank, folder, [_file("NOTES.md", V3, mtime=T0 + 60), _file("OTHER.md", V2, mtime=T0 + 60)], [])
    assert all("contributions" not in ep.frontmatter for ep in _episodes(bank).values())
    assert source_edits.held_count(bank) == 1


def test_a_held_record_expires_after_seven_days(bank, folder):
    fs.sync(bank, folder, [_file("NOTES.md", V1)], [])
    now = datetime.now(timezone.utc)
    source_edits.hold(bank, _edit(bank, folder, "NOTES.md", V2), now=now - timedelta(days=source_edits.EXPIRY_DAYS, hours=1))
    assert source_edits.pending_for(bank, folder["id"], "NOTES.md", _sha(V2)) == []
    fs.sync(bank, folder, [_file("NOTES.md", V2, mtime=T0 + 60)], [])
    assert "contributions" not in _only(bank).frontmatter
    source_edits.hold(bank, _edit(bank, folder, "NOTES.md", V3), now=now - timedelta(days=source_edits.EXPIRY_DAYS - 1))
    assert len(source_edits.pending_for(bank, folder["id"], "NOTES.md", _sha(V3))) == 1


def test_the_same_record_twice_is_held_once(bank, folder):
    for _ in range(3):
        source_edits.receive(bank, _edit(bank, folder, "NOTES.md", V2))
    assert source_edits.held_count(bank) == 1


def test_the_store_is_outside_the_bank_and_holds_no_words(bank, folder, tmp_path):
    source_edits.receive(bank, _edit(bank, folder, "NOTES.md", V2))
    path = source_edits.store_path(bank)
    assert path.is_file() and bank not in path.parents
    raw = path.read_text()
    assert "July" not in raw and set(json.loads(raw)["records"][0]) <= {
        "folder_id", "relpath", "sha", "harness", "session", "tool", "model", "effort", "at", "held_at"}


# --- the sync first: attach at once ---------------------------------------------------------------------------------


def test_a_record_that_arrives_after_the_sync_attaches_to_the_episode_that_holds_its_bytes(bank, folder):
    fs.sync(bank, folder, [_file("NOTES.md", V1)], [])
    _commit(bank)
    fs.sync(bank, folder, [_file("NOTES.md", V2, mtime=T0 + 60)], [])
    _commit(bank)
    ep = _only(bank)
    out = source_edits.receive(bank, _edit(bank, folder, "NOTES.md", V2, at=_at()))
    assert (out.status, out.episodes) == ("attached", [ep.frontmatter["id"]])
    assert out.paths == [f"episodes/{ep.frontmatter['id']}.md"] and source_edits.held_count(bank) == 0
    (c,) = _only(bank).frontmatter["contributions"]
    lo, hi = c["ranges"][0]
    assert "July" in ep.body[lo:hi] and "Owner" not in ep.body[lo:hi]      # against the body git held before
    assert c["content_hash"] == ep.frontmatter["content_hash"] and "model" not in c
    # The same post again is the same contribution.
    again = source_edits.receive(bank, _edit(bank, folder, "NOTES.md", V2, at=_at()))
    assert again.episodes == out.episodes and again.paths == []
    assert len(_only(bank).frontmatter["contributions"]) == 1


def test_a_new_file_an_agent_wrote_is_wholly_its_contribution(bank, folder):
    fs.sync(bank, folder, [_file("NEW.md", V1)], [])
    out = source_edits.receive(bank, _edit(bank, folder, "NEW.md", V1, tool="Write"))
    ep = _only(bank)
    assert out.status == "attached"
    assert ep.frontmatter["contributions"][0]["ranges"] == [[0, len(ep.body)]]


def test_an_edit_of_a_file_cicada_had_not_seen_names_the_editor_and_claims_no_span(bank, folder):
    """Review B1: an Edit of a fresh recorder file changed some of its words, which ones unknown — none is claimed."""
    source_edits.receive(bank, _edit(bank, folder, "FRESH.md", V1))          # held: the app has not posted it yet
    fs.sync(bank, folder, [_file("FRESH.md", V1)], [])
    (c,) = _only(bank).frontmatter["contributions"]
    assert c["harness"] == "claude-code" and c["ranges"] == []


def test_a_declared_edit_of_bytes_staged_long_ago_attaches_nothing(bank, folder):
    """Review B1: a no-op write or a declared edit of a file the agent never changed is not the staged version's."""
    fs.sync(bank, folder, [_file("NOTES.md", V1)], [])
    _commit(bank)
    out = source_edits.receive(bank, _edit(bank, folder, "NOTES.md", V1, at=_at(2)))
    assert (out.status, out.episodes, out.reason) == ("attached", [], "no_change")
    assert not _only(bank).frontmatter.get("contributions")


def test_the_body_the_edit_replaced_is_not_guessed_without_git(tmp_path):
    memory = tmp_path / "plain"
    for sub in ("episodes", "entities", "sources"):
        (memory / sub).mkdir(parents=True)
    f = fs.register(memory, label="alpha-project", path="/Users/example/alpha-project", device="mac-1")
    fs.sync(memory, f, [_file("NOTES.md", V2)], [])
    out = source_edits.receive(memory, _edit(memory, f, "NOTES.md", V2))
    assert out.status == "attached"
    assert _only(memory).frontmatter["contributions"][0]["ranges"] == []      # who yes, which words unknown


def test_an_edit_that_moved_on_before_its_record_is_held_not_attached(bank, folder):
    fs.sync(bank, folder, [_file("NOTES.md", V1)], [])
    fs.sync(bank, folder, [_file("NOTES.md", V3, mtime=T0 + 60)], [])
    out = source_edits.receive(bank, _edit(bank, folder, "NOTES.md", V2))
    assert out.status == "held"
    assert "contributions" not in _only(bank).frontmatter


# --- split notes ---------------------------------------------------------------------------------------------------


@pytest.fixture
def small_split(monkeypatch):
    monkeypatch.setattr(fs, "SPLIT_CHARS", 200)


def _note(*sections, intro="Intro line."):
    pad = "word " * 20
    return intro + "\n\n" + "\n\n".join(f"## {name}\n{words}\n{pad}" for name, words in sections)


def _by_tail(bank):
    return {sid.rsplit("#", 1)[-1]: ep for sid, ep in _episodes(bank).items()}


def test_a_split_note_attaches_only_to_the_sections_whose_body_changed_sync_first(bank, folder, small_split):
    v1 = _note(("Retrieval", "alpha reads"), ("Evaluation", "beta scores"))
    v2 = v1.replace("beta scores", "beta scores higher")
    fs.sync(bank, folder, [_file("REF.md", v1)], [])
    _commit(bank)
    fs.sync(bank, folder, [_file("REF.md", v2, mtime=T0 + 60)], [])
    _commit(bank)
    out = source_edits.receive(bank, _edit(bank, folder, "REF.md", v2))
    eps = _by_tail(bank)
    assert out.status == "attached" and out.episodes == [eps["evaluation"].frontmatter["id"]]
    assert "contributions" in eps["evaluation"].frontmatter
    assert "contributions" not in eps["retrieval"].frontmatter and "contributions" not in eps["intro"].frontmatter


def test_a_split_note_attaches_only_to_the_sections_whose_body_changed_record_first(bank, folder, small_split):
    v1 = _note(("Retrieval", "alpha reads"), ("Evaluation", "beta scores"))
    v2 = v1.replace("beta scores", "beta scores higher")
    fs.sync(bank, folder, [_file("REF.md", v1)], [])
    _commit(bank)
    source_edits.receive(bank, _edit(bank, folder, "REF.md", v2))
    fs.sync(bank, folder, [_file("REF.md", v2, mtime=T0 + 60)], [])
    eps = _by_tail(bank)
    assert "contributions" in eps["evaluation"].frontmatter
    assert "contributions" not in eps["retrieval"].frontmatter and "contributions" not in eps["intro"].frontmatter
    assert source_edits.held_count(bank) == 0


def test_a_section_the_edit_removed_is_edited_by_the_agent_with_no_marked_range(bank, folder, small_split):
    v1 = _note(("Retrieval", "alpha reads"), ("Evaluation", "beta scores"))
    v2 = _note(("Retrieval", "alpha reads"))
    fs.sync(bank, folder, [_file("REF.md", v1)], [])
    _commit(bank)
    source_edits.receive(bank, _edit(bank, folder, "REF.md", v2))
    fs.sync(bank, folder, [_file("REF.md", v2, mtime=T0 + 60)], [])
    gone = _by_tail(bank)["evaluation"]
    assert gone.body == "" and gone.frontmatter["contributions"][0]["ranges"] == []


# --- a meeting takeover --------------------------------------------------------------------------------------------

MEETING = """# Alpha planning

- **Date:** Tuesday, November 3, 2026, 4:01 PM
- **Attendees:** Bob Example, Carol Example

## Transcript

**You** · 00:00
Hi Bob, shall we start?

**Them** · 00:04
Yes. The beta is ready.
"""
NAME_A = "2026-11-03 1601 Alpha planning.md"
NAME_B = "2026-11-03 1601 Alpha planning (corrected).md"


def test_a_corrected_copy_that_takes_a_meeting_over_carries_the_edit(bank):
    folder = fs.register(bank, label="Hex Meetings", path="/m", device="mac-1", kind="meetings", recorder="hex")
    fs.sync(bank, folder, [_file(NAME_A, MEETING, mtime=T0)], [], tz_name="Europe/Madrid")
    _commit(bank)
    (first,) = _episodes(bank).values()
    fixed = MEETING.replace("The beta is ready.", "The beta is nearly ready.")
    source_edits.receive(bank, source_edits.clean(bank, folder_id=folder["id"], relpath=NAME_B, sha256=_sha(fixed),
                                                  harness="codex", session_id="codex-session-0001"))
    fs.sync(bank, folder, [_file(NAME_B, fixed, mtime=T0 + 60)], [], tz_name="Europe/Madrid")
    (ep,) = _episodes(bank).values()
    assert ep.frontmatter["id"] == first.frontmatter["id"] and ep.frontmatter["source_id"] == mt.source_id(folder["id"], NAME_B)
    (c,) = ep.frontmatter["contributions"]
    assert c["harness"] == "codex" and ep.body[c["ranges"][0][0]:c["ranges"][0][1]].count("nearly") == 1
    assert "Hi Bob" not in ep.body[c["ranges"][0][0]:c["ranges"][0][1]]


# --- kept through later edits; newest first; capped ------------------------------------------------------------------


def test_contributions_outlive_a_later_unattributed_edit_and_are_newest_first(bank, folder):
    fs.sync(bank, folder, [_file("NOTES.md", V1)], [])
    _commit(bank)
    source_edits.receive(bank, _edit(bank, folder, "NOTES.md", V2, at=_at(23)))
    fs.sync(bank, folder, [_file("NOTES.md", V2, mtime=T0 + 60)], [])
    _commit(bank)
    fs.sync(bank, folder, [_file("NOTES.md", V3, mtime=T0 + 120)], [])      # the recorder's, or the person's: nobody's record
    ep = _only(bank)
    (c,) = ep.frontmatter["contributions"]
    assert c["content_hash"] != ep.frontmatter["content_hash"] and ep.frontmatter["revised"]["count"] == 2
    source_edits.receive(bank, _edit(bank, folder, "NOTES.md", V3, harness="codex", session="codex-session-0002",
                                     at=_at()))
    ep = _only(bank)
    assert [c["harness"] for c in ep.frontmatter["contributions"]] == ["codex", "claude-code"]


def test_the_list_is_capped_and_outside_the_content_hash(bank):
    fm = {}
    for i in range(episode_staging.MAX_CONTRIBUTIONS + 5):
        episode_staging.with_contributions(fm, [{"harness": "codex", "session": f"s{i}", "at": _at(), "content_hash": "h",
                                                 "ranges": []}])
    assert len(fm["contributions"]) == episode_staging.MAX_CONTRIBUTIONS and fm["contributions"][0]["session"] == "s24"
    assert episode_staging.content_hash("body") == episode_staging.content_hash("body")   # a body's hash is the body's alone


# --- spans: corrected_by, and "moved on" ------------------------------------------------------------------------------


def test_a_span_in_the_changed_words_is_corrected_by_the_agent_while_the_body_stands(bank, folder):
    fs.sync(bank, folder, [_file("NOTES.md", V1)], [])
    _commit(bank)
    source_edits.receive(bank, _edit(bank, folder, "NOTES.md", V2, at=_at(), model="claude-opus-5-5"))
    fs.sync(bank, folder, [_file("NOTES.md", V2, mtime=T0 + 60)], [])
    ep = _only(bank)
    doc_id = ep.frontmatter["id"]
    source = source_spans.Source.open(bank, doc_id)
    july = ep.body.index("July")
    hit = source.span(july, july + 4, evidence.body_hash(ep.body), "user")
    assert hit.status == "current" and hit.corrected_by is not None
    assert (hit.corrected_by.harness, hit.corrected_by.model) == ("claude-code", "claude-opus-5-5")
    wire = hit.model_dump(by_alias=True)
    assert wire["correctedBy"]["harness"] == "claude-code" and "sourceRemoved" in wire
    owner = ep.body.index("Owner")
    assert source.span(owner, owner + 5, evidence.body_hash(ep.body), "user").corrected_by is None
    assert source_spans.edited_by(ep.frontmatter).harness == "claude-code"


def test_when_the_body_moves_on_no_span_is_marked_but_the_episode_stays_edited(bank, folder):
    fs.sync(bank, folder, [_file("NOTES.md", V1)], [])
    _commit(bank)
    source_edits.receive(bank, _edit(bank, folder, "NOTES.md", V2))
    fs.sync(bank, folder, [_file("NOTES.md", V2, mtime=T0 + 60)], [])
    fs.sync(bank, folder, [_file("NOTES.md", V3, mtime=T0 + 120)], [])
    ep = _only(bank)
    source = source_spans.Source.open(bank, ep.frontmatter["id"])
    for needle in ("July", "Carol", "Intro"):
        at = ep.body.index(needle)
        assert source.span(at, at + 3, evidence.body_hash(ep.body), "user").corrected_by is None
    assert source_spans.edited_by(ep.frontmatter).harness == "claude-code"
    assert source_spans.SHAPE == "spans3"


def test_an_episode_nobody_edited_has_no_correction():
    assert source_spans.corrected_by({"content_hash": "h"}, 0, 10) is None
    assert source_spans.edited_by({}) is None
    assert source_spans.corrected_by({"content_hash": "h", "contributions": "nonsense"}, 0, 10) is None


# --- the model and the effort: never guessed ---------------------------------------------------------------------------


@pytest.fixture
def roots(tmp_path, monkeypatch):
    root = tmp_path / "claude" / "projects" / "-example"
    root.mkdir(parents=True)
    monkeypatch.setattr(transcript_capture, "harness_root", lambda h: root.parent if h == "claude-code" else tmp_path / "codex")
    monkeypatch.setattr(transcript_capture, "_episode_cache", {})
    return root


def _transcript(root, *, model="claude-opus-5-5", effort="high", session=SID):
    def line(role, content, **extra):
        return json.dumps({"type": role, "timestamp": "2026-11-23T10:00:00.000Z", "sessionId": session,
                           "message": {"role": role, "content": content, **({"model": model} if role == "assistant" and model else {})},
                           **extra})
    path = root / f"{session}.jsonl"
    path.write_text("\n".join([
        line("user", "please fix the plan"),
        line("assistant", [{"type": "text", "text": "Done, I changed the month."}], **({"effort": effort} if effort else {})),
    ]) + "\n")
    return path


def test_the_model_and_effort_come_from_a_transcript_the_hook_named(bank, roots):
    path = _transcript(roots)
    assert source_edits.agent_fields(bank, "claude-code", SID, str(path)) == ("claude-opus-5-5", "high")


def test_a_transcript_outside_the_harness_root_is_ignored_never_an_error(bank, roots, tmp_path):
    stray = tmp_path / f"{SID}.jsonl"
    stray.write_text(_transcript(roots).read_text())
    assert source_edits.agent_fields(bank, "claude-code", SID, str(stray)) == (None, None)
    assert source_edits.agent_fields(bank, "claude-code", SID, "/does/not/exist.jsonl") == (None, None)


def test_without_a_transcript_the_sessions_captured_episode_answers(bank, roots):
    path = _transcript(roots, model="claude-sonnet-5-5", effort="medium")
    transcript_capture.capture_transcript(bank, harness="claude-code", session_id=SID, transcript_path=str(path), cwd=None,
                                          keep_assistant=True, bank=bank.name)
    assert source_edits.agent_fields(bank, "claude-code", SID, None) == ("claude-sonnet-5-5", "medium")
    assert source_edits.agent_fields(bank, "claude-code", SID, "/does/not/exist.jsonl") == ("claude-sonnet-5-5", "medium")


def test_with_neither_the_model_is_left_out(bank, roots, folder):
    assert source_edits.agent_fields(bank, "claude-code", SID, None) == (None, None)
    assert source_edits.agent_fields(bank, "claude-code", None, None) == (None, None)
    fs.sync(bank, folder, [_file("NOTES.md", V2)], [])
    source_edits.receive(bank, _edit(bank, folder, "NOTES.md", V2))
    (c,) = _only(bank).frontmatter["contributions"]
    assert "model" not in c and "effort" not in c


def test_a_transcript_whose_last_turn_names_no_model_is_not_filled_from_elsewhere(bank, roots):
    path = _transcript(roots, model=None, effort=None)
    assert source_edits.agent_fields(bank, "claude-code", SID, str(path)) == (None, None)


# --- the route ------------------------------------------------------------------------------------------------------------


@pytest.fixture
def client(bank, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    yield TestClient(main.app)
    config.get_settings.cache_clear()


def _post(c, folder, rel, text, **kw):
    body = {"folder_id": folder["id"], "relpath": rel, "sha256": _sha(text), "harness": "claude-code",
            "session_id": SID, "tool": "Edit", "at": _at(), **kw}
    return c.post("/capture/source-edit", json=body)


def test_the_route_attaches_in_one_commit_under_the_agent_and_its_session(client, bank, folder):
    fs.sync(bank, folder, [_file("NOTES.md", V1)], [])
    _commit(bank)
    fs.sync(bank, folder, [_file("NOTES.md", V2, mtime=T0 + 60)], [])
    _commit(bank)
    before = _git(bank, "rev-list", "--count", "HEAD").strip()
    r = _post(client, folder, "NOTES.md", V2)
    assert r.status_code == 200, r.text
    ep = _only(bank)
    assert r.json() == {"status": "attached", "episodes": [ep.frontmatter["id"]]}
    assert int(_git(bank, "rev-list", "--count", "HEAD").strip()) == int(before) + 1
    message = _git(bank, "log", "-1", "--format=%B")
    assert "Cicada-Author: claude-code" in message and f"Cicada-Session: {SID}" in message
    assert _git(bank, "status", "--porcelain").strip() == ""          # nothing left dirty
    assert ep.frontmatter["contributions"][0]["harness"] == "claude-code"


def test_the_route_holds_a_record_the_sync_has_not_met_for_a_file_that_does_not_exist(client, bank, folder):
    """The backend never opens ``relpath``: a path that exists nowhere is held like any other."""
    r = _post(client, folder, "no/such/dir/secret.md", V2)
    assert r.status_code == 200 and r.json() == {"status": "held", "episodes": []}
    assert source_edits.held_count(bank) == 1


@pytest.mark.parametrize("kw, reason", [({"folder_id": "nope"}, "unknown_folder"), ({"sha256": "12"}, "bad_sha"),
                                        ({"harness": "unknown"}, "bad_harness"), ({"session_id": "a b"}, "bad_session"),
                                        ({"relpath": "../x.md"}, "bad_relpath")])
def test_the_route_refuses_in_the_body_with_an_enum_reason(client, bank, folder, kw, reason):
    r = _post(client, folder, "NOTES.md", V2, **kw)
    assert r.status_code == 200 and r.json() == {"status": "refused", "episodes": [], "reason": reason}
    assert source_edits.held_count(bank) == 0


def test_the_route_accepts_snake_case_only_keys_and_ignores_a_bad_transcript(client, bank, folder):
    r = _post(client, folder, "NOTES.md", V2, transcript_path="/etc/passwd")
    assert r.status_code == 200 and r.json()["status"] == "held"


# --- the Corrections record names the editor ------------------------------------------------------------------------------


def test_the_corrections_record_and_commit_body_name_who_edited(bank, folder):
    fs.sync(bank, folder, [_file("NOTES.md", V1)], [])
    _commit(bank)
    source_edits.receive(bank, _edit(bank, folder, "NOTES.md", V2))
    fs.sync(bank, folder, [_file("NOTES.md", V2, mtime=T0 + 60)], [])
    ep = _only(bank).frontmatter["id"]
    editors = source_edits.editors(bank, [ep, "ep_2026-01-01_999"])
    assert editors == {ep: "claude-code"}
    entry = corrections_record.batch_entry({"revised": [ep, "ep_2026-01-01_998"]}, editors=editors)
    assert entry["by"] == {ep: "claude-code"}
    lines = corrections_record.commit_lines(entry)
    assert lines == [f"corrections: revised {ep} (edited by claude-code), ep_2026-01-01_998"]
    merged = corrections_record.merge(entry, corrections_record.batch_entry({"revised": ["ep_2026-02-02_001"]}))
    assert merged["by"] == {ep: "claude-code"}
    assert corrections_record.batch_entry({"revised": ["ep_2026-02-02_001"]}).get("by") is None


def test_a_later_revision_nobody_recorded_is_not_named_for_an_older_edit(bank, folder):
    """Review B2: the run names an editor only when that edit made the body Sleep reads now."""
    fs.sync(bank, folder, [_file("NOTES.md", V1)], [])
    _commit(bank)
    source_edits.receive(bank, _edit(bank, folder, "NOTES.md", V2))
    fs.sync(bank, folder, [_file("NOTES.md", V2, mtime=T0 + 60)], [])
    _commit(bank)
    fs.sync(bank, folder, [_file("NOTES.md", V3, mtime=T0 + 120)], [])      # the recorder's rewrite, no record
    ep = _only(bank).frontmatter["id"]
    assert source_edits.editors(bank, [ep]) == {}


# --- the CLI: for an agent's shell only -------------------------------------------------------------------------------------


def test_watched_file_matches_the_longest_folder_and_its_rules(tmp_path):
    root = tmp_path / "notes"
    (root / "deep").mkdir(parents=True)
    (root / "deep" / "a.md").write_text("x")
    (root / "deep" / "a.png").write_text("x")
    folders = [{"id": "outer", "path": str(root), "device": "mac-1"},
               {"id": "inner", "path": str(root / "deep"), "device": "mac-1"},
               {"id": "elsewhere", "path": str(root), "device": "mac-2"}]
    folder, rel = cli_app.watched_file(root / "deep" / "a.md", folders, "mac-1")
    assert (folder["id"], rel) == ("inner", "a.md")
    assert cli_app.watched_file(root / "deep" / "a.png", folders, "mac-1") is None      # not a file the folder stages
    assert cli_app.watched_file(tmp_path / "other.md", folders, "mac-1") is None
    assert cli_app.watched_file(root / "deep" / "a.md", folders, "mac-9") is None


class _Boot:
    probe: dict = {}


def test_the_command_refuses_from_a_shell_that_names_no_agent(monkeypatch, tmp_path):
    monkeypatch.setattr(cli_app, "caller", lambda environ=None: ("", "unknown"))
    f = tmp_path / "a.md"
    f.write_text("x")
    with pytest.raises(Refusal) as exc:
        cli_app.cmd_source_edit(object(), type("A", (), {"file": str(f)})())
    assert exc.value.code == "refused" and "agent" in str(exc.value)


def test_the_command_posts_the_hash_and_the_relative_path_through_the_backend(monkeypatch, tmp_path):
    root = tmp_path / "notes"
    root.mkdir()
    f = root / "a.md"
    f.write_text("hello")
    sent = []

    def fake_call(boot, method, path, **kw):
        sent.append((method, path, kw.get("body")))
        return {"folders": [{"id": "f1", "path": str(root), "device": "dev"}]} if method == "GET" \
            else {"status": "attached", "episodes": ["ep_2026-11-23_001"]}

    monkeypatch.setattr(cli_app, "caller", lambda environ=None: (SID, "claude-code"))
    monkeypatch.setattr(cli_app, "call", fake_call)
    monkeypatch.setattr("api.services.local_refs.current_device_id", lambda: "dev")
    result = cli_app.cmd_source_edit(_Boot(), type("A", (), {"file": str(f)})())
    assert result.data["status"] == "attached"
    (_, _, _), (method, path, body) = sent
    assert (method, path) == ("POST", "/capture/source-edit")
    assert body == {"folder_id": "f1", "relpath": "a.md", "sha256": hashlib.sha256(b"hello").hexdigest(),
                    "harness": "claude-code", "tool": "cli", "at": body["at"], "session_id": SID}


# --- where else it is drawn: a citation's reference, a popover's quote, an agent's recall detail ---------------------------


def _corrected_episode(bank, folder):
    fs.sync(bank, folder, [_file("NOTES.md", V1)], [])
    _commit(bank)
    source_edits.receive(bank, _edit(bank, folder, "NOTES.md", V2, at=_at(), model="claude-opus-5-5"))
    fs.sync(bank, folder, [_file("NOTES.md", V2, mtime=T0 + 60)], [])
    return _only(bank)


def test_a_citation_reference_says_who_edited_the_source_and_an_unedited_one_says_nothing(bank, folder):
    from api.services import page_citations

    ep = _corrected_episode(bank, folder)
    ref = page_citations._Sources(bank).ref(ep.frontmatter["id"])
    wire = page_citations._ref_dict(ref)
    assert wire["editedBy"] == {"harness": "claude-code", "model": "claude-opus-5-5", "at": _at()}
    assert "(edited by claude-code · claude-opus-5-5)" in page_citations.ref_words(wire)
    plain = page_citations._ref_dict(page_citations._Ref(n=1, key="k", kind="conversation"))
    assert "editedBy" not in plain and "edited by" not in page_citations.ref_words({**plain, "title": "t"})


def test_a_popovers_quote_carries_corrected_by_only_over_the_changed_words(bank, folder):
    from api.models.schemas import ProvenanceSpan
    from api.services import provenance

    ep = _corrected_episode(bank, folder)
    indexed = bank_index.file(bank, "episodes", f"{ep.frontmatter['id']}.md")
    july = ep.body.index("July")
    over = ProvenanceSpan(episode=ep.frontmatter["id"], start=july, end=july + 4)
    provenance._mark_corrected(over, indexed)
    assert over.corrected_by.harness == "claude-code" and over.model_dump(by_alias=True)["correctedBy"]["model"] == "claude-opus-5-5"
    under = ProvenanceSpan(episode=ep.frontmatter["id"], start=0, end=5)
    provenance._mark_corrected(under, indexed)
    held = ProvenanceSpan(episode=ep.frontmatter["id"], start=july, end=july + 4, held=True)
    provenance._mark_corrected(held, indexed)
    stale = ProvenanceSpan(episode=ep.frontmatter["id"], stale=True)
    provenance._mark_corrected(stale, indexed)
    assert under.corrected_by is None and held.corrected_by is None and stale.corrected_by is None


def test_the_recall_detail_line_names_the_editor_and_says_the_words_stay_their_speakers(bank, folder):
    from api.services import mcp_tools

    ep = _corrected_episode(bank, folder)
    line = mcp_tools._corrected_sources_line(bank, f"Said in {ep.frontmatter['id']} and ep_2026-01-01_999.")
    assert f"`{ep.frontmatter['id']}` corrected by claude-code · claude-opus-5-5" in line and "their speaker's" in line
    assert mcp_tools._corrected_sources_line(bank, "ep_2026-01-01_999 only") is None


def test_the_sleep_run_detail_carries_who_edited(bank):
    from api.services import sleep_run_detail

    summary = {"corrections": corrections_record.batch_entry({"revised": ["ep_2026-11-23_001"]},
                                                             editors={"ep_2026-11-23_001": "claude-code"})}
    got = sleep_run_detail._corrections(bank, summary)
    assert got.by == {"ep_2026-11-23_001": "claude-code"} and got.model_dump(by_alias=True)["by"]
