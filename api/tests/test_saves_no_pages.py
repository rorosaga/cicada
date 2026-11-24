"""Saves alone make no page and no mention; a saved public link's page is read when the save is (G245, ruling 80).

The owner, 2026-11-24: "if i save it already has a reason", and saves must "not blote cicada memory with shit". So every
save is read, and what keeps a pile of saves from becoming a pile of pages is here:

* saves with no words of the person's are ONE source for the 2+ rule, however many (``promotion.conversation_keys``);
* such a save is no mention (``episode_time``): it starts no page's clock and refreshes none;
* a page only saves (or a tab group) made is quiet;
* a save's page links only to a page the save names in full, at most five (``media_ingestor.inject_media_edges``);
* the public page behind a read save is read by the existing path, newest first, behind one constant
  (``link_enrichment.READ_SAVED_PAGES``).

Synthetic text only (`alpha-tool`, `alex-example`, `example.com`).
"""
from __future__ import annotations

import asyncio
import json
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from api.config import Settings
from api.services import (bank_index, conflict_resolver as cr, entity_extractor as ex, entity_resolver as er,
                          episode_time, history_index, link_enrichment, markdown_parser, media_ingestor, promotion,
                          providers, quiet_pages, saved_reading, sleep_cycle)

TODAY = date(2026, 11, 24)
CYCLE_NOW = datetime(2026, 11, 24, 3, 0)

SAVE_A, SAVE_B, SAVE_C = "ep_2026-11-20_001", "ep_2026-11-20_002", "ep_2026-11-20_003"
TALK = "ep_2026-10-01_001"

SAVE_FM = {"source": "url", "origin": "chrome-bookmark", "url": "https://example.com/a", "media_entity_id": "media-a",
           "timestamp": "2026-11-20T10:00:00+00:00"}
#: A save Sleep reads with no words of his: today only one he talked about (`read_asked`) waits for a model; once every
#: save is read (Track 1) a plain one does too, and this is what it is.
WAITING = {**SAVE_FM, history_index.WOKEN_KEY: {"why": "title", "at": "2026-11-21"}}
POST = "# A post\n\n**Source:** url\n**URL:** https://example.com/a\n**Saved:** 2026-11-20\n\n## Description\nalpha-tool is a synthetic build tool.\n"


class _CycleDay(date):
    @classmethod
    def today(cls):
        return cls(CYCLE_NOW.year, CYCLE_NOW.month, CYCLE_NOW.day)


def _bank(tmp_path: Path, *episodes) -> Path:
    memory = tmp_path / "synthetic-bank"
    for sub in ("episodes", "entities", "sources", "inbox"):
        (memory / sub).mkdir(parents=True, exist_ok=True)
    for eid, fm, body in episodes:
        markdown_parser.write(memory / "episodes" / f"{eid}.md", {"id": eid, "processed": False, **fm}, body)
    bank_index.invalidate()
    return memory


# --------------------------------------------------------------------------- the 2+ rule counts saves as one source


def test_saves_with_no_words_of_his_are_one_source_however_many(tmp_path):
    memory = _bank(tmp_path, (SAVE_A, SAVE_FM, POST), (SAVE_B, {**SAVE_FM, "url": "https://example.com/b"}, POST),
                   (SAVE_C, {**SAVE_FM, "origin": "x-likes", "url": "https://x.example.com/c"}, POST))
    assert promotion.conversation_keys([SAVE_A], memory) == {promotion.SAVES_KEY}
    assert promotion.conversation_keys([SAVE_A, SAVE_B, SAVE_C], memory) == {promotion.SAVES_KEY}


