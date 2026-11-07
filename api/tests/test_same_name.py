"""G227 — same name, different things: a short qualifier in parentheses, on every surface and door.

Placeholders only: ``<name-a>`` is spelled ``Alpha`` here, one page an IDE and one a program.
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from api.services import bank_index, same_name


def _page(bank: Path, stem: str, name: str, kind: str, summary: str = "", **extra) -> Path:
    (bank / "entities").mkdir(parents=True, exist_ok=True)
    lines = [f"name: {name}", f"type: {kind}", f"status: {extra.pop('status', 'active')}",
             f"created: '{extra.pop('created', '2026-01-05')}'"]
    for key, value in extra.items():
        lines.append(f"{key}: {value}")
    body = f"## Summary\n\n{summary}\n" if summary else ""
    path = bank / "entities" / f"{stem}.md"
    path.write_text("---\n" + "\n".join(lines) + "\n---\n" + body, encoding="utf-8")
    return path


@pytest.fixture
def bank(tmp_path):
    bank_index.invalidate()
    same_name.invalidate()
    _page(tmp_path, "alpha", "Alpha", "tool", "Alpha is an AI-powered IDE built for pair programming.")
    _page(tmp_path, "alpha-program", "Alpha", "project", "Alpha is an accelerator program for early teams.")
    _page(tmp_path, "beta", "Beta", "tool", "Beta is a library.")
    return tmp_path


# --------------------------------------------------------------------------- the one function


def test_described_as_reads_the_head_noun_of_the_first_sentence():
    assert same_name.described_as("Alpha is an AI-powered IDE built for pair programming.", "Alpha") == "IDE"
    assert same_name.described_as("Alpha is an accelerator program for early teams.", "Alpha") == "program"
    assert same_name.described_as("It is a company headquartered in a city.", "Alpha") == "company"
    assert same_name.described_as("Alpha is a messaging and collaboration platform.", "Alpha") == "platform"
    # Never a guess: another shape, another subject, a phrase too long or a word that says nothing.
    assert same_name.described_as("The person uses Alpha every day.", "Alpha") is None
    assert same_name.described_as("Beta is a tool.", "Alpha") is None
    assert same_name.described_as("Alpha is a kind of thing.", "Alpha") is None
    assert same_name.described_as("Alpha is a very big old slow strange machine.", "Alpha") is None
    assert same_name.described_as("", "Alpha") is None


def test_qualifiers_tell_a_shared_title_apart_and_leave_a_lone_title_bare(bank):
    q = same_name.qualifiers(bank)
    assert q == {"alpha": "IDE", "alpha-program": "program"}
    assert same_name.label(bank, "alpha", "Alpha") == "Alpha (IDE)"
    assert same_name.label(bank, "beta", "Beta") == "Beta"
    assert same_name.fields(bank, "beta", "Beta") == {"qualifier": None, "displayName": "Beta"}
    assert sorted(same_name.pages_titled(bank, "  alpha ")) == ["alpha", "alpha-program"]
    assert same_name.pages_titled(bank, "Beta") == []
    # The stored title stays clean: nothing was written.
    assert "name: Alpha\n" in (bank / "entities" / "alpha.md").read_text()


def test_qualifiers_fall_back_to_the_type_word_then_a_date_then_a_number():
    pages = [same_name.Page(id="a", name="Gamma", type="tool"), same_name.Page(id="b", name="Gamma", type="company")]
    assert same_name.derive(pages) == {"a": "tool", "b": "company"}
    pages = [same_name.Page(id="a", name="Gamma", type="tool", created="2025-05-01"),
             same_name.Page(id="b", name="Gamma", type="tool", created="2026-02-01")]
    assert same_name.derive(pages) == {"a": "tool, May 2025", "b": "tool, Feb 2026"}
    pages = [same_name.Page(id="a", name="Gamma", type="tool", created="2025-05-01"),
             same_name.Page(id="b", name="Gamma", type="tool", created="2025-05-09")]
    assert same_name.derive(pages) == {"a": "tool, May 2025, 1", "b": "tool, May 2025, 2"}
    # A saved link by its site, then its path, then its day.
    pages = [same_name.Page(id="m1", name="Home", type="media", site="example.com", path="docs"),
             same_name.Page(id="m2", name="Home", type="media", site="example.com", path="blog"),
             same_name.Page(id="t", name="Home", type="tool")]
    assert same_name.derive(pages) == {"m1": "example.com/docs", "m2": "example.com/blog", "t": "tool"}


def test_a_saved_links_site_needs_a_real_domain():
    assert same_name._site_and_path({"media": {"url": "https://www.example.com/docs/x"}}) == ("example.com", "docs")
    assert same_name._site_and_path({"media": {"url": "chrome-extension://abcdef/popup.html"}}) == ("", "")
    assert same_name._site_and_path({"media": {"url": "http://machine-01:8000/x"}}) == ("", "")


def test_the_map_is_cached_and_moves_when_a_page_is_born_or_dropped(bank):
    same_name.qualifiers(bank)
    built = same_name.builds
    for _ in range(5):
        same_name.qualifiers(bank)
    assert same_name.builds == built          # one stat per call while nothing moved
    time.sleep(0.01)
    _page(bank, "beta-company", "Beta", "company")
    assert same_name.qualifier(bank, "beta") == "library"
    assert same_name.qualifier(bank, "beta-company") == "company"
    # A dropped page no longer shares its title (written as a write is: a rename into the folder).
    time.sleep(0.01)
    tmp = bank / "entities" / ".beta-company.tmp"
    tmp.write_text("---\nname: Beta\ntype: company\nstatus: dropped\n---\n")
    tmp.replace(bank / "entities" / "beta-company.md")
    assert same_name.qualifier(bank, "beta") is None


# --------------------------------------------------------------------------- the app's reads


def test_graph_nodes_carry_the_qualifier_only_when_the_title_is_shared(bank):
    from api.services import graph_builder

    graph = graph_builder.build_graph(bank)
    nodes = {n.id: n for n in graph.nodes}
    assert (nodes["alpha"].qualifier, nodes["alpha"].display_name) == ("IDE", "Alpha (IDE)")
    wire = {n["id"]: n for n in graph.model_dump(by_alias=True)["nodes"]}
    assert wire["alpha-program"]["displayName"] == "Alpha (program)"
    assert "qualifier" not in wire["beta"] and "displayName" not in wire["beta"]


def test_the_graph_build_primes_the_same_map_it_would_build(bank):
    from api.services import graph_builder

    built = dict(same_name.qualifiers(bank))
    same_name.invalidate()
    graph_builder._CACHE.update(key=None, value=None)
    before = same_name.builds
    graph_builder.build_graph(bank)
    assert same_name.builds == before + 1          # primed once from the build's own reads
    assert same_name.qualifiers(bank) == built and same_name.builds == before + 1   # and then held


def test_the_graph_node_shape_moved():
    from api.routers import graph

    assert "+same-name" in graph.NODE_SHAPE and graph.NODE_SHAPE.endswith("+source-links")


def test_the_card_and_search_carry_it(bank, monkeypatch):
    from fastapi.testclient import TestClient

    from api import config, main

    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    config.get_settings.cache_clear()
    try:
        client = TestClient(main.app)
        card = client.get("/entities/alpha-program").json()
        assert card["qualifier"] == "program" and card["displayName"] == "Alpha (program)"
        assert card["name"] == "Alpha"
        lone = client.get("/entities/beta").json()
        assert lone["qualifier"] is None and lone["displayName"] == "Beta"
    finally:
        config.get_settings.cache_clear()

    from api.services import search_service

    hits = search_service.search(bank, "alpha", kinds=("entity",), mode="prefix").results
    shown = {h.id: h.display_name for h in hits}
    assert shown.get("alpha") == "Alpha (IDE)" and shown.get("alpha-program") == "Alpha (program)"
    # Owner 2026-10-29: searching the bare name returns every page with it, each with its qualifier (the app's tag).
    hits = search_service.search(bank, "Alpha", kinds=("entity",), mode="lexical").results
    assert {(h.id, h.name, h.qualifier) for h in hits} >= {("alpha", "Alpha", "IDE"),
                                                           ("alpha-program", "Alpha", "program")}


# --------------------------------------------------------------------------- links by id


def test_the_name_index_never_lets_a_name_take_another_pages_id(tmp_path):
    from api.services.id_utils import build_name_index, link_targets, resolve_entity_id

    _page(tmp_path, "alpha", "Alpha", "tool")
    _page(tmp_path, "media-alpha", "Alpha", "media")
    _page(tmp_path, "gamma", "Gamma", "tool")
    entities = tmp_path / "entities"
    index = build_name_index(entities)
    assert index["alpha"] == "alpha"                      # the page's own id wins its key
    assert resolve_entity_id(entities, "alpha", index) == "alpha"
    assert resolve_entity_id(entities, "Alpha", index) is None     # a shared name never picks one
    assert sorted(link_targets(entities, "Alpha", index)) == ["alpha", "media-alpha"]
    assert link_targets(entities, "alpha", index) == ["alpha"]
    assert link_targets(entities, "Gamma", index) == ["gamma"]
    assert link_targets(entities, "Nothing", index) == []


def test_a_wikilink_edge_to_a_shared_name_needs_the_linking_pages_own_tie(tmp_path):
    import yaml

    from api.services import wikilink_resolver

    _page(tmp_path, "alpha", "Alpha", "tool")
    _page(tmp_path, "alpha-program", "Alpha", "project")
    _page(tmp_path, "writer", "Writer", "person", "Writer uses [[Alpha]] daily.", related="[alpha]")
    _page(tmp_path, "reader", "Reader", "person", "Reader heard of [[Alpha]].")
    wikilink_resolver.materialize_wikilink_edges(tmp_path)
    edges = yaml.safe_load((tmp_path / "graph_edges.yaml").read_text()) or []
    edges = edges.get("edges", edges) if isinstance(edges, dict) else edges
    pairs = {(e["source"], e["target"]) for e in edges if e.get("label") == "mentions"}
    assert ("writer", "alpha") in pairs
    assert not any(src == "reader" for src, _ in pairs)   # no tie: no edge picked by listing order


# --------------------------------------------------------------------------- Stage 2: never joined on the name alone


def _existing(stem: str, name: str, kind: str, body: str = "") -> dict:
    return {"id": stem, "frontmatter": {"name": name, "type": kind, "status": "active"}, "body": body}


def test_an_exact_title_joins_only_the_one_page_of_the_mentions_kind():
    from api.services import entity_resolver as er

    ide, link = _existing("alpha", "Alpha", "tool"), _existing("media-alpha", "Alpha", "media")
    by_name = {"alpha": link}                     # the last writer of the plain name map: the saved link
    same = {"alpha": [ide, link]}
    hit = er._find_direct_candidate_match({"name": "Alpha", "type": "tool"}, by_name, {}, same_title=same)
    assert hit["candidate"]["id"] == "alpha"
    # A program said where only the IDE has the name: never a join on the name.
    alone = {"alpha": [ide]}
    assert er._find_direct_candidate_match({"name": "Alpha", "type": "project"}, {"alpha": ide}, {},
                                           same_title=alone) is None
    # Without the map the old exact join holds (every other caller).
    assert er._find_direct_candidate_match({"name": "Alpha", "type": "project"}, {"alpha": ide}, {}) is not None
    # A concept mention — Stage 1's word for what it could not place — still joins the one placed page.
    assert er._same_title_pick({"name": "Alpha", "type": "concept"}, [ide, link]) is ide
    # Two of its kind: the judge's.
    twin = _existing("alpha-2", "Alpha", "tool")
    assert er._same_title_pick({"name": "Alpha", "type": "tool"}, [ide, twin]) is None


def test_the_same_title_judge_asks_when_it_cannot_tell(monkeypatch):
    from api.services import entity_resolver as er

    calls = []

    async def judge(**kwargs):
        calls.append(kwargs)
        return {"alpha": "different", "alpha-program": "unsure"}[
            "alpha" if kwargs["existing_type"] == "tool" else "alpha-program"]

    monkeypatch.setattr(er, "_llm_judge_same_entity", judge)
    ide, prog = _existing("alpha", "Alpha", "tool"), _existing("alpha-program", "Alpha", "project")
    twin_prog = _existing("alpha-program-2", "Alpha", "project")
    mention = {"name": "Alpha", "type": "project", "summary": "Applied to Alpha's spring cohort."}
    match = asyncio.run(er._same_title_match(mention, {"alpha": [ide, prog, twin_prog]}, {}, settings=None))
    assert match["decision"] == "unsure" and match["candidate"]["id"] == "alpha-program"
    assert match["same_title"] == ["alpha", "alpha-program", "alpha-program-2"]
    assert all(c["types_may_differ"] for c in calls)
    # One page of the mention's kind: no judge at all.
    calls.clear()
    assert asyncio.run(er._same_title_match(mention, {"alpha": [ide, prog]}, {}, settings=None)) is None
    assert calls == []


def test_the_judge_prompt_lets_the_descriptions_decide_when_types_may_differ(monkeypatch):
    from api.services import entity_resolver as er

    seen = {}

    async def fake(**kwargs):
        seen["prompt"] = kwargs["messages"][-1]["content"]

        class R:
            choices = [type("C", (), {"message": type("M", (), {"content": '{"decision": "different"}'})()})()]
        return R()

    monkeypatch.setattr("api.services.providers.resolve_llm_fn", lambda *a, **k: fake)

    class S:
        litellm_disambiguation_model = "x"
        litellm_model = "x"

    out = asyncio.run(er._llm_judge_same_entity("Alpha", "project", "a program", "Alpha", "tool", "an IDE", S(),
                                                note=er._SAME_TITLE_NOTE, types_may_differ=True))
    assert out == "different"
    assert er._TYPE_GUIDELINE not in seen["prompt"] and "let the descriptions decide" in seen["prompt"]
    # Without the flag a type mismatch is still "different" with no call.
    seen.clear()
    assert asyncio.run(er._llm_judge_same_entity("Alpha", "project", "", "Alpha", "tool", "", S())) == "different"
    assert seen == {}


# --------------------------------------------------------------------------- asked in plain words


def test_a_name_pages_share_is_asked_which_page_and_one_page_yes_or_no():
    """Owner 2026-10-29 (pick the page): one question per mention over every page with the name — answered by the
    page's option or "none" (`same_name_pick`) — and, with one page, the yes/no question about it."""
    from api.services import inbox_wording

    fm = {"kind": "merge_suggestion", "entity_id": "alpha", "entity_name": "Alpha", "merge_target_hint": "alpha"}
    titled = [{"id": "alpha-program", "name": "Alpha", "type": "project", "qualifier": "program"},
              {"id": "alpha", "name": "Alpha", "type": "tool", "qualifier": "IDE"},
              {"id": "media-alpha", "name": "Alpha", "type": "media", "qualifier": "example.com"}]
    same = {"alpha": "IDE", "alpha-program": "program", "media-alpha": "example.com"}
    said = inbox_wording.spoken(fm, "2026-10-29", other_fm={"name": "Alpha", "type": "tool"}, same=same, titled=titled)
    assert said.question == "Which Alpha is this: the program, the IDE or the one saved from example.com?"
    assert "3 things are called Alpha" in said.reason and "another one" in said.reason
    # Whatever the merge target, it is the same one question.
    assert inbox_wording.spoken({**fm, "merge_target_hint": "media-alpha"}, "2026-10-29", same=same,
                                titled=titled).question == said.question
    # One page with the name.
    said = inbox_wording.spoken(fm, "2026-10-29", other_fm={"name": "Alpha", "type": "tool"}, same={})
    assert said.question == "Is this the Alpha tool?" and "a page already has that name" in said.reason
    # An item served without options (no candidate left, an older item) keeps same / different.
    assert set(inbox_catchup_keys()) <= {"same", "different"}
    # Different names keep the old pair question.
    other = {**fm, "entity_name": "Alfa"}
    assert inbox_wording.spoken(other, "2026-10-29", other_fm={"name": "Alpha", "type": "tool"}).question \
        == "Are Alfa and Alpha the same tool?"
    # A decay question about a page whose title is shared names it by its qualifier.
    decay = {"kind": "decay", "entity_id": "alpha", "entity_name": "Alpha"}
    assert inbox_wording.spoken(decay, "2026-10-29", page_fm={"name": "Alpha", "type": "tool"},
                                same={"alpha": "IDE"}).question == "Do you still use Alpha (IDE)?"


