"""G140 Q-R8/Q-R9 (R5 §2 defect 3, §5.7; G22) — what an agent saw in a saved
video, recorded as provenance: one watch episode (`assistant:` summary +
`video [m:ss]:` quotes), one `describes` claim whose spans are `assistant` and
`media`, times derived at read. Cicada fetches nothing. Synthetic bank."""
from __future__ import annotations

import re
import subprocess
import urllib.request

import pytest
from fastapi.testclient import TestClient

from _stdio_server import stdio_server
from _synthetic_bank import _bank
from api import config, main
from api.remote import catalog
from api.remote.runtime import RemoteRuntime
from api.services import evidence, markdown_parser, media_ingestor, mcp_tools
from api.services.claims import EVIDENCE_KINDS, Evidence, parse_claims
from api.services.media_ingestor import MediaMeta

URL = "https://vimeo.com/123456789"
SUMMARY = "A talk on how alpha indexes notes with sqlite-vec and why it stays local."
EXCERPTS = [{"t": 754, "quote": "search is one lookup"}, {"t": "1:05", "quote": "we keep every vector on the laptop"}]


async def _meta(url, client, from_bookmark_file=False):
    # One title per URL: `_media_entity_id` slugs the title alone, so a shared
    # title would make the second save overwrite the first page.
    title = "Alpha Talk" if url == URL else "Beta Talk"
    return MediaMeta(title=title, site="vimeo.com", media_type="url", provider="vimeo")


def _offline(*a, **k):
    raise OSError("no backend in this test")


