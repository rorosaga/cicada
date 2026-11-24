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
    assert recall_text.reading_line(1, record=True) in both and "cicada_record_read(url, outcome, summary)" in both
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


def test_a_slow_wall_scan_drops_only_the_reading_sentence_and_finishes_in_the_background(client, bank, monkeypatch):
    """After a Sleep rewrite a warm cache can still hold many page bodies not yet judged. The hook's
    budget bounds that parse: past the deadline the derived count is unknown (the reading sentence is
    dropped), the page note is untouched, and a background scan finishes the judging."""
    import threading
    import time

    from api.services import bank_index, reading_queue, reading_walls

    for i in range(30):
        put_page(bank, f"w{i}", f"https://articles.paperfold.io/post/{i}", fetch_status="blocked")
    enable(sites=("paperfold.io",))
    bank_index.invalidate(bank)
    bank_index.files(bank, "entities")
    reading_walls.reset_memo()
    real = reading_walls._holds_words
    slow = {"on": True}

    def _slow(*a, **k):
        if slow["on"]:
            time.sleep(0.05)
        return real(*a, **k)

    monkeypatch.setattr(reading_walls, "_holds_words", _slow)
    inj = hook_recall.Injection("From Cicada\nA page note.", ["alpha-project"], "injected", None)
    t0 = time.monotonic()
    out = hook_recall.with_reading_note(inj, bank, "s-slow", event="user_prompt_submit", deadline=t0 + 0.2)
    assert time.monotonic() - t0 < 0.6, "the count gave up at the deadline instead of judging all 30 pages"
    assert out.text == inj.text and out.injected == inj.injected, "the page note is untouched; no sentence"
    assert reading_queue.counts(bank, warm_only=True, deadline=time.monotonic() - 1)[1] is None
    for th in [th for th in threading.enumerate() if th.name == "reading-warm"]:
        th.join(10)
    slow["on"] = False
    assert reading_queue.counts(bank, warm_only=True, deadline=time.monotonic() + 5)[1] == 30, \
        "the background scan judged every page; the next prompt counts them"


# --- G245 (track C1): the line names the list that is due, to a harness that has read one, and repeats on a floor -----


def _list_on(*keys):
    reading_settings.update(saved_lists_={k: True for k in keys})


def _driver(bank, harness="claude-code"):
    from api.services import saved_lists

    saved_lists.note_reader(bank, harness)


def _prompt(client, session="s-l", harness="claude-code"):
    return client.post(URL, json=_body("fix the failing test in the parser", session=session, harness=harness)).json()


def test_a_due_list_is_named_in_the_persons_terms_to_a_harness_that_read_a_list_before(client, bank):
    enable()
    _list_on("x")
    _driver(bank)
    start = client.post(URL, json=_body(None, event="session_start", session="s-l")).json()
    text = start["additionalContext"]
    assert "your X Bookmarks is due to be read in the person's own signed-in browser" in text
    assert "links are waiting" not in text and "link is waiting" not in text, "a list is not counted as a link"
    assert "x.com" not in text, "a site's and a list's name, never an address"


def test_a_harness_with_no_recorded_list_read_hears_nothing_of_the_lists(client, bank):
    enable()
    _list_on("x")
    start = client.post(URL, json=_body(None, event="session_start", session="s-l")).json()
    assert "due to be read" not in (start["additionalContext"] or "")
    assert "waiting in Cicada's reading queue" not in (start["additionalContext"] or "")
    _driver(bank, "codex")           # another harness recorded one: the line is for that harness only
    assert "due to be read" not in (_prompt(client, "s-l2")["additionalContext"] or "")
    assert "your X Bookmarks" in (_prompt(client, "s-l3", harness="codex")["additionalContext"] or "")


def test_the_links_a_person_asked_about_still_reach_every_harness(client, bank):
    enable()
    _list_on("x")
    _ask(bank)
    start = client.post(URL, json=_body(None, event="session_start", session="s-l")).json()
    assert recall_text.reading_line(1) in start["additionalContext"]
    assert "due to be read" not in start["additionalContext"]


def test_a_list_that_stays_due_repeats_on_a_later_prompt_only_after_the_floor(client, bank, monkeypatch):
    enable()
    _list_on("x")
    _driver(bank)
    clock = {"t": 1000.0}
    monkeypatch.setattr(hook_recall, "_mono", lambda: clock["t"])
    client.post(URL, json=_body(None, event="session_start", session="s-l"))
    for _ in range(5):                       # prompt after prompt inside the floor: nothing
        clock["t"] += 60
        assert _prompt(client)["additionalContext"] is None
    clock["t"] += hook_recall.READING_SEEN.LIST_REPEAT_S
    again = _prompt(client)
    assert "your X Bookmarks" in again["additionalContext"] and again["reason"] == "reading"
    clock["t"] += 60
    assert _prompt(client)["additionalContext"] is None, "said again, so the floor starts over"


def test_a_list_that_was_read_stops_the_line_and_the_next_one_due_is_said_at_once(client, bank, monkeypatch):
    from api.services import saved_lists

    enable()
    _list_on("x", "instagram")
    _driver(bank)
    clock = {"t": 1000.0}
    monkeypatch.setattr(hook_recall, "_mono", lambda: clock["t"])
    client.post(URL, json=_body(None, event="session_start", session="s-l"))      # X is due first (table order)
    saved_lists.note(bank, "x", "read", items=3)                                  # read: Instagram is due now
    clock["t"] += 30
    nxt = _prompt(client)
    assert "your Instagram Saved" in nxt["additionalContext"] and "your X Bookmarks" not in nxt["additionalContext"]


def test_the_list_line_stays_inside_the_notes_budget_and_is_neutral(client, bank):
    from api.services import handshake

    enable()
    _list_on("x")
    _driver(bank)
    start = client.post(URL, json=_body(None, event="session_start", session="s-l")).json()
    assert len(start["additionalContext"]) // 4 <= handshake.MAX_TOKENS
    for lists in (("X Bookmarks",), ("X Bookmarks", "YouTube Watch later"), ("A", "B", "C")):
        for waiting in (0, 1, 4):
            assert len(recall_text.reading_line(waiting, lists=lists)) < 600


def test_a_recorded_read_is_what_makes_a_harness_a_driver(bank):
    from api.services import saved_lists

    assert saved_lists.readers(bank) == frozenset()
    saved_lists.note_reader(bank, "Claude-Code")
    saved_lists.note_reader(bank, "a person's name/with slash")   # not a harness name: ignored
    saved_lists.note_reader(bank, "")
    assert saved_lists.readers(bank) == frozenset({"claude-code"})


def test_an_agents_recorded_list_read_makes_it_a_driver_and_a_refused_one_does_not(bank):
    from _stdio_server import stdio_server
    from api.services import saved_lists

    srv = stdio_server()
    enable()
    srv.SESSION = srv.SessionIdentity("ses_2026-10-06_c0ffee00", "claude-code", None)
    srv.get_memory_path = lambda: bank
    refused = srv.handle_tool("cicada_record_saved_list", {"platform": "x", "outcome": "read", "items": []})
    assert "Not recorded" in refused and saved_lists.readers(bank) == frozenset(), "the list was never turned on"
    _list_on("x")
    out = srv.handle_tool("cicada_record_saved_list", {"platform": "x", "outcome": "read", "items": []})
    assert "empty" in out or "Recorded" in out, out
    assert "claude-code" in saved_lists.readers(bank)