def inbox_catchup_keys() -> list[str]:
    from types import SimpleNamespace

    from api.services import catchup_chat

    item = SimpleNamespace(kind=SimpleNamespace(value="merge_suggestion"), options=[])
    return [row["key"] for row in catchup_chat.answer_keys(item)]


def test_a_same_title_question_points_at_the_page_by_id(tmp_path):
    from api.services.clarification_manager import ClarificationManager
    from api.services.markdown_parser import parse

    _page(tmp_path, "alpha", "Alpha", "tool")
    _page(tmp_path, "alpha-program", "Alpha", "project")
    manager = ClarificationManager(tmp_path)
    item = manager.create(entity_name="Alpha", source_episode="ep_2026-10-29_001",
                          uncertainty_type="Possible duplicate of Alpha", suggested_classification="project — x",
                          suggested_confidence=0.6, source_context="", same_title=["alpha", "alpha-program"],
                          target_id="alpha-program")
    fm = parse(manager.dir / f"{item}.md").frontmatter
    assert fm["merge_target_hint"] == "alpha-program" and fm["same_title"] == ["alpha", "alpha-program"]
    assert fm["title"] == "Which Alpha is this?"       # one question for the mention (pick the page)

    from api.services import mcp_tools

    line = mcp_tools._format_inbox_blurb(fm, "")
    assert "`alpha`, `alpha-program`" in line and "2 pages called Alpha" in line and "page:<id>" in line


