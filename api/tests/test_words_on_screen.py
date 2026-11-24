"""What Cicada SAYS about a save (ruling 80, owner 2026-11-24, G246: "if i save it already has a reason").

Sleep reads a save, so every sentence shown to a person or returned to an agent says what Cicada did or will do with it, in
plain words, and none of Cicada's own words for its parts ("lookup", "indexed", "index-only", "lean", "its turn") reach
either: the owner asked "What even is lookup?". The night's number is the one constant (``history_index.SAVES_PER_DAY``),
never written twice. No field, route or ETag shape is renamed. Synthetic banks, placeholder titles and example.com links.
"""
from __future__ import annotations

import json

import pytest

from _synthetic_bank import _bank
from drain_harness import settings

from api.services import (bank_index, history_index, markdown_parser, media_ingestor, mcp_tools, recall_text,
                          saved_lookup, saved_words, search_index, source_overview, source_streams)
from api.services.media_ingestor import MediaMeta, PreparedItem, RawItem

#: The words that name Cicada's parts, never the person's or an agent's.
INTERNAL = ("lookup", "indexed", "index-only", "index only", "lean ", "its turn", "findable")
WORDS = "A page about the thing it is titled"
NIGHT = 37     # a number that is nobody's default: it must come from the constant, not from a copy


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    bank_index.invalidate()
    monkeypatch.setattr(history_index, "SAVES_PER_DAY", NIGHT)
    yield
    bank_index.invalidate()


def _save(memory, url, title, *, origin="chrome-bookmark", idx=None, description=WORDS, bulk=False,
          media_type="bookmark", **kw):
    item = RawItem(url=url, title=title, origin=origin, **kw)
    meta = MediaMeta(title=title, description=description, site="example.com", media_type=media_type)
    res = media_ingestor.write_prepared(PreparedItem(item, meta), memory, idx if idx is not None else {}, bulk=bulk)
    bank_index.invalidate()
    return res.episode_id, res.media_entity_id


def _read(memory, episode_id):
    path = memory / "episodes" / f"{episode_id}.md"
    parsed = markdown_parser.parse(path)
    parsed.frontmatter.update(processed=True, processed_by="sleep")
    markdown_parser.write(path, parsed.frontmatter, parsed.body)
    bank_index.invalidate()


@pytest.fixture
def states(tmp_path):
    """One save of each state, by its record: waiting, the older pile, nothing to read, read, and another service's."""
    memory = _bank(tmp_path)
    idx: dict = {}
    out = {}
    out["waiting"] = _save(memory, "https://example.com/waiting", "Quokka habitat restoration guide", idx=idx)
    out["pile"] = _save(memory, "https://example.com/pile", "Lichen taxonomy field handbook", idx=idx, bulk=True)
    out["no-words"] = _save(memory, "https://example.com/empty", "Basalt column geology notes", idx=idx,
                            description="", media_type="youtube")
    out["read"] = _save(memory, "https://example.com/read", "Zeppelin mooring mast history", idx=idx)
    _read(memory, out["read"][0])
    out["record"] = _save(memory, "https://github.com/alpha-org/alpha-project", "Alpha project repository", idx=idx,
                          origin="github-owned", media_type="bookmark")
    search_index.refresh(memory)
    for state, (episode, _page) in out.items():
        assert history_index.save_state(markdown_parser.parse(memory / "episodes" / f"{episode}.md").frontmatter) == state
    return memory, out


def _no_internal_word(text: str, where: str = "") -> None:
    for word in INTERNAL:
        assert word not in text.lower(), f"{where} says {word!r}: {text!r}"


# ---- the one place the sentences live ---------------------------------------------------------------------------------


def test_the_night_s_number_is_the_constant_in_every_sentence_that_has_one():
    for text in (saved_words.clause(), saved_words.pile_line(250), saved_words.about("pile"), saved_words.saved_heading(),
                 saved_words.note_footer(), saved_words.recorded_posts()):
        assert f"about {NIGHT}" in text.replace(",", ""), text
    assert "100" not in saved_words.pile_line(250), "no second copy of the number"
    assert saved_words.pile_line(1).startswith("1 save not read yet.")
    assert saved_words.pile_line(2).startswith("2 saves not read yet.")


