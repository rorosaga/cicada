"""Two related things are not one thing (owner 2026-10-29, G21/G209; `entity_relations`).

"There are some really dumb questions again like is <product-a> the same as <product-a> Code?" — a part and its whole,
a product and its maker, an alternative and the original, a version and its line, asked as "same?". The judge now
names the relation; a relation is a claim, never a question; a public pair is settled by a cited check; a pair the
record already relates is never asked. Synthetic names only; the judge and the search tool are fakes; git is real."""
from __future__ import annotations

import asyncio
import json
import subprocess
from types import SimpleNamespace

import pytest

from _synthetic_bank import _bank as _synthetic, _entity as _page
from api.services import (agent_engine, bank_index, entity_extractor, entity_relations, entity_resolver,
                          markdown_parser, merge_rejections, web_lookup, web_settle)
from api.services.clarification_manager import ClarificationManager
from api.services.claims import Claim, parse_claims, write_claims
from api.tests.test_sleep_cycle_hold import _bank, _entity, _settings

EP, TS = "ep_2026-10-28_001", "2026-10-28T10:00:00+00:00"
DOCS = "https://docs.tool-example.dev/example-db-cloud"


def _resolve(memory, extracted, pages, monkeypatch, verdict, calls=None):
    async def judge(*_a, **k):
        if calls is not None:
            calls.append(k.get("existing_name"))
        return verdict

    async def batch(new_name, new_type, new_description, entries, settings, *, new_connections=""):
        if calls is not None:
            calls.extend(e["name"] for e in entries)
        return [verdict for _ in entries]
    monkeypatch.setattr(entity_resolver.SqliteVecIndexer, "_rebuild_pending_index", lambda self, entries: None)
    monkeypatch.setattr(entity_resolver, "_llm_judge_same_entity", judge)
    monkeypatch.setattr(entity_resolver, "_llm_judge_batch", batch)
    return asyncio.run(entity_resolver.resolve(extracted, pages, _settings(memory)))


def _asked(memory):
    return [markdown_parser.parse(p).frontmatter for p in sorted((memory / "inbox").glob("inbox-*.md"))]


def _fake_response(payload: dict):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))])


# ---------- the judge names a relation ----------


@pytest.mark.parametrize("payload, new_type, expected", [
    ({"decision": "related", "relation": "part_of"}, "tool", "related:part_of"),
    ({"decision": "related", "relation": "made-by"}, "tool", "related:made_by"),
    ({"decision": "related", "relation": "sibling_of"}, "tool", "different"),   # no relation Cicada keeps
    ({"decision": "related", "relation": "part_of"}, "person", "different"),    # two people are never a relation
    ({"decision": "unsure"}, "tool", "unsure"),
])
def test_the_one_pair_judge_reads_a_relation(monkeypatch, tmp_path, payload, new_type, expected):
    from api.services import providers

    async def fn(**_k):
        return _fake_response(payload)
    monkeypatch.setattr(providers, "resolve_llm_fn", lambda *a, **k: fn)
    out = asyncio.run(entity_resolver._llm_judge_same_entity(
        "Example DB Cloud", new_type, "a hosted database", "Example DB", new_type, "a database", _settings(tmp_path)))
    assert out == expected


def test_the_batch_judge_reads_a_relation_per_entry():
    parsed = {"decisions": [{"entry": 1, "decision": "related", "relation": "version_of"},
                            {"entry": 2, "decision": "same"}, {"entry": 3, "decision": "related"}]}
    assert entity_resolver._batch_decisions(parsed, 3, "tool") == ["related:version_of", "same", "different"]
    assert entity_resolver._batch_decisions(parsed, 3, "person") == ["different", "same", "different"]


def test_both_prompts_offer_related_and_say_a_part_is_never_the_same():
    for prompt in (entity_resolver._DISAMBIG_PROMPT, entity_resolver._DISAMBIG_BATCH_PROMPT):
        assert '"related"' in prompt and "A part is never the same as its whole" in prompt
        assert entity_relations.PROMPT_LINES in prompt
    schema = agent_engine.SCHEMA_BY_STAGE["disambiguation"]["properties"]
    assert schema["relation"]["enum"] == list(entity_relations.RELATIONS)


# ---------- a relation is never a question ----------


def _tool_page(eid, name, aliases=(), body=None):
    return {"id": eid, "frontmatter": {"name": name, "type": "tool", "status": "active", "confidence": 0.8,
                                       **({"aliases": list(aliases)} if aliases else {})},
            "body": body or f"## Summary\n{name} is a synthetic tool."}


