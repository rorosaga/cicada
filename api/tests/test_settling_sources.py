"""Ruling 54a (owner 2026-11-04): for a private person, the way to learn and update facts is the page's Where to check
sources, never a search engine. Synthetic banks only; the model and the fetcher are stubs."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from api.services import bank_index, fact_sources, markdown_parser, settling_agent, source_proposals, source_refresh, \
    web_context, web_lookup, web_settle
from api.services.claims import Claim, parse_claims, write_claims

SITE = "https://nora-hidden-example.org/about"
HTML = "<html><title>About</title><main>Nora Hidden is part of Globex now, and has since this year.</main></html>"
PREDICATE = "part-of"
TRUSTED = {"ref": SITE, "kind": "url", "predicate": PREDICATE, "added_by": "user", "added_at": "2026-09-01"}


def _claim(cid: str, obj: str, said: str) -> Claim:
    return Claim(id=cid, text=f"Nora Hidden is part of {obj}", subject="nora-hidden", predicate=PREDICATE, object=obj,
                 object_kind="literal", observer="user", source_trust="direct", origin="sleep", authored_by="m",
                 confidence=0.8, valid_from=said, recorded_at=said)


def _page(memory: Path, sources, *, said="2026-01-02") -> None:
    body = write_claims("## Summary\nNora Hidden is a friend.\n", [_claim("c-a", "Initech", said), _claim("c-b", "Globex", said)])
    markdown_parser.write(memory / "entities" / "nora-hidden.md",
                          {"name": "Nora Hidden", "type": "person", "status": "active", "confidence": 0.7,
                           "created": "2026-01-01", "last_referenced": "2026-01-01", "source_episodes": [],
                           "related": [], "version": 1, "sources": sources}, body)


def _question(memory: Path) -> Path:
    path = memory / "inbox" / "inbox-501.md"
    markdown_parser.write(path, {
        "kind": "conflict", "status": "pending", "priority": 0.6, "entity_id": "nora-hidden", "entity_name": "Nora Hidden",
        "predicate": PREDICATE, "title": "What is Nora Hidden's title?", "created_date": "2026-10-23",
        "uncertainty_type": "conflict", "allow_other": True, "allow_defer": True,
        "options": [{"key": "a", "label": "Initech", "claim_id": "c-a"}, {"key": "b", "label": "Globex", "claim_id": "c-b"}],
    }, "Two values.")
    bank_index.invalidate(memory)
    return path


@pytest.fixture
def bank(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_ALLOW_CONNECTOR_FETCH", "on")
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    m = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (m / sub).mkdir(parents=True)
    markdown_parser.write(m / "entities" / "dana-rivers.md",
                          {"name": "Dana Rivers", "type": "person", "owner": True, "status": "active", "confidence": 0.7,
                           "created": "2026-01-01", "last_referenced": "2026-01-01", "source_episodes": [], "related": [],
                           "version": 1}, "## Summary\nThe owner.\n")
    return m


class Stub:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.searches = 0
        self.prompts: list[str] = []

    def __call__(self, *, messages, web_search=False, timeout=None, **_kw):
        if web_search:
            self.searches += 1
            raise AssertionError("no search for a private person")
        self.prompts.append(messages[1]["content"])
        reply = self.replies.pop(0) if self.replies else {"answer": {"sure": False}}
        return {"choices": [{"message": {"content": json.dumps(reply)}}], "model": "fake-model"}


def _run(bank, stub, opened=None):
    calls = opened if opened is not None else []

    async def fetch(url):
        calls.append(url)
        return "ok", HTML, url
    return asyncio.run(web_lookup.run_tail(bank, SimpleNamespace(web_check_per_run=8), user_triggered=True, llm_fn=stub,
                                           engine=("resolved", "claude-cli", "plan"), fetch=fetch))


ANSWER = {"answer": {"sure": True, "option_key": "b", "url": SITE,
                     "quote": "Nora Hidden is part of Globex now"}}


def test_an_open_tracked_source_settles_a_private_person_with_no_search_and_undo_takes_it_back(bank):
    _page(bank, [TRUSTED])
    _question(bank)
    stub, opened = Stub(ANSWER), []
    report = _run(bank, stub, opened)
    assert opened == [SITE] and stub.searches == 0 and report.settled == 1
    assert HTML.split("<main>")[1].split("</main>")[0] in stub.prompts[0]     # opened before the model's first turn
    body = markdown_parser.parse(bank / "entities" / "nora-hidden.md").body
    claims = {c.id: c for c in parse_claims(body)}
    assert claims["c-a"].valid_to is not None and claims["c-a"].superseded_by       # closed, never deleted
    rec = markdown_parser.parse(bank / "inbox" / "settled" / "inbox-501.md").frontmatter["settled"]
    assert rec["scope"] == "source" and rec["ref"] == SITE and rec["at"]
    target, _p, _l = web_settle.undo(bank, "inbox-501")
    assert target == "inbox-501"
    assert parse_claims(markdown_parser.parse(bank / "entities" / "nora-hidden.md").body)[0].valid_to is None


def test_same_day_or_undated_stays_the_one_question_ruling_26(bank):
    from datetime import date

    _page(bank, [TRUSTED], said=date.today().isoformat())
    _question(bank)
    report = _run(bank, Stub(ANSWER))
    assert report.settled == 0 and report.skipped.get("refused") == 1 and (bank / "inbox" / "inbox-501.md").exists()


def test_a_quote_not_on_the_page_settles_nothing(bank):
    _page(bank, [TRUSTED])
    _question(bank)
    wrong = {"answer": {"sure": True, "option_key": "b", "url": SITE, "quote": "words not on the page"}}
    report = _run(bank, Stub(wrong, wrong, wrong))
    assert report.settled == 0 and report.skipped == {"quote_not_on_page": 1}


def test_a_walled_tracked_source_is_never_requested_stays_on_the_agents_list_and_the_question_stays(bank):
    linkedin = {"ref": "https://www.linkedin.com/in/nora-hidden", "kind": "url", "predicate": "linkedin",
                "added_by": "user", "added_at": "2026-09-01"}
    _page(bank, [linkedin])
    _question(bank)
    opened: list[str] = []

    def fn(**_kw):
        raise AssertionError("no call: nothing Cicada may open")
    report = _run(bank, fn, opened)
    assert opened == [] and report.settled == 0 and report.source_kinds == {"walled": 1}
    assert (bank / "inbox" / "inbox-501.md").exists()
    due = source_refresh.due(bank)
    assert [d.ref for d in due if d.checker == source_refresh.AGENT] == [linkedin["ref"]]   # ruling 26's own listing


def test_a_proposed_source_is_never_opened(bank):
    proposed = dict(TRUSTED, added_by="agent", proposed=True)
    _page(bank, [proposed])
    _question(bank)
    opened: list[str] = []

    def fn(**_kw):
        raise AssertionError("no call")
    report = _run(bank, fn, opened)
    assert opened == [] and report.settled == 0 and report.source_kinds == {"proposed": 1}


def test_a_removed_source_is_not_there_to_open(bank):
    _page(bank, [TRUSTED])
    fact_sources.delete_source(bank, "nora-hidden", 0, remembered_by="user")
    _question(bank)
    opened: list[str] = []

    def fn(**_kw):
        raise AssertionError("no call")
    report = _run(bank, fn, opened)
    assert opened == [] and report.source_kinds == {"none": 1}


def test_no_source_means_no_call_and_the_question_stays(bank):
    _page(bank, [])
    _question(bank)

    def fn(**_kw):
        raise AssertionError("no call")
    report = _run(bank, fn)
    assert report.settled == 0 and report.looked_up == 0 and report.source_kinds == {"none": 1}


def test_a_blocked_source_is_never_retried_and_the_question_stays(bank):
    _page(bank, [TRUSTED])
    _question(bank)
    asked: list[str] = []

    async def fetch(url):
        asked.append(url)
        return "blocked", "", ""
    stub = Stub({"calls": [{"tool": "open", "url": SITE}]}, {"answer": {"sure": False}})
    report = asyncio.run(web_lookup.run_tail(bank, SimpleNamespace(web_check_per_run=8), user_triggered=True, llm_fn=stub,
                                             engine=("resolved", "claude-cli", "plan"), fetch=fetch))
    assert asked == [SITE] and report.settled == 0


def test_the_model_may_propose_only_a_link_written_in_the_conversation_it_names(bank):
    _page(bank, [TRUSTED])
    _question(bank)
    markdown_parser.write(bank / "episodes" / "ep_2026-10-22_001.md",
                          {"id": "ep_2026-10-22_001", "timestamp": "2026-10-22T09:00:00+00:00", "processed": True,
                           "source": "whatsapp"}, "speaker:Nora: my site is https://nora-found.example.org/ now")
    bank_index.invalidate(bank)
    answer = {"answer": {"sure": False, "propose": [
        {"id": "nora-hidden", "url": "https://nora-found.example.org/", "episode": "ep_2026-10-22_001", "quote": "my site is"},
        {"id": "nora-hidden", "url": "https://guessed-from-a-name.example.org/", "episode": "ep_2026-10-22_001", "quote": "my site is"},
    ]}}
    report = _run(bank, Stub(answer))
    sources = fact_sources.as_sources(markdown_parser.parse(bank / "entities" / "nora-hidden.md").frontmatter["sources"])
    added = [s for s in sources if s["ref"] != SITE]
    assert [s["ref"] for s in added] == ["https://nora-found.example.org/"]
    assert fact_sources.is_proposed(added[0]) and not source_refresh.tracked(added[0])
    assert "entities/nora-hidden.md" in report.paths
    assert source_proposals.ASKS == "sources"     # it joins the one grouped review on the next Sleep's step


def test_a_removed_link_is_not_proposed_again(bank):
    _page(bank, [dict(TRUSTED, ref="https://nora-found.example.org/", predicate=None)])
    fact_sources.delete_source(bank, "nora-hidden", 0, remembered_by="user")
    assert settling_agent.take_proposals(bank, [{"id": "nora-hidden", "url": "https://nora-found.example.org/",
                                                 "episode": "", "quote": ""}], ("nora-hidden",)) == []


def test_a_changed_page_is_read_through_ruling_26s_own_fold(bank):
    """The update path's one gap: a tracked public page that changed with no machine-readable fact."""
    _page(bank, [dict(TRUSTED, refresh={"at": "2026-10-01", "outcome": "read", "good": "2026-10-01", "hash": "old",
                                        "changed": "2026-10-01"})])
    stub = Stub({"value": "Globex", "quote": "Nora Hidden is part of Globex now"})
    report = _run(bank, stub)
    fm = markdown_parser.parse(bank / "entities" / "nora-hidden.md").frontmatter
    assert "changed" not in fact_sources.as_sources(fm["sources"])[0]["refresh"]
    assert "entities/nora-hidden.md" in report.paths and report.skipped.get("source_read") == 1
    assert any(p.startswith("episodes/") for p in report.paths)      # a `source-refresh` episode, its evidence