def test_a_save_with_his_own_words_counts_as_its_own_conversation(tmp_path):
    memory = _bank(
        tmp_path, (SAVE_A, SAVE_FM, POST),
        (SAVE_B, {**SAVE_FM, "has_note": True}, POST + "\n## Saved because\nI want to try it for the build.\n"),
        (SAVE_C, {**SAVE_FM, "saved_why": {"reasons": ["read_later"], "at": "2026-11-21T09:00:00+00:00"}}, POST),
        ("ep_2026-11-20_004", {**SAVE_FM, "readable_by_folder": {"at": "2026-11-21", "folders": ["Build"]}}, POST))
    keys = promotion.conversation_keys([SAVE_A, SAVE_B, SAVE_C, "ep_2026-11-20_004"], memory)
    assert keys == {promotion.SAVES_KEY, SAVE_B, SAVE_C, "ep_2026-11-20_004"}


def test_only_saves_are_pooled(tmp_path):
    """A conversation, a feed item and a save the person read-asked about keep the key they always had."""
    memory = _bank(
        tmp_path, (SAVE_A, SAVE_FM, POST), (TALK, {"source": "telegram"}, "user: alpha-tool again\n"),
        (SAVE_B, {"source": "article", "origin": "rss", "published_at": "2026-11-01T08:00:00+00:00",
                  "url": "https://example.com/feed"}, POST),
        (SAVE_C, {**SAVE_FM, history_index.WOKEN_KEY: {"why": "title", "at": "2026-11-21"}}, POST))
    assert promotion.conversation_keys([SAVE_A, TALK], memory) == {promotion.SAVES_KEY, TALK}
    assert promotion.conversation_keys([SAVE_B], memory) == {SAVE_B}      # a feed item keeps ruling 39's own rule
    # Talking about a save is a conversation (its own episode); the save itself still has no words of his.
    assert promotion.conversation_keys([SAVE_C, SAVE_A], memory) == {promotion.SAVES_KEY}


def _model_free(monkeypatch):
    monkeypatch.setattr(er, "SqliteVecIndexer", lambda *a, **k: None)

    async def no_model(*a, **k):
        raise AssertionError("no model call expected")
    monkeypatch.setattr(er, "_llm_judge_same_entity", no_model)


def _resolve(bank, episodes, *, existing=(), threshold=2):
    settings = SimpleNamespace(memory_path=bank, litellm_model="synthetic-model", litellm_disambiguation_model="",
                               sleep_promotion_threshold=threshold)
    extracted = [{"episode_id": eid, "episode_timestamp": ts, "origin": origin, "entities": [
        {"name": "Alpha Tool", "type": "tool", "confidence": 0.9, "source_episode": eid, "description": "A tool.",
         "untimed": untimed, "source_episode_timestamp": None if untimed else ts}], "relationships": []}
        for eid, ts, origin, untimed in episodes]
    out = asyncio.run(er.resolve(extracted, list(existing), settings))
    return [c for c in out["changes"] if c.get("action") == "create" and c.get("id") == "alpha-tool"]


def test_two_saves_naming_one_thing_make_no_page(tmp_path, monkeypatch):
    _model_free(monkeypatch)
    bank = _bank(tmp_path, (SAVE_A, SAVE_FM, POST), (SAVE_B, {**SAVE_FM, "url": "https://example.com/b"}, POST))
    ts = "2026-11-20T10:00:00+00:00"
    assert _resolve(bank, [(SAVE_A, ts, "chrome-bookmark", True), (SAVE_B, ts, "chrome-bookmark", True)]) == []


def test_one_save_and_one_conversation_make_the_page_and_it_keeps_both_sources(tmp_path, monkeypatch):
    _model_free(monkeypatch)
    bank = _bank(tmp_path, (SAVE_A, SAVE_FM, POST), (TALK, {"source": "telegram"}, "user: alpha-tool again\n"))
    (change,) = _resolve(bank, [(SAVE_A, "2026-11-20T10:00:00+00:00", "chrome-bookmark", True),
                                (TALK, "2026-10-01T10:00:00+00:00", "telegram", False)])
    assert set(change["source_episodes"]) == {SAVE_A, TALK}
    assert change["untimed"] is False                       # the conversation is a mention; the save adds none