def test_a_related_mention_is_no_question_and_its_relation_is_a_claim(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    mention = _entity("Example DB Cloud", "tool", EP, TS)
    out = _resolve(memory, [{"episode_id": EP, "entities": [mention], "relationships": []}],
                   [_tool_page("example-db", "Example DB")], monkeypatch, "related:made_by")
    assert _asked(memory) == []
    assert out["relations"] == [{
        "source": "Example DB", "target": "Example DB Cloud", "label": "creates", "confidence": 0.6,
        "source_page": "example-db", "target_page": "example-db-cloud",
        "epistemic": "abductive", "evidence": [{"episode": EP, "kind": "reasoning"}], "source_episode": EP, "source_episode_timestamp": TS}]
    claims = entity_extractor.entities_to_claims(
        [{"episode_id": "", "origin": "sleep", "relationships": out["relations"]}], memory)
    assert [(c.subject, c.predicate, c.object, c.origin, c.observer, c.epistemic) for c in claims] == [
        ("example-db", "creates", "example-db-cloud", "sleep", "agent", "abductive")]
    assert claims[0].evidence[0].kind == "reasoning" and claims[0].evidence[0].episode == EP


def test_an_unsure_judge_still_asks(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    mention = _entity("Example DB Cloud", "tool", EP, TS)
    out = _resolve(memory, [{"episode_id": EP, "entities": [mention], "relationships": []}],
                   [_tool_page("example-db", "Example DB")], monkeypatch, "unsure")
    assert [(fm["kind"], fm["merge_target_hint"]) for fm in _asked(memory)] == [("merge_suggestion", "example-db")]
    assert out["relations"] == []


def _project_page(eid, name):
    return {"id": eid, "frontmatter": {"name": name, "type": "project", "status": "active", "confidence": 0.8,
                                       "born": {"kind": "repository", "repo": "example-repo"}},
            "body": f"## Summary\n{name} is a synthetic project."}


def test_a_part_of_a_project_lands_on_it_never_a_question(tmp_path, monkeypatch):
    """Owner 2026-10-23: "a canoe, its hull, the hull build — is one thing". A feature or a pull request of a project
    the judge calls a part lands on the project as a mention of it; its own other names never become the project's."""
    memory = _bank(tmp_path)
    mention = _entity("Faster loading PR", "project", EP, TS)
    mention["aliases"] = ["#999"]
    out = _resolve(memory, [{"episode_id": EP, "entities": [mention], "relationships": []}],
                   [_project_page("example-app", "Example App")], monkeypatch, "related:part_of")
    assert _asked(memory) == []
    assert [(c["action"], c["id"]) for c in out["changes"]] == [("update", "example-app")]
    assert not (out["changes"][0]["entity"].get("aliases") or [])
    assert out["name_to_id"]["faster loading pr"] == "example-app"
    assert out["relations"] == []   # one endeavour: no claim between a page and itself


# ---------- an organisation/tool alias lead meets the judge first ----------


def _lead_pages():
    return [_tool_page("example-db", "Example DB"),
            _tool_page("example-db-cloud", "Example DB Cloud", aliases=["Example DB"])]


@pytest.mark.parametrize("verdict, asked", [("related:makes", False), ("different", False), ("unsure", True),
                                            ("same", True)])
def test_an_alias_lead_is_asked_only_when_the_judge_cannot_tell(tmp_path, monkeypatch, verdict, asked):
    memory = _bank(tmp_path)
    mention = _entity("Example DB", "tool", EP, TS)
    out = _resolve(memory, [{"episode_id": EP, "entities": [mention], "relationships": []}], _lead_pages(),
                   monkeypatch, verdict)
    assert bool(_asked(memory)) is asked
    related = [r for r in out["relations"] if r["source_page"] == "example-db-cloud"]
    assert len(related) == (1 if verdict == "related:makes" else 0)


def test_a_pair_the_record_relates_is_judged_and_asked_never_again(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    pages = _lead_pages()
    pages[1]["body"] = write_claims(pages[1]["body"], [Claim(
        id="clm_rel", text="Example DB Cloud is made by Example DB", subject="example-db-cloud", predicate="made-by",
        object="example-db", valid_from="2026-10-01", recorded_at="2026-10-01")])
    for page in pages:
        markdown_parser.write(memory / "entities" / f"{page['id']}.md", page["frontmatter"], page["body"])
    calls: list = []
    mention = _entity("Example DB", "tool", EP, TS)
    _resolve(memory, [{"episode_id": EP, "entities": [mention], "relationships": []}], pages, monkeypatch, "unsure",
             calls)
    # Never asked; the alias behind the lead is proposed for removal instead (`wrong_aliases`, 2026-10-29).
    assert calls == [] and [fm["kind"] for fm in _asked(memory)] == ["page_edit"]


def test_the_clarifier_never_proposes_a_related_pair_but_still_asks_about_people(tmp_path):
    memory = _bank(tmp_path)
    body = write_claims("## Summary\nA database.\n", [Claim(
        id="clm_inc", text="x", subject="example-db", predicate="includes", object="example-db-cloud",
        valid_from="2026-10-01", recorded_at="2026-10-01")])
    markdown_parser.write(memory / "entities" / "example-db.md", {"name": "Example DB", "type": "tool"}, body)
    clarifier = ClarificationManager(memory)
    assert clarifier.create("Example DB Cloud", EP, "Possible duplicate of Example DB",
                            "tool — could refer to the same entity as Example DB", 0.8, "ctx") is None
    assert clarifier.create("Example DB Cloud", EP, "Possible duplicate of Example DB",
                            "person — could refer to the same person as Example DB", 0.8, "ctx") is not None
    assert entity_relations.known(memory, "example-db-cloud", "example-db")
    assert not entity_relations.known(memory, "example-db-cloud", "other-page")


# ---------- a public pair is settled by a cited check ----------


def _git(memory, *args):
    return subprocess.run(["git", "-C", str(memory), *args], check=True, capture_output=True, text=True).stdout


@pytest.fixture
def bank(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_ALLOW_CONNECTOR_FETCH", "on")
    memory = _synthetic(tmp_path)
    for p in (memory / "inbox").glob("inbox-*.md"):
        p.unlink()
    _page(memory, "owner-example", type="person", owner=True, name="Owner Example")
    _page(memory, "example-db", type="tool", name="Example DB", body="## Summary\nA document database.\n")
    _page(memory, "example-db-cloud", type="tool", name="Example DB Cloud", body="## Summary\nA hosted database.\n")

    def item(item_id, entity_id, entity_name, target, cls="tool"):
        markdown_parser.write(memory / "inbox" / f"{item_id}.md", {
            "kind": "merge_suggestion", "status": "pending", "priority": 0.8, "required_input": "merge",
            "entity_id": entity_id, "entity_name": entity_name, "merge_target_hint": target,
            "title": f"Is {entity_name} the same as {target}?", "uncertainty_type": f"Possible duplicate of {target}",
            "suggested_classification": f"{cls} — could refer to the same entity as {target}",
            "created_date": "2026-10-28", "source_episode": EP}, "Context.")
    item("inbox-301", "example-db-cloud", "Example DB Cloud", "example-db")
    item("inbox-302", "alpha-project-notifications", "Alpha Project notifications", "example-db")
    item("inbox-303", "speed-pr-(#999)", "Speed PR (#999)", "example-db")
    item("inbox-304", "bob-example-2", "Bob Example", "example-db")
    item("inbox-305", "example-db-cloud", "Example DB Cloud", "bob-example", "person")
    _git(memory, "add", "-A")
    _git(memory, "commit", "-qm", "seed pairs")
    bank_index.invalidate()
    return memory


def test_only_a_pair_of_two_public_things_may_be_looked_up(bank):
    facts = web_settle.bank_facts(bank)
    why = {}
    for item_id in ("inbox-301", "inbox-302", "inbox-303", "inbox-304", "inbox-305"):
        parsed = markdown_parser.parse(bank / "inbox" / f"{item_id}.md")
        why[item_id] = web_settle.classify(bank, parsed.frontmatter, parsed.body, facts)
    assert why == {"inbox-301": ("public", "public"), "inbox-302": (None, "own_project"),
                   "inbox-303": (None, "private_file"), "inbox-304": (None, "person"), "inbox-305": (None, "person")}
    c = web_settle.candidate(bank, bank / "inbox" / "inbox-301.md", facts)
    assert web_settle.queries_for(c) == ("Example DB Cloud", "Example DB") and c.category == []


def _pair_fake(answer: dict, searched=("Example DB Cloud", "Example DB")):
    def fn(*, messages, web_search=False, timeout=None, **kw):
        assert web_search is True and messages[0]["content"] == web_lookup.PAIR_SYSTEM_PROMPT
        return {"choices": [{"message": {"content": json.dumps(answer)}}], "model": "fake-model",
                "tool_uses": [["WebSearch", {"query": q}] for q in searched]}
    return fn


def test_a_check_settles_a_pair_with_a_cited_relation_and_undo_takes_it_back(bank):
    answer = {"sure": True, "relation": "made_by", "url": DOCS, "quote": "Example DB Cloud is the hosted service "
              "run by the makers of Example DB."}
    report = asyncio.run(web_lookup.run_tail(bank, SimpleNamespace(web_check_per_run=8), user_triggered=True,
                                             llm_fn=_pair_fake(answer), engine=("resolved", "claude-cli", "plan")))
    assert report.settled == 1 and report.settled_items == ["inbox-301"]
    assert not (bank / "inbox" / "inbox-301.md").exists()
    rec = markdown_parser.parse(bank / "inbox" / "settled" / "inbox-301.md").frontmatter["settled"]
    assert (rec["relation"], rec["predicate"], rec["entity_id"], rec["pair"]) == (
        "made_by", "creates", "example-db", ["example-db-cloud", "example-db"])
    claims = parse_claims(markdown_parser.parse(bank / "entities" / "example-db.md").body)
    assert [(c.subject, c.predicate, c.object, c.origin) for c in claims] == [
        ("example-db", "creates", "example-db-cloud", "web-check")]
    assert claims[0].evidence[0].kind == "page"
    # The relation on the record keeps the pair from being asked again.
    assert ClarificationManager(bank).create("Example DB Cloud", EP, "Possible duplicate of Example DB",
                                             "tool — could refer to the same entity as Example DB", 0.8, "x") is None
    target, _paths, _lines = web_settle.undo(bank, "inbox-301")
    assert target == "inbox-301" and (bank / "inbox" / "inbox-301.md").exists()
    assert parse_claims(markdown_parser.parse(bank / "entities" / "example-db.md").body) == []
    assert markdown_parser.parse(bank / "inbox" / "inbox-301.md").frontmatter.get("web_check") == "undone"


@pytest.mark.parametrize("answer, searched, reason", [
    ({"sure": True, "relation": "same", "url": DOCS, "quote": "Example DB Cloud is Example DB."},
     ("Example DB Cloud",), "same"),                                   # a check never merges
    ({"sure": True, "relation": "made_by", "url": DOCS, "quote": "q"},
     ("Example DB Cloud pricing",), "query_strayed"),                  # a search for anything else settles nothing
    ({"sure": False}, ("Example DB",), "unsure"),
])
def test_a_check_that_finds_them_the_same_or_strays_settles_nothing(bank, answer, searched, reason):
    report = asyncio.run(web_lookup.run_tail(bank, SimpleNamespace(web_check_per_run=8), user_triggered=True,
                                             llm_fn=_pair_fake(answer, searched),
                                             engine=("resolved", "claude-cli", "plan")))
    assert report.settled == 0 and report.skipped == {reason: 1}
    assert (bank / "inbox" / "inbox-301.md").exists()


def test_the_generic_settle_refuses_a_pair(bank):
    with pytest.raises(web_settle.NotSettleable):
        web_settle.settle(bank, "inbox-301", ref=DOCS, quote="q", answer="a database", checker="agent",
                          checker_kind="agent")


def test_a_rejected_pair_stays_rejected(tmp_path):
    memory = _bank(tmp_path)
    merge_rejections.add_rejected(memory, "example-db-cloud", "example-db")
    assert ClarificationManager(memory).create("Example DB Cloud", EP, "Possible duplicate of Example DB",
                                               "tool — x", 0.8, "ctx") is None


# ---------- review of #545 ----------


def test_b1_a_pair_never_cleared_is_asked_and_never_also_a_relation(tmp_path, monkeypatch):
    """The reviewer's repro: a close spelling sharing an alias is never cleared by the judge alone — its `related`
    verdict reads as unsure, so the pair is asked; the raw verdict in the cache must not also write a claim."""
    memory = _bank(tmp_path)
    mention = _entity("Talvik", "tool", EP, TS)
    mention["aliases"] = ["Tal"]
    out = _resolve(memory, [{"episode_id": EP, "entities": [mention], "relationships": []}],
                   [_tool_page("talwyk", "Talwyk", aliases=["Tal"])], monkeypatch, "related:has_version")
    asked = [(fm["kind"], fm["merge_target_hint"]) for fm in _asked(memory)]
    assert asked == [("merge_suggestion", "talwyk")]
    assert out["relations"] == []


def test_b2_unsure_about_one_page_holds_and_asks_though_another_reads_as_its_whole(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    mention = _entity("Faster loading work", "project", EP, TS)
    pages = [_project_page("example-app", "Example App"), _project_page("example-tool", "Example Tool")]

    async def judge(*_a, **k):
        return "unsure" if k.get("existing_name") == "Example App" else "related:part_of"

    async def batch(new_name, new_type, new_description, entries, settings, *, new_connections=""):
        return ["unsure" if e["name"] == "Example App" else "related:part_of" for e in entries]
    monkeypatch.setattr(entity_resolver.SqliteVecIndexer, "_rebuild_pending_index", lambda self, entries: None)
    monkeypatch.setattr(entity_resolver, "_llm_judge_same_entity", judge)
    monkeypatch.setattr(entity_resolver, "_llm_judge_batch", batch)
    out = asyncio.run(entity_resolver.resolve([{"episode_id": EP, "entities": [mention], "relationships": []}],
                                              pages, _settings(memory)))
    assert not any(c["id"] in ("example-app", "example-tool") for c in out["changes"])   # held, never landed
    assert out["name_to_id"].get("faster loading work") not in ("example-app", "example-tool")


def _write_pages(memory, pages):
    for page in pages:
        markdown_parser.write(memory / "entities" / f"{page['id']}.md", page["frontmatter"], page["body"])


@pytest.mark.parametrize("case", ["judged_different", "open_question", "rejected"])
def test_b3_a_second_batch_makes_no_judge_call_for_a_lead_already_settled(tmp_path, monkeypatch, case):
    entity_resolver._LEAD_VERDICTS.clear()
    memory = _bank(tmp_path)
    pages = _lead_pages()
    _write_pages(memory, pages)
    if case == "rejected":
        merge_rejections.add_rejected(memory, "example-db", "example-db-cloud")
    verdict = "unsure" if case == "open_question" else "different"
    extracted = [{"episode_id": EP, "entities": [_entity("Example DB", "tool", EP, TS)], "relationships": []}]
    first: list = []
    _resolve(memory, extracted, pages, monkeypatch, verdict, first)
    if case == "open_question":
        assert len(_asked(memory)) == 1
    second: list = []
    _resolve(memory, extracted, pages, monkeypatch, verdict, second)
    assert second == []
    if case == "rejected":
        # No question; the alias that made them meet is proposed for removal, once (`wrong_aliases`, 2026-10-29).
        assert first == [] and [fm["kind"] for fm in _asked(memory)] == ["page_edit"]


def test_the_direction_guard_drops_a_reversed_relation():
    assert not entity_relations.plausible("has_version", "Example Robot Head", "Example Robot")
    assert not entity_relations.plausible("version_of", "Example Robot", "Example Robot Head")
    assert entity_relations.plausible("part_of", "Example Robot Head", "Example Robot")
    assert entity_relations.plausible("made_by", "Example DB Cloud", "Example DB")
    assert not entity_relations.plausible("makes", "Example DB Cloud", "Example DB")
    assert entity_relations.plausible("alternative_to", "Example DB Cloud", "Example DB")


def test_a_reversed_judge_relation_writes_no_claim(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    out = _resolve(memory, [{"episode_id": EP, "entities": [_entity("Example DB Cloud", "tool", EP, TS)],
                             "relationships": []}], [_tool_page("example-db", "Example DB")], monkeypatch,
                   "related:makes")
    assert out["relations"] == [] and _asked(memory) == []


def test_the_dry_run_refuses_a_live_bank_or_an_output_in_the_repo(tmp_path):
    from api.scripts import duplicate_questions_dry_run as dry

    root = tmp_path / "memory-root"
    (root / "entities").mkdir(parents=True)
    copy = tmp_path / "copy"
    settings = SimpleNamespace(memory_root=root)
    assert dry.refusal(copy, tmp_path / "out", settings) is None
    assert "inside the repository" in dry.refusal(dry.REPO / "memory", tmp_path / "out", settings)
    assert "--out is inside the repository" in dry.refusal(copy, dry.REPO / "tmp-out", settings)
    assert "configured memory root" in dry.refusal(root, tmp_path / "out", settings)
    assert "configured memory root" in dry.refusal(root / "banks" / "b", tmp_path / "out", settings)
    (copy / "entities").mkdir(parents=True)
    (copy / "inbox").mkdir()
    assert dry.main(["--bank", str(dry.REPO / "memory"), "--out", str(tmp_path / "o")]) == 2