def test_a_changed_page_the_quote_is_not_on_keeps_waiting_for_the_persons_agent(bank):
    _page(bank, [dict(TRUSTED, refresh={"at": "2026-10-01", "outcome": "read", "good": "2026-10-01", "changed": "2026-10-01"})])
    report = _run(bank, Stub({"value": "Globex", "quote": "invented words"}))
    fm = markdown_parser.parse(bank / "entities" / "nora-hidden.md").frontmatter
    assert fact_sources.as_sources(fm["sources"])[0]["refresh"]["changed"]
    assert report.paths == []


def test_a_public_pages_own_source_comes_before_its_pinned_search():
    """`web_context`: the facts from a tracked source, each quote on the bytes opened; the search only when none."""
    url = "https://globex-example.org/"
    page = SimpleNamespace(entity_id="globex", name="Globex", type="company", world=[], fm={}, body="", depth="line")

    async def fetch(url):
        return "ok", "<html><title>Globex</title><main>Globex is a company founded in 1990.</main></html>", url

    def fn(*, messages, web_search=False, **_kw):
        assert web_search is False
        return {"choices": [{"message": {"content": json.dumps({"sure": True, "facts": [
            {"predicate": "description", "value": "a company", "as_of": "", "url": url,
             "quote": "Globex is a company founded in 1990."},
            {"predicate": "description", "value": "invented", "as_of": "", "url": url,
             "quote": "words not on the page"}]})}}], "model": "m"}
    import api.services.settling_agent as sa

    real = sa.tracked_public
    sa.tracked_public = lambda *_a, **_k: ({url: "globex"}, {"open": 1, "walled": 0, "proposed": 0})
    try:
        facts = web_settle.BankFacts()
        looked = asyncio.run(web_context.from_own_sources(fn, Path("/nonexistent"), page, "line", facts, fetch=fetch))
    finally:
        sa.tracked_public = real
    assert looked is not None and [f.value for f in looked.facts] == ["a company"]