def test_a_save_with_his_own_reason_counts_as_a_conversation(tmp_path, monkeypatch):
    _model_free(monkeypatch)
    bank = _bank(tmp_path, (SAVE_A, SAVE_FM, POST),
                 (SAVE_B, {**SAVE_FM, "has_note": True, "url": "https://example.com/b"},
                  POST + "\n## Saved because\nI want alpha-tool for the build.\n"))
    ts = "2026-11-20T10:00:00+00:00"
    (change,) = _resolve(bank, [(SAVE_A, ts, "chrome-bookmark", True), (SAVE_B, ts, "chrome-bookmark", False)])
    assert set(change["source_episodes"]) == {SAVE_A, SAVE_B}


# --------------------------------------------------------------------------- his reason is about the save, not about every name in it


def _five_saves_one_with_a_reason(tmp_path, reason: str):
    """Five posts name Alpha Tool; one of them carries his reason, which is about the post."""
    posts = [(f"ep_2026-11-20_{n:03d}", {**SAVE_FM, "url": f"https://example.com/p{n}"}, POST) for n in range(1, 5)]
    posts.append(("ep_2026-11-20_005", {**SAVE_FM, "has_note": True, "url": "https://example.com/p5"},
                  POST + f"\n## Saved because\n{reason}\n"))
    return _bank(tmp_path, *posts), [p[0] for p in posts]


def test_a_reason_on_a_save_is_his_own_source_only_for_what_his_words_name(tmp_path):
    memory, ids = _five_saves_one_with_a_reason(tmp_path, "Reading this for the billing rewrite.")
    reasoned = ids[-1]
    assert promotion.conversation_keys(ids, memory) == {promotion.SAVES_KEY, reasoned}                 # no name to test: as before
    assert promotion.conversation_keys(ids, memory, ["Alpha Tool", "alpha-tool-cli"]) == {promotion.SAVES_KEY}
    memory, ids = _five_saves_one_with_a_reason(tmp_path / "again", "I want alpha-tool for the billing rewrite.")
    # his words name it (spelled with a hyphen, the page is "Alpha Tool"): the save is his own source for it
    assert promotion.conversation_keys(ids, memory, ["Alpha Tool"]) == {promotion.SAVES_KEY, ids[-1]}
    # an alias of the page counts as its name
    memory, ids = _five_saves_one_with_a_reason(tmp_path / "alias", "I want the AT cli for the billing rewrite.")
    assert promotion.conversation_keys(ids, memory, ["Alpha Tool", "AT cli"]) == {promotion.SAVES_KEY, ids[-1]}


def test_a_name_five_saves_carry_makes_no_page_when_the_one_reason_among_them_does_not_name_it(tmp_path, monkeypatch):
    _model_free(monkeypatch)
    memory, ids = _five_saves_one_with_a_reason(tmp_path, "Reading this for the billing rewrite.")
    ts = "2026-11-20T10:00:00+00:00"
    assert _resolve(memory, [(eid, ts, "chrome-bookmark", True) for eid in ids]) == []


def test_a_name_his_reason_names_plus_another_save_makes_the_page(tmp_path, monkeypatch):
    _model_free(monkeypatch)
    memory, ids = _five_saves_one_with_a_reason(tmp_path, "I want Alpha Tool for the billing rewrite.")
    ts = "2026-11-20T10:00:00+00:00"
    (change,) = _resolve(memory, [(eid, ts, "chrome-bookmark", True) for eid in ids])
    assert ids[-1] in change["source_episodes"]


def test_a_name_only_saves_and_a_reason_that_does_not_name_it_carry_is_still_only_the_saves(tmp_path):
    from api.services import saves_bounded

    memory, ids = _five_saves_one_with_a_reason(tmp_path, "Reading this for the billing rewrite.")
    saves = saves_bounded.for_bank(memory)
    assert saves.all_of(ids) is False                                    # no name given: his words make it his
    assert saves.all_of(ids, ["Alpha Tool"]) is True                     # his words do not name it: only saves carried it
    assert saves.all_of(ids, ["billing rewrite"]) is False               # they do
    assert saves.of(ids[-1], ["Alpha Tool"]) is True and saves.of(ids[-1], ["Billing Rewrite"]) is False


