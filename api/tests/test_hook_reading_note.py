"""G166 — the waiting-links sentence. Nothing tells an agent to check the reading
queue, and the queue lives outside the bank (so `_state.md` cannot carry it), so
the recall hook adds ONE per-request sentence — "N links are waiting in Cicada's
reading queue for an agent to read" — only while agent reading is on and only when
more wait than this session was last told (a new ask always; pages of allowed sites
only once they grew by ten, so a long session is not re-told for every save). Never stored, never in `_state.md`, never
captured back as the person's words. The remote handshake adds the same sentence
for a connection that can read the queue."""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.remote import catalog
from api.remote.runtime import RemoteRuntime
from api.services import hook_recall, media_ingestor, reading_asks, reading_service, reading_settings, recall_text
from api.services import transcript_extract
from test_hook_context_route import URL, _body, _clean  # noqa: F401 — autouse cleanup
from test_hook_recall import _index, bank  # noqa: F401
from _reading_fixtures import PUBLIC, enable, put_page


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))


@pytest.fixture
def client(bank, monkeypatch):  # noqa: F811
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    config.get_settings.cache_clear()
    yield TestClient(main.app)
    config.get_settings.cache_clear()


def _ask(memory, url=PUBLIC):
    return asyncio.run(reading_service.ask(memory, url))


def test_nothing_is_added_while_agent_reading_is_off(client, bank):
    data = client.post(URL, json=_body(None, event="session_start")).json()
    assert data["reason"] == "primer" and "reading queue" not in data["additionalContext"]
    assert hook_recall.waiting_links(bank) == 0


def test_session_start_says_so_and_a_prompt_does_not_repeat_it(client, bank):
    enable()
    _ask(bank)
    start = client.post(URL, json=_body(None, event="session_start")).json()
    assert start["reason"] == "primer" and start["additionalContext"].startswith(recall_text.PRIMER_HEADER)
    assert recall_text.reading_line(1) in start["additionalContext"]
    first = client.post(URL, json=_body("fix the failing test in the parser")).json()
    assert first["additionalContext"] is None and first["reason"] == "no_match", "the session was already told"


def test_a_session_that_never_started_hears_it_on_its_first_prompt_and_again_only_when_more_wait(client, bank):
    enable()
    _ask(bank)
    r = client.post(URL, json=_body("fix the failing test in the parser", session="s-9")).json()
    assert r["reason"] == "reading" and r["injected"] == []
    assert r["additionalContext"] == f"{recall_text.READING_HEADER}\n{recall_text.reading_line(1)}"
    again = client.post(URL, json=_body("fix the failing test in the parser", session="s-9")).json()
    assert again["additionalContext"] is None
    _ask(bank, "https://blog.bob-example.org/post/2")
    more = client.post(URL, json=_body("fix the failing test in the parser", session="s-9")).json()
    assert recall_text.reading_line(2) in more["additionalContext"]


def test_a_drained_queue_lets_the_next_ask_count_as_new_in_the_same_session(client, bank):
    enable()
    _ask(bank)
    body = lambda: _body("fix the failing test in the parser", session="s-drain")  # noqa: E731
    assert client.post(URL, json=body()).json()["reason"] == "reading"
    reading_asks.record_outcome(bank, media_ingestor.url_hash(PUBLIC), "needs_login")
    assert client.post(URL, json=body()).json()["additionalContext"] is None, "nothing waits, nothing said"
    _ask(bank, "https://blog.bob-example.org/post/2")
    again = client.post(URL, json=body()).json()
    assert recall_text.reading_line(1) in again["additionalContext"], "a second ask after a drain is new"


def test_it_rides_beside_a_page_note(client, bank):
    enable()
    _ask(bank)
    r = client.post(URL, json=_body(session="s-2")).json()
    assert r["reason"] == "injected" and r["injected"] == ["alpha-project"]
    text = r["additionalContext"]
    assert text.startswith(recall_text.RECALL_HEADER) and text.endswith(recall_text.reading_line(1))
    page_part = text.rsplit("\n\n", 1)[0]
    assert len(page_part) // 4 <= hook_recall.MAX_TOKENS, "the page note keeps its own 400-token budget"


def test_a_wall_page_of_a_site_that_is_not_allowed_is_not_counted_but_an_ask_is(client, bank):
    enable()
    _ask(bank, "https://x.com/alpha/status/1")
    assert hook_recall.waiting_links(bank) == 1, "an explicit ask needs no site permission"
    reading_asks.drop(bank, media_ingestor.url_hash("https://x.com/alpha/status/1"))
    assert hook_recall.waiting_links(bank) == 0, "a saved wall page of a site nobody allowed"
    enable(sites=("x",))
    from api.services import bank_index

    bank_index.invalidate(bank)
    assert hook_recall.waiting_links(bank) in (0, 1)  # cold cache: the derived part is counted next prompt
    bank_index.files(bank, "entities")
    assert hook_recall.waiting_links(bank) == 1, "allowed: it is waiting, with no write anywhere"
    enable(sites=())
    assert hook_recall.waiting_links(bank) == 0


def test_only_waiting_links_count_and_an_outcome_stops_the_sentence(client, bank):
    enable()
    _ask(bank)
    reading_asks.record_outcome(bank, media_ingestor.url_hash(PUBLIC), "needs_login")
    assert hook_recall.waiting_links(bank) == 0