def test_a_source_that_blocked_cicadas_read_is_never_asked_again(bank):
    _page(bank, [dict(TRUSTED, refresh={"at": "2026-10-01", "outcome": "blocked", "blocked": "2026-10-01",
                                        "changed": "2026-10-01"})])
    _question(bank)
    opened: list[str] = []

    def fn(**_kw):
        raise AssertionError("no call")
    report = _run(bank, fn, opened)
    assert opened == [] and report.settled == 0 and report.source_kinds == {"walled": 1}


def test_a_private_pairs_tracked_source_settles_it_with_no_search_and_never_a_merge(bank):
    """A person in the address book: no search exists for them, and the page's own source may still answer (54a)."""
    from api.services.claims import parse_claims as parse

    site = "https://nora-hidden-example.org/about"
    markdown_parser.write(bank / "entities" / "nora-hidden.md", {
        "name": "Nora Hidden", "type": "person", "status": "active", "confidence": 0.7, "created": "2026-01-01",
        "last_referenced": "2026-01-01", "source_episodes": [], "related": [], "version": 1,
        "sources": [dict(TRUSTED, ref=site, predicate="website"),
                    {"ref": "addressbook://card-1", "kind": "app", "predicate": "phone", "added_by": "cicada"}]},
        "## Summary\nNora Hidden is a friend.\n")
    markdown_parser.write(bank / "entities" / "nora42.md", {
        "name": "nora42", "type": "person", "status": "active", "confidence": 0.7, "created": "2026-01-01",
        "last_referenced": "2026-01-01", "source_episodes": [], "related": [], "version": 1}, "## Summary\nAn account.\n")
    markdown_parser.write(bank / "inbox" / "inbox-601.md", {
        "kind": "merge_suggestion", "required_input": "merge", "status": "pending", "priority": 0.6, "entity_id": "nora42",
        "entity_name": "nora42", "title": "Is nora42 the same as Nora Hidden?", "merge_target_hint": "nora-hidden",
        "uncertainty_type": "Possible duplicate of Nora Hidden", "created_date": "2026-10-23", "allow_other": True,
        "allow_defer": True, "suggested_classification": "person"}, "Nora Hidden may go by nora42.")
    bank_index.invalidate(bank)

    async def fetch(url):
        return "ok", "<html><title>Nora Hidden</title><main>Nora Hidden writes as nora42 online.</main></html>", url
    stub = Stub({"answer": {"sure": True, "url": site, "quote": "Nora Hidden writes as nora42 online."}})
    report = asyncio.run(web_lookup.run_tail(bank, SimpleNamespace(web_check_per_run=8), user_triggered=True, llm_fn=stub,
                                             engine=("resolved", "claude-cli", "plan"), fetch=fetch))
    assert report.settled == 1 and stub.searches == 0
    assert "Search: not available" in stub.prompts[0]
    assert [c.predicate for c in parse(markdown_parser.parse(bank / "entities" / "nora-hidden.md").body)] == ["goes-by"]
    assert (bank / "entities" / "nora42.md").exists()
    rec = markdown_parser.parse(bank / "inbox" / "settled" / "inbox-601.md").frontmatter["settled"]
    assert rec["scope"] == "source"