@pytest.fixture
def saved(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    (memory / "sources").mkdir(exist_ok=True)
    server = stdio_server()
    monkeypatch.setattr(server, "get_memory_path", lambda: memory)
    monkeypatch.setattr(server, "SESSION", server.SessionIdentity("ses_watch_fixed", "claude-code", None))
    monkeypatch.setattr(mcp_tools, "_backend_sleep_running", lambda *a, **k: False)
    monkeypatch.setattr(media_ingestor, "enrich", _meta)
    monkeypatch.setattr(urllib.request, "urlopen", _offline)
    server.handle_tool("cicada_save_url", {"url": URL})
    return server, memory


def _record(server, **kw):
    args = {"url": URL, "summary": SUMMARY, "excerpts": EXCERPTS, **kw}
    return server.handle_tool("cicada_record_watch", args)


def _ids(out):
    return (re.search(r"entity `([^`]+)`", out).group(1), re.search(r"episode `(ep_[^`]+)`", out).group(1),
            re.search(r"claim `([^`]+)`", out).group(1))


def _claim(memory, eid, cid):
    return {c.id: c for c in parse_claims(markdown_parser.parse(memory / "entities" / f"{eid}.md").body)}[cid]


def test_a_video_line_is_media_and_carries_its_time():
    text = "assistant: a summary\n\nvideo [12:34]: a quote\nuser: later"
    at = text.index("a quote")
    assert evidence.speaker_kind(text, at) == "media" and evidence.media_time(text, at) == 754
    assert evidence.media_time(text, text.index("summary")) is None
    assert evidence.speaker_kind(text, text.index("later")) == "user"
    assert [(t.role, t.t) for t in evidence.turns(text)] == [("assistant", None), ("media", 754), ("user", None)]
    assert "media" in EVIDENCE_KINDS
    assert Evidence.from_dict({"episode": "ep_x", "start": 1, "end": 5, "kind": "media"}).kind == "media"


def test_an_untimed_video_line_stays_the_persons_words():
    """Q-R9: the time is what makes a line a video's. A person writing
    "Video: …" in their own message is still the person."""
    text = "user: here is my plan\nVideo: the one I recorded\nuser [0:10]: not a marker either"
    assert evidence.speaker_kind(text, text.index("the one I recorded")) == "user"
    assert evidence.media_time(text, text.index("the one I recorded")) is None
    assert [t.role for t in evidence.turns(text)] == ["user"], "one turn: neither line is a marker"


def test_a_watch_is_an_episode_and_a_describes_claim_with_media_spans(saved):
    server, memory = saved
    out = _record(server)
    eid, ep, cid = _ids(out)
    parsed = markdown_parser.parse(memory / "episodes" / f"{ep}.md")
    assert parsed.body.splitlines() == [f"assistant: {SUMMARY}", "",
                                        "video [1:05]: we keep every vector on the laptop",
                                        "video [12:34]: search is one lookup"], "time order, one line each"
    fm = parsed.frontmatter
    assert (fm["source"], fm["media_entity_id"], fm["processed"], fm["session_id"]) == (
        "video-watch", eid, False, "ses_watch_fixed")
    claim = _claim(memory, eid, cid)
    assert (claim.predicate, claim.object, claim.origin, claim.authored_by) == (
        "describes", SUMMARY, "agent/watch", "claude-code")
    text = evidence.source_text(memory, ep)
    assert [(e.kind, evidence.media_time(text, e.start)) for e in claim.evidence] == [
        ("assistant", None), ("media", 65), ("media", 754)]
    assert "never the transcript" in out


def test_a_quote_the_summary_repeats_still_lands_on_its_video_line(saved):
    server, memory = saved
    out = _record(server, summary="It says search is one lookup, which is the point.",
                  excerpts=[{"t": "0:10", "quote": "search is one lookup"}])
    eid, ep, cid = _ids(out)
    text = evidence.source_text(memory, ep)
    (media,) = [e for e in _claim(memory, eid, cid).evidence if e.kind == "media"]
    assert text[:media.start].endswith("video [0:10]: ")


def test_caps_hold_and_the_reply_says_so(saved):
    server, memory = saved
    excerpts = [{"t": i, "quote": f"{i:02d} " + "q" * 300} for i in range(20)] + [
        {"t": "soon", "quote": "x"}, {"t": "25:00:00", "quote": "past a day"}]
    out = _record(server, summary="word " * 600, excerpts=excerpts)
    _, ep, _ = _ids(out)
    lines = markdown_parser.parse(memory / "episodes" / f"{ep}.md").body.splitlines()
    assert len(lines[0]) <= len("assistant: ") + 1500 and "\n" not in lines[0]
    video = [line for line in lines if line.startswith("video [")]
    assert len(video) == 12 and all(len(line.split(": ", 1)[1]) <= 240 for line in video)
    assert "past a day" not in "\n".join(lines), "a time past MAX_T_S is dropped, never written"
    assert "10 excerpt(s) left out" in out and "cut at 1,500 characters" in out


def test_nothing_is_fetched_for_a_saved_video(saved, monkeypatch):
    server, _ = saved

    async def spy(*a, **k):
        raise AssertionError("record_watch fetched")

    monkeypatch.setattr(media_ingestor, "enrich", spy)
    assert _record(server).startswith("Recorded the watch")


def test_an_unsaved_link_is_saved_first_and_a_local_file_is_refused(saved):
    server, memory = saved
    other = "https://vimeo.com/987654321"
    assert _record(server, url=other).startswith("Recorded the watch")
    assert media_ingestor.url_hash(other) in media_ingestor.load_url_index(memory)
    assert "isn't saved in Cicada yet" in _record(server, url="file:///tmp/example-clip.mov")


def test_the_watch_commits_both_files_under_the_agent_and_is_idempotent(saved):
    server, memory = saved
    eid, ep, _ = _ids(_record(server))
    log = subprocess.run(["git", "-C", str(memory), "log", "-1", "--format=%s%n%b"],
                         capture_output=True, text=True, check=True).stdout
    assert f"episodes/{ep}.md: created (trigger: mcp/claude-code)" in log
    assert f"entities/{eid}.md: updated (source: {ep}, trigger: mcp/claude-code)" in log
    assert "Cicada-Author: claude-code" in log
    count = len(list((memory / "episodes").glob("*.md")))
    assert _ids(_record(server))[1] == ep and len(list((memory / "episodes").glob("*.md"))) == count


def test_chapters_fill_an_empty_page_and_never_overwrite(saved):
    server, memory = saved
    out = _record(server, chapters=[{"t": "2:00", "title": "Demo"}, {"t": "0:00", "title": "Intro"}])
    eid = _ids(out)[0]
    media = markdown_parser.parse(memory / "entities" / f"{eid}.md").frontmatter["media"]
    assert media["chapters"] == [{"t": 0, "title": "Intro"}, {"t": 120, "title": "Demo"}] and "Chapters saved" in out
    again = _record(server, summary="A second look.", chapters=[{"t": "0:00", "title": "Other"}])
    assert "already has chapters" in again
    assert markdown_parser.parse(memory / "entities" / f"{eid}.md").frontmatter["media"]["chapters"][0]["title"] == "Intro"


def test_the_span_route_serves_the_time(saved, monkeypatch):
    server, memory = saved
    _, ep, _ = _ids(_record(server))
    text = evidence.source_text(memory, ep)
    start = text.index("search is one lookup")
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    try:
        body = TestClient(main.app).get(f"/episodes/{ep}/span", params={"start": start, "end": start + 20}).json()
    finally:
        config.get_settings.cache_clear()
    assert body["kind"] == "media" and body["t"] == 754


def test_a_remote_watch_is_record_scope_and_the_apps(saved, monkeypatch):
    _, memory = saved
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    try:
        runtime = RemoteRuntime(post=lambda path, payload: {}, sleep_running=lambda: False)
        phone = catalog.Connector(id="aaaaaaaa", label="Phone", app="claude", scopes=catalog.DEFAULT_SCOPES,
                                  created_at="2026-09-01T00:00:00+00:00")
        text, status = runtime.call(phone, "cicada_record_watch", {"url": URL, "summary": SUMMARY,
                                                                   "excerpts": EXCERPTS})
    finally:
        config.get_settings.cache_clear()
    assert status == "ok" and text.startswith("Recorded the watch"), text
    eid, _, cid = _ids(text)
    assert _claim(memory, eid, cid).origin == "remote:aaaaaaaa"
    assert catalog.TOOL_SCOPE["cicada_record_watch"] == "record" and "cicada_record_watch" in catalog.WRITE_TOOLS
