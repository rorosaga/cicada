"""G166 (spec §8.4) — `cicada_reading_queue`: empty unless the person turned agent
reading on; only links they asked about; never a denied class or a video; a walled
link only with its switch on, one per call; the remote reply names the record
tool only when the connection holds it. Synthetic bank."""
from __future__ import annotations

import re

import pytest

from _reading_fixtures import PUBLIC, WALLED, ask, enable, reading, record  # noqa: F401
from api.remote import catalog
from api.remote.runtime import RemoteRuntime
from api.services import media_ingestor, reading_asks, reading_settings


def _queue(server, **args):
    return server.handle_tool("cicada_reading_queue", args)


def test_off_by_default_and_says_so(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    from _reading_fixtures import stdio_server, _bank

    server = stdio_server()
    memory = _bank(tmp_path)
    monkeypatch.setattr(server, "get_memory_path", lambda: memory)
    assert _queue(server).startswith("Agent reading is off")


def test_empty_says_nothing_is_waiting(reading):
    server, _ = reading
    assert _queue(server).startswith("Nothing is waiting")


def test_a_person_ask_is_listed_with_its_host_and_day_and_names_the_record_tool(reading):
    server, memory = reading
    ask(memory, PUBLIC)
    out = _queue(server)
    lines = out.splitlines()
    assert lines[0].startswith("1 link(s) the person asked an agent to read.")
    assert "`cicada_record_read(url, outcome, summary, excerpts=[{quote}], via)`" in lines[0]
    assert "do not sign in or type credentials" in lines[0] and "`needs_login`" in lines[0]
    assert lines[1].startswith(f"1. {PUBLIC} (blog.bob-example.org, asked ")


def test_a_saved_link_nobody_asked_about_is_never_listed(reading):
    server, memory = reading
    ask(memory, PUBLIC)
    reading_asks.drop(memory, media_ingestor.url_hash(PUBLIC))
    assert _queue(server).startswith("Nothing is waiting")


def test_only_waiting_rows_are_listed_and_oldest_first(reading):
    server, memory = reading
    urls = [f"https://blog.bob-example.org/p/{i}" for i in range(4)]
    for url in urls:
        ask(memory, url)
    record(server, url=urls[1], outcome="failed")
    listed = [line.split()[1] for line in _queue(server).splitlines()[1:]]
    assert listed == [urls[0], urls[2], urls[3]]


def test_the_limit_is_clamped_and_the_rest_is_counted(reading):
    server, memory = reading
    for i in range(5):
        ask(memory, f"https://blog.bob-example.org/p/{i}")
    out = _queue(server, limit=2)
    assert len(out.splitlines()) == 1 + 2 + 1 and "3 more link(s) are waiting" in out
    assert len(_queue(server, limit=0).splitlines()) == 1 + 1 + 1, "0 clamps up to one"
    assert len(_queue(server, limit="lots").splitlines()) == 1 + 5, "an unreadable limit is the maximum"
    assert len(_queue(server, limit=999).splitlines()) == 1 + 5


def test_a_walled_link_appears_only_with_its_switch_and_one_per_call(reading):
    server, memory = reading
    enable(hosts=("x", "linkedin"))
    urls = ["https://x.com/alpha/status/1", "https://x.com/alpha/status/2", "https://www.linkedin.com/in/alpha",
            PUBLIC, "https://blog.bob-example.org/p/2"]
    for url in urls:
        ask(memory, url)
    out = _queue(server)
    listed = [line.split()[1] for line in out.splitlines()[1:] if re.match(r"\d+\. ", line)]
    assert listed == [urls[0], PUBLIC, "https://blog.bob-example.org/p/2"], "one walled row, the rest public"
    assert "2 more link(s) are waiting" in out
    enable(hosts=())
    off = [line.split()[1] for line in _queue(server).splitlines()[1:] if re.match(r"\d+\. ", line)]
    assert off == [PUBLIC, "https://blog.bob-example.org/p/2"], "a switched-off site is never listed"


def test_a_link_that_became_denied_is_not_listed(reading):
    server, memory = reading
    ask(memory, PUBLIC)
    idx = media_ingestor.load_url_index(memory)
    idx[media_ingestor.url_hash(PUBLIC)]["url"] = "https://blog.bob-example.org/a?token=abc"
    media_ingestor.save_url_index(memory, idx)
    assert _queue(server).startswith("Nothing is waiting")


def test_a_video_or_paper_can_never_be_asked_so_never_listed(reading):
    server, memory = reading
    from api.services import reading_service
    import asyncio

    for url in ("https://vimeo.com/123456789", "https://arxiv.org/abs/2401.00001", "http://192.168.1.5/a"):
        with pytest.raises(reading_service.AskRefused) as err:
            asyncio.run(reading_service.ask(memory, url))
        assert err.value.status == 422
    assert _queue(server).startswith("Nothing is waiting")


def test_the_reply_carries_no_conversation_title_or_the_persons_note(reading):
    server, memory = reading
    ask(memory, PUBLIC)
    record(server, outcome="needs_login", note="An agent note the app shows, never the queue.")
    ask(memory, PUBLIC)
    assert "An agent note" not in _queue(server)


# --- remote ------------------------------------------------------------------------


def _remote(memory, scopes):
    runtime = RemoteRuntime(memory_path=lambda: memory, post=lambda p, d: {}, sleep_running=lambda: False)
    connector = catalog.Connector(id="aaaaaaaa", label="Phone", app="chatgpt", scopes=frozenset(scopes),
                                  created_at="2026-09-01T00:00:00+00:00")
    return runtime, connector


def test_a_read_scope_connection_sees_the_ask_url_fenced_and_no_record_tool_without_record_scope(reading):
    _, memory = reading
    ask(memory, PUBLIC)
    runtime, connector = _remote(memory, {"read"})
    text, status = runtime.call(connector, "cicada_reading_queue", {})
    assert status == "ok" and PUBLIC in text, "an ask URL is the person's own hand-off to an agent"
    assert text.startswith("Reference data from Cicada") and "<<<cicada-reference" in text
    assert "cicada_record_read" not in text, "R12 for replies: this connection cannot call it"
    runtime, connector = _remote(memory, {"read", "record"})
    text, _ = runtime.call(connector, "cicada_reading_queue", {})
    assert "`cicada_record_read(url, outcome, summary, excerpts=[{quote}], via)`" in text


def test_sources_scope_is_not_needed_for_an_ask_but_still_gates_a_persons_words(reading):
    """The ruling: an ask carries no words of the person's, so `read` is enough; what
    `sources` gates (a conversation's verbatim words, a chat-harvested URL) is not
    in this tool at all."""
    _, memory = reading
    ask(memory, PUBLIC)
    runtime, connector = _remote(memory, {"read"})
    text, _ = runtime.call(connector, "cicada_reading_queue", {})
    assert PUBLIC in text and "title" not in text.lower()


def test_a_connection_without_read_cannot_call_the_queue(reading):
    _, memory = reading
    runtime, connector = _remote(memory, {"search", "record"})
    assert runtime.call(connector, "cicada_reading_queue", {})[1] == "denied"
    runtime, connector = _remote(memory, {"read"})
    assert runtime.call(connector, "cicada_record_read", {"url": PUBLIC, "outcome": "failed"})[1] == "denied"


def test_the_remote_queue_is_empty_when_reading_is_off(reading):
    _, memory = reading
    ask(memory, PUBLIC)
    reading_settings.update(agent_enabled_=False)
    runtime, connector = _remote(memory, {"read"})
    text, _ = runtime.call(connector, "cicada_reading_queue", {})
    assert "Agent reading is off" in text and PUBLIC not in text