def test_the_inbox_serves_display_names_and_the_question(bank):
    from api.services import inbox_service
    from api.services.clarification_manager import ClarificationManager

    ClarificationManager(bank).create(entity_name="Alpha", source_episode="ep_2026-10-29_001",
                                      uncertainty_type="Possible duplicate of Alpha",
                                      suggested_classification="project — x", suggested_confidence=0.6,
                                      source_context="", same_title=["alpha", "alpha-program"], target_id="alpha")
    items = [i for i in inbox_service.load_inbox(bank) if i.kind.value == "merge_suggestion"]
    assert items, "the question is served"
    item = items[0]
    assert item.same_title == ["alpha", "alpha-program"]
    assert item.merge_target_display_name == "Alpha (IDE)"
    assert item.spoken_question == "Which Alpha is this: the IDE or the program?"
    assert [(o.key, o.page_name, o.qualifier) for o in item.options] == [
        ("page:alpha", "Alpha", "IDE"), ("page:alpha-program", "Alpha", "program"), ("another", None, None)]


# --------------------------------------------------------------------------- the agent doors


def _ctx(memory):
    from api.services import mcp_tools

    return mcp_tools.ToolContext(memory_path=lambda: memory, session_id="s", harness="unknown")


def test_recall_detail_on_a_shared_name_names_both_and_a_page_says_what_it_is_shown_as(bank):
    from api.services import mcp_tools

    out = str(mcp_tools.recall_detail(_ctx(bank), "Alpha"))
    assert "2 pages are called \"Alpha\"" in out
    assert "Alpha (IDE) — id `alpha`" in out and "Alpha (program) — id `alpha-program`" in out
    page = str(mcp_tools.recall_detail(_ctx(bank), "alpha"))
    assert "Shown as: Alpha (IDE)." in page and "Alpha (program) (id `alpha-program`)" in page
    lone = str(mcp_tools.recall_detail(_ctx(bank), "beta"))
    assert "Shown as" not in lone


