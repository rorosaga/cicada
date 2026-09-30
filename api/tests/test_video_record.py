"""G162 — `cicada_record_watch`'s three new arguments (`basis`, `engine`, `duration`): the union on a
repeat (A2), the two documented divergences from the belief layer (A3), dropped values (A4), and the
model join on the watch block (M3). Synthetic banks; the MCP body runs in-process."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from _video_fixtures import add_video, url_of
from _synthetic_bank import _bank
from api import config, main
from api.services import bank_index, markdown_parser, mcp_tools, video_state
from api.services.claims import parse_claims

URL = url_of("00")
SUMMARY = "A talk on how alpha indexes notes with sqlite-vec."
EXCERPTS = [{"t": "1:05", "quote": "we keep every vector on the laptop"}]
SESSION = "ses_video_record_01"


@pytest.fixture
def rig(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    key = add_video(memory, "00", duration_s=None)
    monkeypatch.setattr(mcp_tools, "_backend_sleep_running", lambda *a, **k: False)
    monkeypatch.setattr(mcp_tools, "_now_ts", lambda: "2026-09-03T10:05:10Z")
    ctx = mcp_tools.ToolContext(memory_path=lambda: memory, session_id=SESSION, harness="claude-code")
    return ctx, memory, key


def _record(ctx, **kw):
    args = {"summary": SUMMARY, "excerpts": EXCERPTS, **kw}
    return mcp_tools.record_watch(ctx, URL, args.pop("summary"), args.pop("excerpts"), None,
                                  args.get("basis"), args.get("engine"), args.get("duration"))


def _episodes(memory):
    return sorted(memory.glob("episodes/ep_*.md"), key=lambda p: p.name)


def _watch_eps(memory):
    return [p for p in _episodes(memory) if markdown_parser.parse(p).frontmatter.get("source") == "video-watch"]


def _state(memory, key):
    return video_state.state_of(video_state.watch_records(memory).get(key, []))


def _git_clean(memory) -> bool:
    import subprocess

    return subprocess.run(["git", "-C", str(memory), "status", "--porcelain"], capture_output=True,
                          text=True).stdout.strip() == ""


def test_a_stated_basis_and_engine_are_kept_on_the_episode(rig):
    ctx, memory, key = rig
    out = _record(ctx, basis="transcript", engine="captions")
    (ep,) = _watch_eps(memory)
    fm = markdown_parser.parse(ep).frontmatter
    assert (fm["watch_basis"], fm["watch_engine"]) == ("transcript", "captions")
    assert _state(memory, key) == "transcript"
    assert "Pass basis" not in out and "off the person's video queue" not in out


def test_an_omitted_basis_is_recorded_and_the_reply_asks_for_it(rig):
    ctx, memory, key = rig
    out = _record(ctx)
    (ep,) = _watch_eps(memory)
    assert "watch_basis" not in markdown_parser.parse(ep).frontmatter
    assert _state(memory, key) == "recorded" and "Pass basis (transcript, frames or both)" in out


def test_same_hash_new_basis_unions_in_place(rig):
    """A2: no second episode; `transcript` + `frames` becomes `both`; the hash is kept and `processed`
    is not flipped (Sleep may already have read the first record)."""
    ctx, memory, key = rig
    _record(ctx, basis="transcript", engine="captions")
    (ep,) = _watch_eps(memory)
    first = markdown_parser.parse(ep).frontmatter
    markdown_parser.write(ep, {**first, "processed": True, "processed_by": "sleep"},
                          markdown_parser.parse(ep).body)
    bank_index.invalidate(memory)
    _record(ctx, basis="frames", engine="local_frames")
    eps = _watch_eps(memory)
    assert len(eps) == 1
    fm = markdown_parser.parse(eps[0]).frontmatter
    assert fm["watch_basis"] == "both" and fm["watch_engine"] == "local_frames"
    assert fm["content_hash"] == first["content_hash"]
    assert fm["processed"] is True and fm["processed_by"] == "sleep"
    assert _state(memory, key) == "watched_and_transcript"


def test_a_repeat_that_states_nothing_never_downgrades(rig):
    ctx, memory, key = rig
    _record(ctx, basis="both", engine="captions")
    _record(ctx)
    (ep,) = _watch_eps(memory)
    assert markdown_parser.parse(ep).frontmatter["watch_basis"] == "both"


def test_a_stated_basis_replaces_an_unstated_one(rig):
    ctx, memory, key = rig
    _record(ctx)
    _record(ctx, basis="transcript")
    (ep,) = _watch_eps(memory)
    assert markdown_parser.parse(ep).frontmatter["watch_basis"] == "transcript"


def test_the_repeat_commits_its_change_and_leaves_the_tree_clean(rig):
    """The union rewrites the episode file: its path rides the write's commit, so no dirty file is left
    for the next `git add -A` writer (the G85-class smear)."""
    ctx, memory, key = rig
    import subprocess

    for args in (["add", "-A"], ["commit", "-q", "-m", "fixture"]):
        subprocess.run(["git", "-C", str(memory), *args], check=True, capture_output=True)
    _record(ctx, basis="transcript")
    assert _git_clean(memory)
    _record(ctx, basis="frames")
    assert _git_clean(memory)


def test_retraction_and_no_excerpt_divergence(rig):
    """A3: two documented divergences from the belief layer's rule ("a `describes` claim with a `media`
    span"). A record with a summary and no valid excerpt has no `media` span, yet the episode says it
    was read; and retracting the claim does not un-read the video (R-VU1)."""
    ctx, memory, key = rig
    out = mcp_tools.record_watch(ctx, URL, SUMMARY, [{"t": "soon", "quote": "x"}], None, "frames", "local_frames")
    eid = "media-00"
    claims = [c for c in parse_claims(markdown_parser.parse(memory / "entities" / f"{eid}.md").body)
              if c.predicate == "describes"]
    (claim,) = claims
    assert not any(e.kind == "media" for e in claim.evidence), "belief layer: no media span, so 'not watched'"
    assert _state(memory, key) == "watched", "episode layer: the agent did watch"
    result = mcp_tools.retract_claim(ctx, eid, claim.id, "wrong video")
    assert "retract" in result.lower() or "withdr" in result.lower() or "closed" in result.lower(), result
    assert _state(memory, key) == "watched", "a withdrawn claim does not un-watch the video"


def test_unknown_engine_and_duration_dropped(rig):
    """A4: the record is still written; an unreadable duration and an engine spelled with a provider's
    name (the retired `gemini_url`) are dropped and the reply says so; `duration` never overwrites."""
    ctx, memory, key = rig
    out = _record(ctx, basis="transcript", engine="gemini_url", duration="soon")
    (ep,) = _watch_eps(memory)
    fm = markdown_parser.parse(ep).frontmatter
    assert "watch_engine" not in fm and fm["watch_basis"] == "transcript"
    assert "engine isn't one Cicada knows" in out and "duration could not be read" in out
    page = markdown_parser.parse(memory / "entities" / "media-00.md").frontmatter
    assert "duration_s" not in page["media"]


def test_a_duration_fills_an_empty_page_and_never_overwrites(rig, tmp_path):
    ctx, memory, key = rig
    _record(ctx, basis="transcript", duration="8:14")
    assert markdown_parser.parse(memory / "entities" / "media-00.md").frontmatter["media"]["duration_s"] == 494
    _record(ctx, summary="A different account of the same video.", basis="transcript", duration="1:00:00")
    assert markdown_parser.parse(memory / "entities" / "media-00.md").frontmatter["media"]["duration_s"] == 494


def test_a_provider_length_is_never_overwritten(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    add_video(memory, "00", duration_s=600)
    monkeypatch.setattr(mcp_tools, "_backend_sleep_running", lambda *a, **k: False)
    ctx = mcp_tools.ToolContext(memory_path=lambda: memory, session_id=SESSION, harness="claude-code")
    mcp_tools.record_watch(ctx, URL, SUMMARY, None, None, "transcript", None, "5:00")
    assert markdown_parser.parse(memory / "entities" / "media-00.md").frontmatter["media"]["duration_s"] == 600


def test_an_unrecognised_basis_is_dropped_not_fatal(rig):
    ctx, memory, key = rig
    out = _record(ctx, basis="telepathy")
    assert "isn't one of transcript, frames or both" in out
    assert _state(memory, key) == "recorded"


# --- M3: the model on the watch block is the turn join ------------------------------------------------------


def _capture(memory, *, models: bool = True):
    body = ("user: Watch the lantern video for me.\n"
            "assistant: Recorded it.")
    starts = [0, body.index("assistant:")]
    sidecar = [{"offset": starts[0], "ts": "2026-09-03T10:05:00+00:00", "speaker": "user"},
               {"offset": starts[1], "ts": "2026-09-03T10:05:30+00:00", "speaker": "assistant",
                **({"model": "claude-opus-5-5", "effort": "high"} if models else {})}]
    markdown_parser.write(memory / "episodes" / "ep_2026-09-03_001.md",
                          {"id": "ep_2026-09-03_001", "timestamp": "2026-09-03T10:05:00+00:00",
                           "source": "claude-code", "capture_kind": "transcript", "session_id": SESSION,
                           "processed": True, "turns": sidecar}, body)
    bank_index.invalidate(memory)


def _text(memory, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    try:
        (ep,) = _watch_eps(memory)
        return TestClient(main.app).get(f"/episodes/{ep.stem}/text").json()
    finally:
        config.get_settings.cache_clear()


def test_watch_block_author_model_from_turn_join(rig, monkeypatch):
    ctx, memory, key = rig
    _capture(memory)
    _record(ctx, basis="transcript", engine="captions")
    watch = _text(memory, monkeypatch)["watch"]
    assert (watch["authorModel"], watch["authorEffort"]) == ("claude-opus-5-5", "high")


def test_watch_block_no_model_without_capture(rig, monkeypatch):
    """A write with no captured turn (Codex, a remote app, no hook) has no join: null, never a guess."""
    ctx, memory, key = rig
    _record(ctx, basis="transcript", engine="captions")
    watch = _text(memory, monkeypatch)["watch"]
    assert watch["authorModel"] is None and watch["authorEffort"] is None
    assert watch["basis"] == "transcript" and watch["fidelity"] == "verbatim"


def test_watch_block_no_model_when_the_capture_names_none(rig, monkeypatch):
    ctx, memory, key = rig
    _capture(memory, models=False)
    _record(ctx, basis="transcript")
    watch = _text(memory, monkeypatch)["watch"]
    assert watch["authorModel"] is None