# --------------------------------------------------------------------------- a save is no mention


def test_counts_as_activity_says_a_bare_save_is_no_mention_and_a_reason_is():
    bare = {**SAVE_FM}
    assert episode_time.counts_as_activity(bare) is False
    assert episode_time.counts_as_activity({**bare, "has_note": True}) is True
    assert episode_time.counts_as_activity({**bare, "saved_why": {"reasons": ["design"]}}) is True
    assert episode_time.counts_as_activity({**bare, "readable_by_folder": {"folders": ["Build"]}}) is True
    # A conversation, a book's record and a watched day are untouched by the rule.
    assert episode_time.counts_as_activity({"source": "claude-code", "origin": "claude-code"}) is True
    assert episode_time.counts_as_activity({"source": "telegram", "origin": "telegram"}) is True
    assert episode_time.counts_as_activity({**bare, "book": {"highlights": [{"text": "x"}]}}) is True


def test_the_bank_wide_reader_and_the_card_reader_agree(tmp_path):
    """`untimed_ids` (the cache) and `untimed_among` (one awk pass, then a line reader) tell a save the same way — a
    block-valued mark (`saved_why:` then indented lines) counts as present."""
    memory = _bank(
        tmp_path, (SAVE_A, SAVE_FM, POST), (SAVE_B, {**SAVE_FM, "has_note": True, "url": "https://example.com/b"}, POST),
        (SAVE_C, {**SAVE_FM, "saved_why": {"reasons": ["read_later"], "text": "for the build"},
                  "url": "https://example.com/c"}, POST),
        ("ep_2026-11-20_004", {"source": "claude-code", "origin": "claude-code"}, "user: hi\n"),
        ("ep_2026-11-20_005", {**SAVE_FM, "source": "tab-group", "origin": "chrome-tab-group", "url": None,
                               "media_entity_id": None}, "# A group\n"))
    ids = [SAVE_A, SAVE_B, SAVE_C, "ep_2026-11-20_004", "ep_2026-11-20_005"]
    expected = frozenset({SAVE_A, "ep_2026-11-20_005"})
    assert episode_time.untimed_ids(memory) == expected
    episode_time._MEMO.clear()
    assert episode_time.untimed_among(memory, ids) == expected
    with patch.object(episode_time, "_sources", lambda _paths: None):      # awk unavailable: the line reader agrees
        episode_time._MEMO.clear()
        assert episode_time.untimed_among(memory, ids) == expected


def test_sleep_hands_the_marks_of_his_words_to_stage_one(tmp_path):
    memory = _bank(tmp_path, (SAVE_A, WAITING, POST),
                   (SAVE_B, {**SAVE_FM, "has_note": True, "url": "https://example.com/b"}, POST))
    by_id = {e["id"]: e for e in sleep_cycle._get_unprocessed_episodes(memory)}
    assert saved_reading.no_words_of_his(by_id[SAVE_A]) and not saved_reading.no_words_of_his(by_id[SAVE_B])
    assert episode_time.counts_as_activity(by_id[SAVE_A]) is False and episode_time.counts_as_activity(by_id[SAVE_B])


def _extract(episodes):
    async def fake(**kw):
        reply = {"entities": [{"name": "Alpha Tool", "type": "tool", "confidence": 0.7,
                               "summary": "Alpha Tool is a build tool.", "key_facts": ["Alpha Tool is a build tool."]}],
                 "relationships": []}
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(reply)))])

    async def no_sleep(*_a, **_k):
        return None
    with patch.object(providers, "resolve_llm_fn", lambda *a, **k: fake), patch.object(ex.asyncio, "sleep", no_sleep):
        return asyncio.run(ex.extract([dict(e) for e in episodes], Settings(_env_file=None), today=TODAY))