def test_recalls_page_heading_carries_the_qualifier_and_id(bank):
    from api.services import mcp_tools

    block = mcp_tools._render_entity_summary(bank / "entities", {"entity_id": "alpha-program"})
    assert block.startswith("### Alpha (program) (project, ") and block.splitlines()[0].endswith("— id `alpha-program`")
    lone = mcp_tools._render_entity_summary(bank / "entities", {"entity_id": "beta"})
    assert lone.startswith("### Beta (tool, ") and "id `" not in lone.splitlines()[0]


def test_a_name_two_pages_share_resolves_to_neither_for_an_agent(bank):
    from api.services import mcp_tools

    entities = bank / "entities"
    assert mcp_tools._entity_id_for_name(entities, "Alpha") is None
    assert mcp_tools._entity_id_for_name(entities, "alpha") == "alpha"
    assert mcp_tools._entity_id_for_name(entities, "Beta") == "beta"


def test_an_ask_citation_links_a_shared_title_by_id():
    from api.services import mcp_tools

    out = mcp_tools._render_ask({"answer": "x", "citations": [
        {"entity_id": "alpha", "entity_name": "Alpha", "display_name": "Alpha (IDE)"},
        {"entity_id": "beta", "entity_name": "Beta"}]})
    assert "- [[alpha|Alpha (IDE)]]" in out and "- [[Beta]]" in out