def test_every_sentence_the_module_can_return_is_plain():
    every = [saved_words.clause(), saved_words.pile_line(3), saved_words.saved_heading(), saved_words.note_footer(),
             saved_words.ask_heading(), saved_words.recorded_posts(), saved_words.NOT_SAVED,
             saved_words.not_a_save("a day of the person's watch history"), recall_text.SAVED_HEADER]
    for state in ("waiting", "pile", "no-words", "read", "record", None):
        every += [saved_words.about(state), saved_words.tag(state), saved_words.link_suffix(state),
                  saved_words.head_line(state), saved_words.by_id(state, "A title", " https://example.com/x")]
    for text in every:
        _no_internal_word(text)


def test_what_a_person_did_not_save_says_it_is_kept_never_read_and_why():
    line = saved_words.not_a_save("a day of the person's watch history")
    assert "kept, never read" in line and "did not save it" in line


# ---- an agent reads a save by its id ----------------------------------------------------------------------------------


def _by_id(memory, episode_id):
    ctx = mcp_tools.ToolContext(memory_path=lambda: memory, session_id="s", harness="claude-code")
    return str(mcp_tools.sources(ctx, episode_id))


def test_an_agent_reading_a_save_by_id_is_told_where_it_stands_and_when_it_is_read(states):
    memory, out = states
    pile = _by_id(memory, out["pile"][0])
    assert "not read yet" in pile and f"about {NIGHT} saves a night, newest first" in pile
    assert "talks about it" in pile and "https://example.com/pile" in pile
    waiting = _by_id(memory, out["waiting"][0])
    assert "Sleep reads it at its next run" in waiting
    empty = _by_id(memory, out["no-words"][0])
    assert "nothing to read yet" in empty and "talks about it or their own agent opens it" in empty
    read = _by_id(memory, out["read"][0])
    assert "Sleep reads it" not in read and "not read yet" not in read.lower(), "a read save is an ordinary item"
    record = _by_id(memory, out["record"][0])
    assert "kept, never read" in record and "did not save it" in record
    for text in (pile, waiting, empty, read, record):
        _no_internal_word(text, "by id")


def test_a_day_of_watch_history_says_kept_never_read_and_why(tmp_path):
    memory = _bank(tmp_path)
    markdown_parser.write(memory / "episodes" / "ep_2026-11-01_001.md",
                          {"id": "ep_2026-11-01_001", "source": "watch-history", "source_id": "watch-history:2026-11-01",
                           "timestamp": "2026-11-01T10:00:00+00:00", "processed": True, "processed_by": "index"}, "x")
    bank_index.invalidate()
    text = _by_id(memory, "ep_2026-11-01_001")
    assert "kept, never read: the person did not save it" in text
    _no_internal_word(text)


# ---- recall, Ask and the hook's note ----------------------------------------------------------------------------------


def test_a_line_about_a_save_says_whether_sleep_has_read_it(states):
    memory, out = states
    want = {"quokka habitat restoration": "not read yet", "lichen taxonomy field": "not read yet",
            "basalt column geology": "nothing to read yet", "zeppelin mooring mast": None}
    for query, tag in want.items():
        [hit] = saved_lookup.find(memory, query, min_shared=1)
        line = saved_lookup.line(hit)
        if tag:
            assert tag in line, line
        else:
            assert "not read yet" not in line and "nothing to read yet" not in line, f"a read save is ordinary: {line}"
        _no_internal_word(line)


def test_recall_ask_and_the_hook_say_the_same_true_thing(states):
    memory, _ = states
    heading = mcp_tools.saved_heading()
    assert f"about {NIGHT} saves a night" in heading and "not read yet" in heading
    assert "nobody has read" not in heading and "no reason given" not in heading
    assert "not read yet" in recall_text.SAVED_HEADER and "nobody has read" not in recall_text.SAVED_HEADER
    assert f"about {NIGHT} saves a night" in saved_words.note_footer()
    ask = saved_words.ask_heading()
    assert "marked not read yet" in ask and "nobody has read" not in ask and "no reason given" not in ask


def test_the_link_line_of_a_page_in_recall_says_not_read_yet_only_when_it_is_not(states):
    memory, out = states
    entities = memory / "entities"
    for state, expected in (("pile", True), ("waiting", True), ("no-words", True), ("read", False)):
        page = out[state][1]
        text = mcp_tools._render_entity_summary(entities, {"entity_id": page}, ranked_ids=frozenset(), more_call=None)
        link = next(line for line in text.splitlines() if line.startswith("Link:"))
        assert (("not read yet" in link) or ("nothing to read yet" in link)) is expected, (state, link)
        assert "nobody has read" not in link and "no reason given" not in link