def _changed_source(n: int) -> dict:
    return {"ref": f"https://site-{n}-example.org/about", "kind": "url", "predicate": PREDICATE, "added_by": "user",
            "added_at": "2026-09-01", "refresh": {"at": "2026-10-01", "outcome": "read", "good": "2026-10-01",
                                                  "changed": "2026-10-01"}}


def test_the_cap_on_changed_sources_counts_every_attempt_and_an_empty_read_backs_off(bank):
    _page(bank, [_changed_source(n) for n in range(12)])
    calls, fetched = [], []

    def fn(*, messages, web_search=False, **_kw):
        calls.append(1)
        return {"choices": [{"message": {"content": json.dumps({"value": ""})}}], "model": "m"}

    async def fetch(url):
        fetched.append(url)
        return "ok", HTML, url

    def drain():
        return asyncio.run(web_lookup.run_tail(bank, SimpleNamespace(web_check_per_run=8), user_triggered=True, llm_fn=fn,
                                               engine=("resolved", "claude-cli", "plan"), fetch=fetch))
    drain()
    assert len(calls) == len(fetched) == settling_agent.UPDATES_PER_DRAIN
    drain()
    assert len(calls) == settling_agent.UPDATES_PER_DRAIN * 2      # the next five; the first five wait
    drain()
    assert len(calls) == 12                                         # the last two, and no page read twice
    assert len(set(fetched)) == 12
    drain()
    assert len(calls) == 12