def test_stage_one_marks_a_bare_save_untimed_and_a_save_with_a_reason_timed(tmp_path):
    memory = _bank(tmp_path, (SAVE_A, WAITING, POST),
                   (SAVE_B, {**SAVE_FM, "has_note": True, "url": "https://example.com/b"},
                    POST + "\n## Saved because\nI want alpha-tool for the build.\n"))
    out = _extract(sleep_cycle._get_unprocessed_episodes(memory))
    by_ep = {r["episode_id"]: r["entities"][0] for r in out if r}
    assert by_ep[SAVE_A]["untimed"] is True and by_ep[SAVE_A]["source_episode_day"] is None
    assert not by_ep[SAVE_B].get("untimed") and by_ep[SAVE_B]["source_episode_day"] == "2026-11-20"


@pytest.fixture
def bank(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    _model_free(monkeypatch)
    return memory


def _existing(memory):
    return [{"id": f.stem, "frontmatter": (p := markdown_parser.parse(f)).frontmatter, "body": p.body}
            for f in sorted((memory / "entities").glob("*.md"))]


def _cycle(memory, episodes, *, decay=False):
    """Stage 1, 2 and 3 over ``episodes`` (full Sleep episode dicts) against the bank's pages."""
    settings = SimpleNamespace(memory_path=memory, litellm_model="synthetic-model", litellm_disambiguation_model="",
                               sleep_promotion_threshold=1)
    real = Settings(_env_file=None, llm_mode="byok", litellm_model="synthetic-model")
    resolved = []
    if episodes:
        out = _extract(episodes)
        resolved = asyncio.run(er.resolve([r for r in out if r], _existing(memory), settings))["changes"]

    async def no_synthesis(**_k):
        return None
    with patch.object(cr, "_synthesize_entity_update", no_synthesis), patch.object(cr, "date", _CycleDay):
        changes = asyncio.run(cr.resolve_and_prune(resolved, _existing(memory), real, decay=decay, now=CYCLE_NOW))
        cr.apply_changes(changes, memory)
    bank_index.invalidate()
    return resolved


def _fm(memory, name):
    return markdown_parser.parse(memory / "entities" / f"{name}.md").frontmatter


def test_a_save_neither_starts_nor_refreshes_a_pages_clock(bank):
    page = {"name": "Alpha Tool", "type": "tool", "status": "decaying", "confidence": 0.3, "created": "2025-01-01",
            "last_referenced": "2025-01-01", "decayed_through": "2026-10-01", "source_episodes": ["ep_2025-01-01_001"]}
    markdown_parser.write(bank / "entities" / "alpha-tool.md", page, "## Summary\nA synthetic tool.\n")
    markdown_parser.write(bank / "episodes" / f"{SAVE_A}.md", {"id": SAVE_A, "processed": False, **WAITING}, POST)
    bank_index.invalidate()
    (change,) = _cycle(bank, sleep_cycle._get_unprocessed_episodes(bank))
    assert change["action"] == "update" and change["untimed"] is True
    fm = _fm(bank, "alpha-tool")
    assert str(fm["last_referenced"]) == "2025-01-01" and str(fm["decayed_through"]) == "2026-10-01"
    assert fm["status"] == "decaying" and fm["confidence"] == 0.3        # a stranger's post never revives a page
    assert SAVE_A in fm["source_episodes"]                               # its source is kept all the same


def test_a_page_born_from_a_conversation_and_a_save_is_dated_by_the_conversation(bank):
    markdown_parser.write(bank / "episodes" / f"{TALK}.md",
                          {"id": TALK, "processed": False, "source": "telegram", "origin": "telegram",
                           "timestamp": "2026-10-01T10:00:00+00:00"}, "user: I use alpha-tool for builds.\n")
    markdown_parser.write(bank / "episodes" / f"{SAVE_A}.md", {"id": SAVE_A, "processed": False, **WAITING}, POST)
    bank_index.invalidate()
    (change,) = [c for c in _cycle(bank, sleep_cycle._get_unprocessed_episodes(bank)) if c["id"] == "alpha-tool"]
    assert set(change["source_episodes"]) == {SAVE_A, TALK} and change["untimed"] is False
    fm = _fm(bank, "alpha-tool")
    assert str(fm["last_referenced"]) == "2026-10-01"                    # the save (2026-11-20) is no mention


# --------------------------------------------------------------------------- a page only saves made is quiet


def test_a_page_only_saves_or_a_tab_group_made_is_quiet_until_a_conversation_names_it(tmp_path):
    memory = _bank(tmp_path, (SAVE_A, SAVE_FM, POST),
                   (SAVE_B, {"source": "tab-group", "origin": "chrome-tab-group", "timestamp": "2026-11-20T10:00:00+00:00"},
                    "# Build tabs\n\n- alpha-tool docs\n"),
                   (TALK, {"source": "telegram"}, "user: alpha-tool again\n"))
    for name, episodes in (("from-saves", [SAVE_A]), ("from-group", [SAVE_B]), ("from-both", [SAVE_A, SAVE_B]),
                           ("spoken", [SAVE_A, TALK])):
        markdown_parser.write(memory / "entities" / f"{name}.md",
                              {"name": name, "type": "tool", "status": "active", "source_episodes": episodes},
                              "## Summary\nA synthetic page.\n")
    bank_index.invalidate()
    assert quiet_pages.episode_kind({"source": "tab-group", "origin": "chrome-tab-group"}) == quiet_pages.IMPORT
    assert quiet_pages.page_is_quiet(memory, "from-saves") and quiet_pages.page_is_quiet(memory, "from-group")
    assert quiet_pages.page_is_quiet(memory, "from-both")
    assert not quiet_pages.page_is_quiet(memory, "spoken")


# --------------------------------------------------------------------------- links from a save: only what it names


def _edges(memory) -> set[tuple[str, str]]:
    data = markdown_parser.load_yaml_file(memory / "graph_edges.yaml") or {}
    return {(e["source"], e["target"]) for e in data.get("edges") or []}


def _media(memory, episodes):
    markdown_parser.write(memory / "entities" / "media-a-post.md",
                          {"name": "A post", "type": "media", "status": "active", "source_episodes": episodes,
                           "media": {"url": "https://example.com/a", "media_type": "url"}}, "## Summary\nA post.\n")


def _page(memory, name, *aliases, kind="person"):
    markdown_parser.write(memory / "entities" / f"{name.lower().replace(' ', '-')}.md",
                          {"name": name, "type": kind, "status": "active", "aliases": list(aliases)}, "## Summary\nx\n")


def _changes(memory, episode, *ids):
    return [{"id": i, "action": "update", "source_episodes": [episode], "source_episode": episode} for i in ids]


def test_a_saves_page_links_only_to_pages_the_save_names_in_full(tmp_path):
    body = ("# Notes from a meetup\n\n**Source:** url\n**URL:** https://example.com/sam-example\n\n## Description\n"
            "Sam spoke about builds with Alex Example, who maintains the alpha-tool project (the AT team).\n")
    memory = _bank(tmp_path, (SAVE_A, SAVE_FM, body))
    _page(memory, "Alex Example")
    _page(memory, "Sam Example")                         # "Sam" in the post is a first name, never this page
    _page(memory, "Alpha Tool", "AT team", kind="tool")  # named by an alias
    _page(memory, "Beta Rig", kind="tool")               # resolved from the post by the model, never named in it
    _media(memory, [SAVE_A])
    bank_index.invalidate()
    n = media_ingestor.inject_media_edges(memory, _changes(memory, SAVE_A, "alex-example", "sam-example", "alpha-tool",
                                                           "beta-rig"))
    assert n == 2
    assert _edges(memory) == {("media-a-post", "alex-example"), ("media-a-post", "alpha-tool")}
    # The address of the link is no text: a page whose name only the URL holds is not named.


def test_a_save_links_at_most_five_pages(tmp_path):
    names = [f"Tool {chr(97 + i)}" for i in range(8)]
    body = "# Tools\n\n## Description\n" + ", ".join(names) + ".\n"
    memory = _bank(tmp_path, (SAVE_A, SAVE_FM, body))
    for name in names:
        _page(memory, name, kind="tool")
    _media(memory, [SAVE_A])
    bank_index.invalidate()
    ids = [n.lower().replace(" ", "-") for n in names]
    assert media_ingestor.inject_media_edges(memory, _changes(memory, SAVE_A, *ids)) == saved_reading.MAX_LINKS
    assert len(_edges(memory)) == saved_reading.MAX_LINKS == 5
    # The first five the text names, in its order.
    assert {t for _s, t in _edges(memory)} == set(ids[:5])


def test_a_conversation_about_a_link_keeps_its_links(tmp_path):
    """Only a saved item is held to its own text; a conversation the page rests on is read as it always was."""
    memory = _bank(tmp_path, (TALK, {"source": "telegram"}, "user: the post and beta rig\n"))
    _page(memory, "Beta Rig", kind="tool")
    _media(memory, [TALK])
    bank_index.invalidate()
    assert media_ingestor.inject_media_edges(memory, _changes(memory, TALK, "beta-rig")) == 1


def test_a_name_too_short_to_be_stated_is_not_named():
    pages = {"go": ("Go", []), "ai": ("AI", ["Artificial"]), "alpha-tool": ("Alpha Tool", [])}
    assert saved_reading.named_in_full("Go is a language; AI is everywhere; ALPHA TOOL ships.", pages) == ["alpha-tool"]
    assert saved_reading.named_in_full("Alpha Toolkit is not the tool.", pages) == []      # whole words only


# --------------------------------------------------------------------------- the public page behind a read save


def _media_page(memory, name, episodes, *, saved_at="2026-11-01"):
    markdown_parser.write(
        memory / "entities" / f"{name}.md",
        {"name": name, "type": "media", "status": "active", "source_episodes": episodes, "created": saved_at,
         "media": {"url": f"https://example.com/{name}", "media_type": "url", "saved_at": saved_at}},
        "## Summary\nA page.\n")


def test_lean_pages_are_the_saves_no_model_reads_and_the_switch_restores_the_first_reading(tmp_path, monkeypatch):
    memory = _bank(
        tmp_path,
        (SAVE_A, {**SAVE_FM, "processed": True, "processed_by": history_index.INDEXED_BY}, POST),   # stored, not read
        (SAVE_B, {**SAVE_FM, "url": "https://example.com/b", "processed": True, "processed_by": "sleep"}, POST),   # read
        (SAVE_C, {**SAVE_FM, "url": "https://example.com/c", "has_note": True, "processed": True, "processed_by": "sleep"},
         POST),
        (TALK, {"source": "telegram", "processed": True, "processed_by": "sleep"}, "user: alpha-tool again\n"))
    fm = lambda eps: {"source_episodes": eps}   # noqa: E731
    assert link_enrichment.READ_SAVED_PAGES is True
    assert link_enrichment.lean_page(memory, fm([SAVE_A])) is True       # a save no model reads: no page read, as today
    assert link_enrichment.lean_page(memory, fm([SAVE_B])) is False      # a save Sleep read: its page is read
    assert link_enrichment.lean_page(memory, fm([SAVE_C])) is False
    monkeypatch.setattr(link_enrichment, "READ_SAVED_PAGES", False)
    assert link_enrichment.lean_page(memory, fm([SAVE_A])) is True
    assert link_enrichment.lean_page(memory, fm([SAVE_B])) is True       # off: no words of his, nobody talked about it
    assert link_enrichment.lean_page(memory, fm([SAVE_C])) is False      # his reason is still a reason
    assert link_enrichment.lean_page(memory, fm([SAVE_B, TALK])) is False


def test_a_woken_save_is_never_lean_with_the_switch_off(tmp_path, monkeypatch):
    memory = _bank(tmp_path, (SAVE_A, {**SAVE_FM, "processed": True, "processed_by": "sleep",
                                        history_index.WOKEN_KEY: {"why": "title", "at": "2026-11-21"}}, POST))
    monkeypatch.setattr(link_enrichment, "READ_SAVED_PAGES", False)
    assert link_enrichment.lean_page(memory, {"source_episodes": [SAVE_A]}) is False


def _scan_bank(tmp_path):
    memory = _bank(
        tmp_path,
        (SAVE_A, {**SAVE_FM, "processed": True, "processed_by": history_index.INDEXED_BY}, POST),
        (SAVE_B, {**SAVE_FM, "url": "https://example.com/b", "processed": True, "processed_by": "sleep"}, POST),
        (SAVE_C, {**SAVE_FM, "url": "https://example.com/c", "processed": True, "processed_by": "sleep"}, POST),
        ("ep_2026-11-20_004", {**SAVE_FM, "url": "https://example.com/d", "processed": True, "processed_by": "sleep"}, POST))
    _media_page(memory, "media-not-read", [SAVE_A], saved_at="2026-11-10")
    _media_page(memory, "media-old", [SAVE_B], saved_at="2025-01-05")
    _media_page(memory, "media-new", [SAVE_C], saved_at="2026-11-15")
    _media_page(memory, "media-mid", ["ep_2026-11-20_004"], saved_at="2026-06-01")
    bank_index.invalidate()
    return memory


def test_the_backfill_reads_a_read_save_s_page_newest_first_and_never_a_save_no_model_read(tmp_path, monkeypatch):
    memory = _scan_bank(tmp_path)
    settings = Settings(_env_file=None)
    scan = link_enrichment.scan_backfill(memory, settings, today=date(2026, 11, 24))
    queue = [c.media_id for c in (*scan.reuse, *scan.fetch)]
    assert sorted(queue) == ["media-mid", "media-new", "media-old"]      # the stored-not-read save's page is not here
    assert [c.media_id for c in scan.fetch] == ["media-new", "media-mid", "media-old"]
    monkeypatch.setattr(link_enrichment, "READ_SAVED_PAGES", False)       # one line off: oldest-imported first, none read
    off = link_enrichment.scan_backfill(memory, settings, today=date(2026, 11, 24))
    assert [c.media_id for c in off.fetch] == []


def test_the_backfill_goes_through_the_fetch_gate_and_its_caps(tmp_path):
    """No new path: the page is fetched only by the caller's `fetch_fn` (Sleep passes it behind
    `CICADA_ALLOW_CONNECTOR_FETCH`), at most `link_enrich_backfill_per_cycle` a night, and never a walled site."""
    memory = _scan_bank(tmp_path)
    _media_page(memory, "media-walled", [SAVE_B], saved_at="2026-11-18")
    markdown_parser.write(memory / "entities" / "media-walled.md",
                          {"name": "media-walled", "type": "media", "status": "active", "source_episodes": [SAVE_B],
                           "created": "2026-11-18", "media": {"url": "https://www.linkedin.com/posts/x", "media_type": "url",
                                                              "saved_at": "2026-11-18"}}, "## Summary\nA page.\n")
    bank_index.invalidate()
    fetched: list[str] = []

    async def fetch(url, settings):
        fetched.append(url)
        return link_enrichment.FetchResult("failed:synthetic")

    async def summarize(*a, **k):
        return None
    report = asyncio.run(link_enrichment.backfill(memory, Settings(_env_file=None), limit=2, summarize_fn=summarize,
                                                  fetch_fn=fetch, commit=False, today=date(2026, 11, 24)))
    assert fetched == ["https://example.com/media-new", "https://example.com/media-mid"]   # the cap, newest first
    assert report.selected == 2 and not any("linkedin" in u for u in fetched)
    no_gate = asyncio.run(link_enrichment.backfill(memory, Settings(_env_file=None), limit=2, commit=False,
                                                   today=date(2026, 11, 24)))
    assert no_gate.fetched == 0                                          # no fetch_fn: nothing leaves the machine


def test_the_in_cycle_pass_takes_the_newest_save_when_a_page_has_no_mention(tmp_path):
    memory = _scan_bank(tmp_path)
    picked = [p.stem for p in link_enrichment._candidates(memory, 2)]
    assert picked == ["media-new", "media-mid"]