# ---- the record tools' replies ---------------------------------------------------------------------------------------


def test_the_reply_to_a_saved_posts_record_says_sleep_reads_them_and_when():
    said = saved_words.recorded_posts()
    assert "Sleep" in said and f"about {NIGHT} saves a night" in said
    _no_internal_word(said)
    source = open(mcp_tools.__file__).read()
    assert "kept for lookup" not in source and "never read by a model" not in source


def test_the_tool_descriptions_about_saves_carry_none_of_the_internal_words():
    import _stdio_server

    tools = _stdio_server.stdio_server().TOOLS
    for tool in tools:
        text = json.dumps(tool).lower()
        for word in ("lookup", "indexed", "index-only", "its turn", "never read by a model", "kept for lookup"):
            assert word not in text, f"{tool.get('name')} says {word!r}"
    saved = [t for t in tools if t["name"] in ("cicada_record_saved_list", "cicada_record_substack_list")]
    assert len(saved) == 2 and all("Sleep reads" in t["description"] or "read by Sleep" in t["description"] for t in saved)


# ---- the Sleep page's line, the Sources page's row words -------------------------------------------------------------


def _client(memory):
    from fastapi.testclient import TestClient

    from api import main
    from api.config import get_settings

    main.app.dependency_overrides[get_settings] = lambda: settings(memory)
    return TestClient(main.app), main


def test_the_sleep_queue_counts_the_older_pile_and_says_how_many_a_night(states):
    memory, out = states
    client, main = _client(memory)
    try:
        body = client.get("/sleep/queue").json()
        kept = client.get("/sleep/kept").json()
    finally:
        main.app.dependency_overrides.clear()
    assert body["kept"] == 1 == kept["total"], "the pile alone: not a save waiting tonight, not a record"
    assert body["keptPerNight"] == NIGHT
    assert out["waiting"][0] in {i["id"] for i in body["items"]}, "a save waiting for tonight is a row like any item"
    assert out["pile"][0] not in {i["id"] for i in body["items"]}
    assert [i["id"] for i in kept["items"]] == [] and [s["origin"] for s in kept["sources"]] == ["chrome-bookmark"]


def test_a_posts_from_a_saved_list_in_the_pile_are_counted_too(tmp_path):
    memory = _bank(tmp_path)
    idx: dict = {}
    _save(memory, "https://x.com/alpha_user/status/100000000000000001", "A post", idx=idx, origin="x-bookmarks",
          folder="Bookmarks", bulk=True)
    _save(memory, "https://example.com/pile", "A bookmark", idx=idx, bulk=True)
    client, main = _client(memory)
    try:
        assert client.get("/sleep/queue").json()["kept"] == 2
    finally:
        main.app.dependency_overrides.clear()


def test_a_source_says_how_many_of_its_saves_are_not_read_yet_and_the_pace(states):
    memory, _ = states
    rows = source_overview.build_overview(memory, channels=[])
    row = next(r for r in rows if "chrome-bookmark" in r["origins"])
    assert row["kept"] == 1 and row["kept_per_night"] == NIGHT
    assert source_overview.SHAPE == "overview-v19", "no shape renamed: another client reads it"


def _depth(memory, page, url, episode):
    rows = [{"id": page, "kind": "media", "_url": url, "_episode": episode}]
    pages = {page: {"origin": "x-bookmarks"}}
    return source_streams.row_fields(memory, rows, pages, lambda row: None)[page]["depth"]


def test_a_saved_list_row_has_a_word_for_every_state_a_save_can_be_in(tmp_path):
    memory = _bank(tmp_path)
    idx: dict = {}
    kw = {"origin": "x-bookmarks", "folder": "Bookmarks"}
    waiting = _save(memory, "https://x.com/a/status/100000000000000001", "Waiting post", idx=idx, **kw)
    pile = _save(memory, "https://x.com/a/status/100000000000000002", "Older post", idx=idx, bulk=True, **kw)
    empty = _save(memory, "https://x.com/a/status/100000000000000003", "Post by @a", idx=idx, description="", **kw)
    done = _save(memory, "https://x.com/a/status/100000000000000004", "Read post", idx=idx, **kw)
    _read(memory, done[0])
    for (episode, page), url, want in ((waiting, "https://x.com/a/status/100000000000000001", "kept"),
                                       (pile, "https://x.com/a/status/100000000000000002", "kept"),
                                       (empty, "https://x.com/a/status/100000000000000003", "empty"),
                                       (done, "https://x.com/a/status/100000000000000004", "read")):
        assert _depth(memory, page, url, episode) == want, (url, want)