def test_works_at_is_no_conflict_two_places_at_once_are_two_facts(bank):
    """Owner, 2026-11-04: "I can be working in different things at the same time". Pinned for each path, a stale bank map
    included: the seed's multi-valued list wins."""
    from api.services import inbox_generator, predicates

    (bank / "_predicates.yaml").write_text("single_valued:\n  - works-at\n", encoding="utf-8")
    assert predicates.cardinality(bank, "works-at") == "multi"
    assert predicates.build_cardinality_fn(bank)("works-at") is False
    _page(bank, [TRUSTED])
    inbox_generator.write_claim_nudges([{
        "action": "conflict_nudge", "id": "nora-hidden", "predicate": "works-at", "question": "Where?",
        "options": [{"key": "a", "label": "Initech"}, {"key": "b", "label": "Globex"}]}], bank)
    assert not list((bank / "inbox").glob("inbox-*.md"))
    markdown_parser.write(bank / "inbox" / "inbox-531.md", {
        "kind": "conflict", "status": "pending", "priority": 0.6, "entity_id": "nora-hidden", "entity_name": "Nora Hidden",
        "predicate": "works-at", "created_date": "2026-10-23", "allow_other": True, "allow_defer": True, "options": [
            {"key": "a", "label": "Initech", "claim_id": "c-a"}, {"key": "b", "label": "Globex", "claim_id": "c-b"}]}, "x")
    bank_index.invalidate(bank)
    kinds: dict = {}
    assert web_lookup.source_items(bank, web_settle.bank_facts(bank), already=set(), kinds=kinds) == [] and kinds == {}


IMPORTED = {"ref": "https://www.linkedin.com/in/nora-hidden", "kind": "url", "predicate": "linkedin", "added_by": "cicada",
            "added_at": "2026-09-01", "match": "name"}


def test_a_linkedin_link_from_the_connections_is_kept_as_where_to_check_and_read_only_on_ask(bank):
    """Owner, 2026-11-04: "do save the links as resources to check". Counted as given on a confident match; never a tracked
    source, so nothing lists it for a visit; never requested."""
    from api.services import linkedin_people, person_photo

    _page(bank, [IMPORTED])
    _question(bank)
    assert linkedin_people.from_connections(IMPORTED) and person_photo.is_own_account(IMPORTED)
    assert not source_refresh.tracked(IMPORTED) and source_refresh.due(bank) == []
    opened: list[str] = []

    def fn(**_kw):
        raise AssertionError("no call")
    report = _run(bank, fn, opened)
    assert opened == [] and report.source_kinds == {"on_ask": 1}
    assert "read only when they ask" in settling_agent._read_sources(bank, "nora-hidden")


@pytest.mark.parametrize("change", [{"match": "alias"}, {"predicate": "website"}, {"added_by": "agent"}])
def test_an_alias_only_match_or_any_other_link_is_not_counted_as_given(change):
    from api.services import linkedin_people

    assert not linkedin_people.from_connections({**IMPORTED, **change})


def test_a_second_change_is_read_though_the_first_is_waiting(bank):
    """The back-off is keyed on the day the page was seen changing: a later change never waits on an earlier one."""
    _page(bank, [_changed_source(0)])
    calls: list = []

    def fn(*, messages, web_search=False, **_kw):
        calls.append(1)
        return {"choices": [{"message": {"content": json.dumps({"value": ""})}}], "model": "m"}

    async def fetch(url):
        return "ok", HTML, url

    def drain():
        asyncio.run(web_lookup.run_tail(bank, SimpleNamespace(web_check_per_run=8), user_triggered=True, llm_fn=fn,
                                        engine=("resolved", "claude-cli", "plan"), fetch=fetch))
    drain()
    drain()
    assert len(calls) == 1
    later = _changed_source(0)
    later["refresh"]["changed"] = "2026-10-20"
    _page(bank, [later])
    bank_index.invalidate(bank)
    drain()
    assert len(calls) == 2