def test_the_note_is_never_captured_back_as_the_persons_words(client, bank):
    enable()
    _ask(bank)
    text = client.post(URL, json=_body("fix the failing test in the parser", session="s-3")).json()["additionalContext"]
    assert recall_text.is_injection(text)


def test_nothing_is_written_to_state_or_the_bank(client, bank):
    enable()
    _ask(bank)
    before = {p.name for p in bank.rglob("*") if p.is_file()}
    client.post(URL, json=_body(None, event="session_start"))
    assert {p.name for p in bank.rglob("*") if p.is_file()} == before
    assert "reading queue" not in (bank / "_state.md").read_text()


# --- remote ------------------------------------------------------------------------


def _handshake(bank, scopes):
    runtime = RemoteRuntime(memory_path=lambda: bank, post=lambda p, d: {}, sleep_running=lambda: False)
    connector = catalog.Connector(id="aaaaaaaa", label="Phone", app="claude", scopes=frozenset(scopes),
                                  created_at="2026-09-01T00:00:00+00:00")
    return runtime.call(connector, "cicada_handshake", {})[0]


def test_a_remote_handshake_says_links_wait_only_to_a_connection_that_can_read_them(bank):
    enable()
    _ask(bank)
    both = _handshake(bank, {"read", "record"})
    assert recall_text.reading_line(1) in both and "cicada_record_read(url, outcome, summary)" in both
    read_only = _handshake(bank, {"read"})
    assert recall_text.reading_line(1, record=False) in read_only and "cicada_record_read" not in read_only
    assert "reading queue" not in _handshake(bank, {"record"}), "no queue tool, no queue sentence"


def test_a_remote_handshake_is_quiet_when_off_or_nothing_waits(bank):
    assert "reading queue" not in _handshake(bank, {"read", "record"})
    enable()
    assert "reading queue" not in _handshake(bank, {"read", "record"})


def test_the_remote_primer_promises_only_what_the_tools_will_do(bank):
    from api.services import handshake

    both = handshake._remote_reading_item(frozenset({"cicada_reading_queue", "cicada_record_read"}))
    assert "record `needs_login` and move on" in both
    record_only = handshake._remote_reading_item(frozenset({"cicada_record_read"}))
    assert "Ask an agent" in record_only and "only mentioned in chat is refused" in record_only
    assert "when the person gives you a link" not in record_only
    queue_only = handshake._remote_reading_item(frozenset({"cicada_reading_queue"}))
    assert "stop and tell the person" in queue_only and "needs_login" not in queue_only


def test_a_running_session_is_re_told_for_a_new_ask_but_not_for_every_saved_wall_page(client, bank):
    for i in range(3):
        put_page(bank, f"w{i}", f"https://www.linkedin.com/in/w{i}")
    enable(sites=("linkedin",))
    from api.services import bank_index

    bank_index.files(bank, "entities")  # warm: the hook counts the derived part only from a warm cache
    body = lambda: _body("fix the failing test in the parser", session="s-derived")  # noqa: E731
    first = client.post(URL, json=body()).json()
    assert recall_text.reading_line(3) in first["additionalContext"], "derived pages count once the cache is warm"
    put_page(bank, "w3", "https://www.linkedin.com/in/w3")
    bank_index.files(bank, "entities")
    assert client.post(URL, json=body()).json()["additionalContext"] is None, "one more saved page: no repeat"
    _ask(bank)
    bank_index.files(bank, "entities")
    again = client.post(URL, json=body()).json()
    assert recall_text.reading_line(5) in again["additionalContext"], "a new ask is always told"
    for i in range(4, 16):
        put_page(bank, f"w{i}", f"https://www.linkedin.com/in/w{i}")
    bank_index.files(bank, "entities")
    big = client.post(URL, json=body()).json()
    assert big["additionalContext"] is not None, "growth of ten or more is told"


def test_the_hook_never_parses_a_cold_bank(client, bank, monkeypatch):
    put_page(bank, "w", "https://www.linkedin.com/in/w")
    enable(sites=("linkedin",))
    from api.services import bank_index, reading_walls

    bank_index.invalidate(bank)
    monkeypatch.setattr(reading_walls, "scan", lambda *a, **k: (_ for _ in ()).throw(AssertionError("cold scan")))
    assert hook_recall.waiting_links(bank) == 0


def test_a_cold_cache_never_reads_as_drained(client, bank):
    """A bank write makes the page cache cold; the derived count is then unknown, not zero, so a running
    session is neither re-told nor reset while the cache warms in the background."""
    for i in range(4):
        put_page(bank, f"w{i}", f"https://www.linkedin.com/in/w{i}")
    enable(sites=("linkedin",))
    from api.services import bank_index

    bank_index.files(bank, "entities")
    body = lambda: _body("fix the failing test in the parser", session="s-cold")  # noqa: E731
    assert recall_text.reading_line(4) in client.post(URL, json=body()).json()["additionalContext"]
    bank_index.invalidate(bank)  # e.g. a Sleep rewrite
    assert client.post(URL, json=body()).json()["additionalContext"] is None
    assert hook_recall.READING_SEEN.told("s-cold") == 4, "the higher count is remembered, not reset to the cold 0"