def test_a_saved_lists_stream_is_read_by_sleep_and_a_stream_you_did_not_save_is_kept_never_read():
    streams = {s.id: s for group in source_streams.groups() for s in group.specs}
    for sid in ("x.bookmarks", "x.likes", "youtube.watch_later", "github.stars"):
        if sid in streams:
            assert source_streams._depth(streams[sid]) == "read", sid
    for sid in ("youtube.history", "github.repositories", "x.following", "linkedin.connections", "browser:safari.icloud-tabs"):
        if sid in streams:
            assert source_streams._depth(streams[sid]) == "index", sid
    assert any(s in streams for s in ("x.bookmarks", "x.likes")), "the registry names the lists these tests read"


# ---- no field, route or shape renamed ---------------------------------------------------------------------------------


def test_nothing_the_other_clients_read_was_renamed():
    from api.models.schemas import SleepKept, SleepQueueResponse, SourceOverview
    from api.routers import sleep

    for model, names in ((SleepQueueResponse, {"total", "offset", "items", "kept"}), (SleepKept, {"total", "sources", "items"}),
                         (SourceOverview, {"waiting", "kept", "faces", "intent"})):
        assert names <= set(model.model_fields), model
    assert sleep.KEPT_SHAPE == "kept-1" and sleep.EPISODES_SHAPE
    from api.services import channel_items

    assert channel_items.SHAPE == "g161-25"


def test_the_docs_say_what_the_changed_fields_mean_now():
    from api.models.schemas import SourceOverview

    source = open(__import__("api.models.schemas", fromlist=["x"]).__file__).read()
    assert source.count("Ruling 80 (meaning changed from ruling 62's \"kept for lookup\")") == 2, "both `kept` fields say so"
    assert SourceOverview.model_fields["kept_per_night"].default == 0


# ---- the same words, outside the saves (G245/G246 leftovers) ---------------------------------------------------------

#: Files whose sentences reach a person or an agent and once said "lookup" for a web check or for what Cicada keeps.
_SENTENCE_FILES = ("web_settle.py", "public_handle.py", "mcp_tools.py", "watch_history.py", "page_blocks.py")
_HOUSE_WORDS = ("lookup", "look up", "index-only", "indexed", "lean read")


def _shown_strings(path):
    """Every string constant of a module that is not a docstring: what the code can say, never what it explains."""
    import ast

    tree = ast.parse(open(path).read())
    docs = {id(n.body[0].value) for n in ast.walk(tree)
            if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body
            and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
            yield node.lineno, node.value


def test_web_check_and_book_and_citation_sentences_use_no_house_word():
    import os

    from api import services

    root = os.path.dirname(services.__file__)
    for name in _SENTENCE_FILES:
        for line, text in _shown_strings(os.path.join(root, name)):
            lowered = text.lower()
            if " " not in text.strip() or "_lookup" in lowered:      # an identifier, a key or an env name, not a sentence
                continue
            for word in _HOUSE_WORDS:
                assert word not in lowered, f"{name}:{line} says {word!r}: {text[:90]!r}"


def test_the_refusals_about_a_web_check_say_a_web_check():
    from api.services import public_handle, web_settle

    source = open(web_settle.__file__).read() + open(public_handle.__file__).read() + open(mcp_tools.__file__).read()
    assert source.count("a web check may") >= 5
    assert "A web check settles a pair only with how the two are related" in source
    assert "the book source could not be reached" in source and "the book's details arrive" in source


def test_what_a_watched_day_and_a_citation_count_say_is_plain():
    from api.services import page_blocks, watch_history

    assert "a record of what was watched, not a conversation" in open(watch_history.__file__).read()
    assert "from the web," in open(page_blocks.__file__).read()


def test_the_traces_page_says_kept_to_search_never_to_look_up():
    import pathlib

    swift = pathlib.Path(__file__).resolve().parents[2] / "app/CicadaApp/Sources/CicadaApp/Theme/Copy+Traces.swift"
    text = swift.read_text().lower()
    for word in ("to look up", "lookup", "indexed", "index-only"):
        assert word not in text, word
    assert "you and your agent can search" in text and "kept to search, never read by a model" in text
