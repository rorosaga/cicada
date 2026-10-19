"""Ruling 32 — real-time capture for apps with no hook: a remote app's model relays each turn through
`cicada_capture_turns`; one episode per conversation, scrubbed and capped like `/capture/turn`, never the person's
own words, never into a demo bank, not stopped by Sleep; an export of the same conversation upgrades it in place."""
from __future__ import annotations

import re
from datetime import date

import pytest

from _synthetic_bank import _bank
from api import config
from api.remote import catalog
from api.remote.runtime import DENIED_TEXT, RemoteRuntime
from api.services import demo_guard, episode_staging, evidence, markdown_parser, promotion, turn_capture

TODAY = date.today().isoformat()
FIRST = "Help me plan the alpha-project launch for next week, starting with the checklist."
REPLY = "Here is a checklist for the alpha-project launch: scope, owners, dates."
SECOND = "Add a rollback step after the dates please."


def _connector(app="claude", scopes=catalog.DEFAULT_SCOPES, cid="ab12cd34"):
    return catalog.Connector(id=cid, label="Phone", app=app, scopes=frozenset(scopes),
                             created_at="2026-09-01T00:00:00+00:00", auth="oauth")


@pytest.fixture
def memory(tmp_path, monkeypatch):
    bank = _bank(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    config.get_settings.cache_clear()
    yield bank
    config.get_settings.cache_clear()


def _runtime(sleeping=False):
    return RemoteRuntime(post=lambda p, d: {"status": "resolved"}, sleep_running=lambda: sleeping)


def _handle(runtime, connector):
    text, _ = runtime.call(connector, "cicada_handshake", {})
    assert "cicada_capture_turns" in text  # the contract asks for it where the connection holds it
    return re.search(r"`(rc_[a-z0-9]{8}_\d{4}-\d{2}-\d{2}_[0-9a-f]{8})`", text).group(1)


def _relayed(memory):
    found = [p for p in sorted((memory / "episodes").glob("ep_*.md"))
             if isinstance(markdown_parser.parse(p).frontmatter.get("relay"), dict)]
    return found


def _capture(runtime, connector, handle, message, previous=None):
    args = {"conversation": handle, "message": message}
    if previous is not None:
        args["previous_reply"] = previous
    return runtime.call(connector, "cicada_capture_turns", args)


def test_a_conversation_is_one_relayed_episode_turn_by_turn(memory):
    runtime, connector = _runtime(), _connector()
    handle = _handle(runtime, connector)
    assert _capture(runtime, connector, handle, FIRST) == ("Captured. Keep calling this every turn.", "ok")
    assert _capture(runtime, connector, handle, SECOND, REPLY)[1] == "ok"
    assert _capture(runtime, connector, handle, SECOND, REPLY)[0] == "Already captured."  # a re-sent turn
    [path] = _relayed(memory)
    stored = markdown_parser.parse(path)
    fm = stored.frontmatter
    assert stored.body == f"user: {FIRST}\nassistant: {REPLY}\nuser: {SECOND}"
    assert fm["session_id"] == handle and fm["harness"] == "claude-web" and fm["processed"] is False
    assert fm["evidence_kind"] == "assistant" and fm["capture_kind"] == "transcript"
    assert fm["relay"]["app"] == "claude" and fm["relay"]["channel"] == "remote"
    assert fm["relay"]["connector"] == connector.id
    assert fm["relay"]["first"] == turn_capture.relay_match_key(FIRST)


def test_relayed_words_are_never_counted_as_the_persons_own(memory):
    runtime, connector = _runtime(), _connector()
    handle = _handle(runtime, connector)
    _capture(runtime, connector, handle, FIRST)
    _capture(runtime, connector, handle, SECOND, REPLY)
    stored = markdown_parser.parse(_relayed(memory)[0])
    kind = stored.frontmatter["evidence_kind"]
    assert {t.role for t in evidence.turns(stored.body, override=kind)} == {"assistant"}
    assert all(person == "" for person, _ in promotion.exchanges(stored.body, override=kind))
    assert promotion.measure({"name": "alpha-project"}, promotion.exchanges(stored.body, override=kind))[1] is False


def test_capture_scrubs_and_caps_like_a_hook(memory):
    runtime, connector = _runtime(), _connector()
    handle = _handle(runtime, connector)
    secret = "sk-" + "A1b2C3d4E5f6G7h8J9k0"
    _capture(runtime, connector, handle, f"{FIRST} my key is {secret}")
    _capture(runtime, connector, handle, "x " * 5000, "y " * 5000)
    body = markdown_parser.parse(_relayed(memory)[0]).body
    assert secret not in body
    later = body.split("\nuser: ")[-1]
    assert len(later) <= 2100  # a later person turn keeps a 2k head, as on /capture/turn


def test_capture_is_not_stopped_by_sleep_but_never_writes_a_demo_bank(memory):
    runtime, connector = _runtime(sleeping=True), _connector()
    handle = _handle(runtime, connector)
    assert _capture(runtime, connector, handle, FIRST)[1] == "ok"  # a hook-like writer: Sleep reads it next time
    demo_guard.manifest_path(memory).write_text(f"kind: {demo_guard.DEMO_KIND}\n")
    assert demo_guard.is_demo(memory)
    text, status = _capture(_runtime(), connector, handle, SECOND, REPLY)
    assert status == "demo" and len(_relayed(memory)) == 1


def test_capture_needs_record_and_never_reaches_stdio(memory):
    runtime, reader = _runtime(), _connector(scopes={"search", "read"})
    assert runtime.call(reader, "cicada_capture_turns", {"message": FIRST}) == (DENIED_TEXT, "denied")
    assert catalog.TOOL_SCOPE["cicada_capture_turns"] == "record" and "cicada_capture_turns" in catalog.REMOTE_ONLY


def test_an_empty_message_captures_nothing(memory):
    runtime, connector = _runtime(), _connector()
    text, _ = runtime.call(connector, "cicada_capture_turns", {"conversation": _handle(runtime, connector),
                                                               "message": "  "})
    assert "Nothing captured" in text and _relayed(memory) == []


# ── the export upgrades it ──────────────────────────────────────────────────

def _export(source="claude", first=FIRST, when=None, sid="conv-uuid-1"):
    stamp = when or f"{TODAY}T08:00:00+00:00"
    return episode_staging.EpisodeDraft(
        title="Launch plan", source=source, source_id=sid, timestamp=stamp, original_date=stamp[:10],
        turns=[episode_staging.Turn(text=first, speaker="user", ts=stamp),
               episode_staging.Turn(text=REPLY + " (full)", speaker="assistant", ts=stamp),
               episode_staging.Turn(text=SECOND, speaker="user", ts=stamp)])


def test_an_export_of_the_same_conversation_upgrades_the_relayed_episode(memory):
    runtime, connector = _runtime(), _connector()
    handle = _handle(runtime, connector)
    _capture(runtime, connector, handle, FIRST)
    _capture(runtime, connector, handle, SECOND, REPLY)
    [path] = _relayed(memory)
    before = len(list((memory / "episodes").glob("ep_*.md")))
    result = episode_staging.stage([_export()], memory / "episodes")
    assert result.updated == 1 and result.created == 0
    assert len(list((memory / "episodes").glob("ep_*.md"))) == before
    stored = markdown_parser.parse(path)
    fm = stored.frontmatter
    assert fm["source"] == "claude" and fm["source_id"] == "conv-uuid-1" and fm["processed"] is False
    assert "evidence_kind" not in fm and "hook_turns" not in fm
    assert fm["relay"]["upgraded_by"] == "claude" and fm["relay"]["upgraded_at"]
    assert "(full)" in stored.body
    assert {t.role for t in evidence.turns(stored.body)} == {"user", "assistant"}  # now the person's own words
    # A later relay of that conversation leaves the export's episode alone.
    assert _capture(runtime, connector, handle, "One more thing about the launch.", REPLY)[0].startswith(
        "This conversation is already in Cicada")
    assert markdown_parser.parse(path).body == stored.body
    # And a re-import is a plain skip by its source id.
    assert episode_staging.stage([_export()], memory / "episodes").skipped == 1


@pytest.mark.parametrize("draft", [
    _export(source="chatgpt"),                                 # another app's export
    _export(first="hi there"),                                 # too short to tell apart
    _export(first="A different first message about something else entirely."),
    _export(when="2026-01-01T08:00:00+00:00"),                 # far from when it was relayed
], ids=["other-app", "too-short", "different", "far-apart"])
def test_an_export_that_is_not_clearly_the_same_conversation_is_its_own_episode(memory, draft):
    runtime, connector = _runtime(), _connector()
    handle = _handle(runtime, connector)
    _capture(runtime, connector, handle, FIRST if draft.turns[0].text != "hi there" else "hi there")
    result = episode_staging.stage([draft], memory / "episodes")
    assert result.created == 1 and result.updated == 0
    [path] = _relayed(memory)
    assert not markdown_parser.parse(path).frontmatter["relay"].get("upgraded_at")


def test_two_relayed_candidates_upgrade_neither(memory):
    runtime = _runtime()
    for cid in ("ab12cd34", "ef56gh78"):
        connector = _connector(cid=cid)
        _capture(runtime, connector, _handle(runtime, connector), FIRST)
    assert len(_relayed(memory)) == 2
    assert episode_staging.stage([_export()], memory / "episodes").created == 1
