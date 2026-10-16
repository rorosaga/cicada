"""A web lookup settles inbox questions about public things (owner ruling 2026-10-16, G61; amends the S3 rail).

"A web lookup answers 'what is X' for public things and closes the question. The answer is saved with its link and
quote, and you can undo it from a 'Settled by a check' list. Never searched: people's names, your own files, your
projects, your life. Runs from your Claude plan in runs you start; a scheduled metered run costs a few cents more."

Synthetic banks only (example-film, tool-a, bob-example, alice-example, <owner>); the search tool is a fake; git is
real; nothing reaches a network or a paid API."""
from __future__ import annotations

import json
import subprocess
from datetime import date
from types import SimpleNamespace

import pytest

from _synthetic_bank import _bank, _entity
from api.services import (agent_engine, agent_stream, bank_index, engine_select, evidence, fact_sources, inbox_service,
                          markdown_parser, pending_store, providers, web_lookup, web_settle)
from api.services.claims import Claim, parse_claims, write_claims

FILM_URL = "https://films.film-example.net/example-film"
TOOL_URL = "https://docs.tool-example.dev/tool-a"
SECRET = "said over dinner with alice-example about secret-phrase-xyz"


def _git(memory, *args):
    return subprocess.run(["git", "-C", str(memory), *args], check=True, capture_output=True, text=True).stdout


def _commit(memory, msg="seed"):
    _git(memory, "add", "-A")
    _git(memory, "commit", "-qm", msg)
    bank_index.invalidate()


def _item(memory, item_id, **fm):
    body = fm.pop("body", "Context.")
    base = {"status": "pending", "priority": 0.5, "created_date": "2026-09-01", "allow_other": True,
            "allow_defer": True}
    base.update(fm)
    markdown_parser.write(memory / "inbox" / f"{item_id}.md", base, body)


@pytest.fixture
def bank(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_ALLOW_CONNECTOR_FETCH", "on")
    memory = _bank(tmp_path)
    for p in (memory / "inbox").glob("inbox-*.md"):
        p.unlink()
    _entity(memory, "owner-example", type="person", owner=True, name="Owner Example")
    _entity(memory, "alice-example", type="person", name="Alice Example", aliases=["Ali"])
    _entity(memory, "example-film", type="media", name="Example Film", body="## Summary\nA film.\n")
    tool_body = write_claims("## Summary\nA tool.\n", [
        Claim(id="clm_h", text="Tool A is an agent harness", subject="tool-a", predicate="description",
              object="agent harness", valid_from="2026-05-01", recorded_at="2026-05-01"),
        Claim(id="clm_g", text="Tool A is an AI agent", subject="tool-a", predicate="description",
              object="AI agent", valid_from="2026-08-01", recorded_at="2026-08-01"),
    ])
    _entity(memory, "tool-a", type="tool", name="Tool A", body=tool_body)
    # 101: a film with a page — public.
    _item(memory, "inbox-101", kind="clarification", entity_id="example-film", entity_name="Example Film",
          title="Who or what is Example Film?", suggested_classification="media — a film", body=SECRET)
    # 102: a tool conflict on a world-truth predicate — public.
    _item(memory, "inbox-102", kind="conflict", entity_id="tool-a", entity_name="Tool A", predicate="description",
          question="Is Tool A an agent harness or an AI agent?", title="Is Tool A an agent harness or an AI agent?",
          options=[{"key": "a", "label": "agent harness", "claim_id": "clm_h"},
                   {"key": "b", "label": "AI agent", "claim_id": "clm_g"}])
    # 103: a paper with no page yet, held on its pending line — public.
    pending_store.upsert(memory, pending_store.PendingEntity(name="2401.00001", type="media", description="a paper", source_episode="ep_2026-09-01_001", confidence=0.4, tags=[], history_entries=[]))
    _item(memory, "inbox-103", kind="clarification", entity_id="2401-00001", entity_name="2401.00001",
          title="Who or what is 2401.00001?", suggested_classification="media — a research paper on retrieval")
    # Never searched:
    _item(memory, "inbox-201", kind="clarification", entity_id="bob-example", entity_name="Bob Example",
          title="Who or what is Bob Example?", suggested_classification="person — a friend")
    _item(memory, "inbox-202", kind="clarification", entity_id="carol-example", entity_name="Carol Example",
          title="Who or what is Carol Example?", suggested_classification="concept — her friend from school")
    _item(memory, "inbox-203", kind="clarification", entity_id="plan-md", entity_name="plan.md",
          title="Who or what is plan.md?", suggested_classification="concept — a file")
    _item(memory, "inbox-204", kind="conflict", entity_id="owner-example", entity_name="Owner Example",
          predicate="is-a", options=[{"key": "a", "label": "x"}, {"key": "b", "label": "y"}])
    _item(memory, "inbox-205", kind="clarification", entity_id="alpha-project", entity_name="Alpha Project",
          title="Who or what is Alpha Project?", suggested_classification="project — a project")
    _item(memory, "inbox-206", kind="clarification", entity_id="ali", entity_name="Ali",
          title="Who or what is Ali?", suggested_classification="concept — a name")
    _item(memory, "inbox-207", kind="conflict", entity_id="tool-a", entity_name="Tool A", predicate="uses",
          options=[{"key": "a", "label": "python"}, {"key": "b", "label": "rust"}])
    # Repo state: answered from the commit by a trusted local agent, never searched.
    _item(memory, "inbox-301", kind="clarification", entity_id="beta-project", entity_name="Beta Project",
          title="Did PR #42 merge?", question="Did PR #42 merge?", suggested_classification="project — x")
    _commit(memory)
    return memory


def _fake(answer_for, *, strayed=False, calls=None):
    """A fake engine with a fake search tool: it records each prompt and returns the searches it 'made'."""
    def fn(*, messages, web_search=False, timeout=None, **kw):
        assert web_search is True
        user = messages[-1]["content"]
        if calls is not None:
            calls.append(messages)
        query = user.split("Search query (use exactly this): ", 1)[1].split("\n", 1)[0]
        searched = query + (" alice-example" if strayed else "")
        content = json.dumps(answer_for(user))
        return {"choices": [{"message": {"content": content}}], "model": "fake-model",
                "tool_uses": [["WebSearch", {"query": searched}]]}
    return fn


def _answers(user: str) -> dict:
    if "Tool A" in user:
        return {"sure": True, "option_key": "a", "others_ruled_out": True, "url": TOOL_URL,
                "quote": "Tool A is a harness that runs agents."}
    if "Example Film" in user:
        return {"sure": True, "answer": "a 2019 science-fiction film", "url": FILM_URL,
                "quote": "Example Film is a 2019 science-fiction film."}
    return {"sure": False}


def _settings(**over):
    return SimpleNamespace(web_check_per_run=over.pop("cap", 8), **over)


def _run(memory, fn, *, engine=("resolved", "claude-cli", "plan"), user_triggered=True, **kw):
    import asyncio

    settings = _settings(**kw)
    return asyncio.run(web_lookup.run_tail(memory, settings, user_triggered=user_triggered, llm_fn=fn,
                                           engine=engine))


# ---------- which questions may be looked up ----------


def test_the_filter_searches_a_film_a_paper_and_a_tool_and_never_a_person_a_file_the_owner_or_a_project(bank):
    facts = web_settle.bank_facts(bank)
    scope = {}
    for p in sorted((bank / "inbox").glob("inbox-*.md")):
        parsed = markdown_parser.parse(p)
        scope[p.stem] = web_settle.classify(bank, parsed.frontmatter, parsed.body, facts)
    assert {k: v[0] for k, v in scope.items() if v[0] == "public"} == {
        "inbox-101": "public", "inbox-102": "public", "inbox-103": "public"}
    assert scope["inbox-201"] == (None, "person")          # a typed person
    assert scope["inbox-202"] == (None, "person_context")  # an untyped name the description says is someone
    assert scope["inbox-203"] == (None, "private_file")    # the person's own file
    assert scope["inbox-204"] == (None, "owner")           # the owner's page
    assert scope["inbox-205"] == (None, "private_type")    # a project
    assert scope["inbox-206"] == (None, "person")          # an alias of a person page
    assert scope["inbox-207"] == (None, "informational")   # a multi-valued predicate (not what it IS): both may be true
    assert scope["inbox-301"][0] == "repo"                 # repo state: never a web search


def test_the_query_is_the_name_and_a_category_word_and_the_items_own_text_never_reaches_the_engine(bank):
    film = web_settle.candidate(bank, bank / "inbox" / "inbox-101.md", web_settle.bank_facts(bank))
    assert web_settle.query_for(film) == "Example Film film"
    calls: list = []
    _run(bank, _fake(_answers, calls=calls))
    sent = json.dumps(calls)
    assert calls, "the public questions were looked up"
    for word in ("secret-phrase-xyz", "dinner", "alice-example", "Alice Example", "Owner Example", "Bob Example",
                 "plan.md", "Alpha Project", "PR #42"):
        assert word not in sent, word


# ---------- settling, the citation and the two tiers ----------


def test_a_lookup_settles_with_a_cited_claim_and_never_touches_the_pages_sources(bank, monkeypatch):
    import asyncio

    from api.services import sleep_cycle

    async def engine(settings, *, user_triggered):
        return "resolved", "claude-cli", "plan"
    monkeypatch.setattr(web_lookup, "engine_for", engine)
    monkeypatch.setattr(web_lookup, "default_llm_fn", lambda resolved: _fake(_answers))
    monkeypatch.setattr(sleep_cycle._state, "cycle_id", "cyc-web-test")
    monkeypatch.setattr(sleep_cycle._state, "drain", None)
    asyncio.run(sleep_cycle._web_check_safely(bank, _settings(), user_triggered=True))
    # the question left the inbox and is listed under "Settled by a check"
    assert not (bank / "inbox" / "inbox-101.md").exists()
    rows = {r["id"]: r for r in web_settle.list_settled(bank)}
    assert set(rows) == {"inbox-101", "inbox-102"}
    film = rows["inbox-101"]
    assert (film["ref"], film["host"], film["answer"]) == (FILM_URL, "films.film-example.net", "a 2019 science-fiction film")
    # the claim: the agent's, external, its evidence a page-kind span into the web-check episode that holds the link
    page = markdown_parser.parse(bank / "entities" / "example-film.md")
    (claim,) = [c for c in parse_claims(page.body) if c.id == film["claim_id"]]
    assert (claim.observer, claim.source_trust, claim.origin, claim.object) == (
        "agent", "external", "web-check", "a 2019 science-fiction film")
    (ev,) = claim.evidence
    assert ev.kind == "page" and ev.episode == film["episode"]
    text = evidence.source_text(bank, ev.episode)
    assert text[ev.start:ev.end] == "Example Film is a 2019 science-fiction film."
    assert FILM_URL in text, "the link is shown where the claim's evidence shows"
    from api.services import episode_time

    ep_fm = markdown_parser.parse(bank / "episodes" / f"{ev.episode}.md").frontmatter
    assert ep_fm["source"] == "web-check" and not episode_time.counts_as_activity(ep_fm), "a lookup is not a mention"
    # two tiers: a citation is never a tracked source — no sources entry, no trust, no logo
    assert fact_sources.list_sources(bank, "example-film") == []
    assert "sources" not in page.frontmatter
    # one commit, under the model that looked, with the engine trailer
    log = _git(bank, "log", "-1", "--format=%s%n%b")
    assert log.startswith("Web check ") and "Cicada-Author: fake-model" in log and "Cicada-Engine: claude-cli" in log
    assert _git(bank, "status", "--porcelain").strip() == ""


def test_a_conflict_settle_closes_the_other_option_and_undo_restores_exactly_what_it_changed(bank):
    before_page = (bank / "entities" / "tool-a.md").read_text()
    before_item = markdown_parser.parse(bank / "inbox" / "inbox-102.md")
    _run(bank, _fake(_answers))
    claims = {c.id: c for c in parse_claims(markdown_parser.parse(bank / "entities" / "tool-a.md").body)}
    settled = next(r for r in web_settle.list_settled(bank) if r["id"] == "inbox-102")
    assert claims["clm_g"].valid_to == date.today().isoformat()
    assert claims["clm_g"].superseded_by == settled["claim_id"]
    assert claims["clm_h"].valid_to is None, "the winning option's own claim is left as it was"
    target, paths, _lines = web_settle.undo(bank, "inbox-102")
    assert target == "inbox-102"
    assert (bank / "entities" / "tool-a.md").read_text() == before_page
    restored = markdown_parser.parse(bank / "inbox" / "inbox-102.md")
    assert restored.frontmatter.pop("web_check") == "undone", "the person took it back: no check settles it again"
    assert (restored.frontmatter, restored.body) == (before_item.frontmatter, before_item.body)
    assert "inbox-102" not in {r["id"] for r in web_settle.list_settled(bank)}
    assert "inbox-102" in {i.id for i in inbox_service.load_inbox(bank)}


def test_a_held_paper_is_settled_on_its_pending_line_and_undone_from_it(bank):
    def answers(user):
        if "2401.00001" in user:
            return {"sure": True, "answer": "a paper on dense retrieval", "url": "https://papers.paper-example.net/2401",
                    "quote": "We present a dense retrieval method."}
        return {"sure": False}
    report = _run(bank, _fake(answers))
    assert report.settled == 1
    assert not (bank / "entities" / "2401-00001.md").exists(), "a lookup never creates a page"
    (line,) = [e for e in pending_store.load(bank) if e.name == "2401.00001"]
    assert [d["object"] for d in line.held_claims] == ["a paper on dense retrieval"]
    web_settle.undo(bank, "inbox-103")
    (line,) = [e for e in pending_store.load(bank) if e.name == "2401.00001"]
    assert line.held_claims == []


def test_a_search_that_strays_from_the_pinned_query_settles_nothing(bank):
    report = _run(bank, _fake(_answers, strayed=True))
    assert report.settled == 0 and report.skipped.get("query_strayed") == 3
    assert web_settle.list_settled(bank) == []


def test_no_search_at_all_is_no_lookup():
    c = web_settle.Candidate("inbox-1", "clarification", "public", "x", "X", "media", True, "description", [], [])
    assert not web_lookup.queries_ok([], "X")
    assert web_lookup.queries_ok(["x"], "X") and not web_lookup.queries_ok(["X", "X", "X"], "X")
    assert web_lookup.parse_answer(c, '{"sure": true, "answer": "a thing"}').reason == "no_citation"


# ---------- gates, ruling 4, caps ----------


def test_the_connector_gate_stops_the_lookup_before_any_call(bank, monkeypatch):
    monkeypatch.setenv("CICADA_ALLOW_CONNECTOR_FETCH", "off")
    calls: list = []
    report = _run(bank, _fake(_answers, calls=calls))
    assert report.reason == "gate" and calls == []


def test_ruling_4_a_scheduled_run_never_uses_a_plan_but_may_use_a_metered_search(bank, monkeypatch):
    import asyncio
    import litellm

    async def plan(settings, registry=None, *, user_triggered=True):
        return SimpleNamespace(llm_mode="agent"), "pinned"
    monkeypatch.setattr(engine_select, "resolve_settings", plan)
    resolved, _label, why = asyncio.run(web_lookup.engine_for(object(), user_triggered=False))
    assert resolved is None and why == "scheduled_plan"
    resolved, _label, why = asyncio.run(web_lookup.engine_for(object(), user_triggered=True))
    assert resolved is not None and why == "plan"

    async def metered(settings, registry=None, *, user_triggered=True):
        return SimpleNamespace(llm_mode="byok", litellm_model="anthropic/claude-x"), "byok"
    monkeypatch.setattr(engine_select, "resolve_settings", metered)
    monkeypatch.setattr(litellm, "supports_web_search", lambda model: True)
    resolved, _label, why = asyncio.run(web_lookup.engine_for(object(), user_triggered=False))
    assert resolved is not None and why == "metered"
    monkeypatch.setattr(litellm, "supports_web_search", lambda model: False)
    assert asyncio.run(web_lookup.engine_for(object(), user_triggered=False))[2] == "no_search_tool"

    # and a scheduled run with only a plan looks nothing up
    monkeypatch.setattr(engine_select, "resolve_settings", plan)
    calls: list = []
    import asyncio as _a
    report = _a.run(web_lookup.run_tail(bank, _settings(), user_triggered=False, llm_fn=_fake(_answers, calls=calls)))
    assert report.reason == "scheduled_plan" and calls == []


def test_the_per_run_cap_and_the_thirty_day_memo(bank):
    calls: list = []
    report = _run(bank, _fake(lambda u: {"sure": False}, calls=calls), cap=1)
    assert report.looked_up == 1 and len(calls) == 1
    calls.clear()
    _run(bank, _fake(lambda u: {"sure": False}, calls=calls), cap=8)
    assert len(calls) == 2, "the question looked up and left open is not looked up again within 30 days"


# ---------- the person's own agent: cicada_record_check(outcome="settles") ----------


@pytest.fixture
def server(bank, monkeypatch):
    from _stdio_server import stdio_server
    from api.services import mcp_tools

    srv = stdio_server()
    monkeypatch.setattr(srv, "get_memory_path", lambda: bank)
    monkeypatch.setattr(srv, "SESSION", srv.SessionIdentity("ses_web_fixed", "claude-code", None))
    monkeypatch.setattr(mcp_tools, "_backend_sleep_running", lambda *a, **k: False)
    mcp_tools._SETTLES_BY_SESSION.clear()
    return srv


def test_an_agent_settles_a_public_question_with_a_found_page_and_quote(server, bank):
    out = server.handle_tool("cicada_record_check", {
        "item_id": "inbox-101", "source": FILM_URL, "outcome": "settles",
        "proposed_value": "a 2019 science-fiction film", "quotes": [{"quote": "Example Film is a 2019 film."}]})
    assert out.startswith("Settled inbox-101"), out
    (row,) = web_settle.list_settled(bank)
    assert (row["settled_by"], row["settled_by_kind"]) == ("claude-code", "agent")
    log = _git(bank, "log", "-1", "--format=%s%n%b")
    assert "Cicada-Author: claude-code" in log and "Cicada-Session: ses_web_fixed" in log


def test_an_agent_cannot_settle_a_person_a_walled_page_or_without_a_quote(server, bank):
    person = server.handle_tool("cicada_record_check", {
        "item_id": "inbox-201", "source": FILM_URL, "outcome": "settles", "proposed_value": "a friend",
        "quotes": [{"quote": "x"}]})
    assert person.startswith("Not recorded") and "person" in person
    walled = server.handle_tool("cicada_record_check", {
        "item_id": "inbox-101", "source": "https://www.linkedin.com/in/someone", "outcome": "settles",
        "proposed_value": "a film", "quotes": [{"quote": "x"}]})
    assert walled.startswith("Not recorded")
    bare = server.handle_tool("cicada_record_check", {
        "item_id": "inbox-101", "source": FILM_URL, "outcome": "settles", "proposed_value": "a film"})
    assert bare.startswith("Not recorded") and "quote" in bare
    assert web_settle.list_settled(bank) == []
    assert (bank / "inbox" / "inbox-101.md").exists()


def test_a_repo_question_is_settled_only_from_a_commit_by_a_trusted_local_agent(server, bank):
    url = server.handle_tool("cicada_record_check", {
        "item_id": "inbox-301", "source": FILM_URL, "outcome": "settles", "proposed_value": "merged",
        "quotes": [{"quote": "Merge pull request #42"}]})
    assert url.startswith("Not recorded") and "commit" in url
    ok = server.handle_tool("cicada_record_check", {
        "item_id": "inbox-301", "source": "commit:abc1234", "outcome": "settles", "proposed_value": "merged",
        "quotes": [{"quote": "Merge pull request #42"}]})
    assert ok.startswith("Settled inbox-301"), ok


def test_a_remote_connection_never_settles(bank):
    from api.services import mcp_tools

    ctx = SimpleNamespace(is_remote=True)
    out = mcp_tools._record_settle(ctx, bank, "inbox-101", FILM_URL, None, "a film", [{"quote": "x"}])
    assert out.startswith("Not recorded") and "never settles" in out


def test_check_nudges_names_the_settle_path_only_for_a_public_question(server, bank):
    from api.services import mcp_tools

    ctx = SimpleNamespace(is_remote=False, author="claude-code", can=lambda tool: True)
    film = mcp_tools._settle_lines(ctx, bank, "inbox-101")
    assert film and 'search only "Example Film film"' in film[0] and 'outcome="settles"' in film[0]
    assert mcp_tools._settle_lines(ctx, bank, "inbox-201") == []


# ---------- telemetry, the route, the engine seam ----------


def test_the_ledger_rows_are_ids_and_enums_only(bank, monkeypatch):
    from api.services import telemetry

    monkeypatch.setenv("CICADA_TELEMETRY", "on")
    _run(bank, _fake(_answers))
    rows = [json.loads(line) for f in telemetry.telemetry_dir().glob("*.jsonl") for line in f.read_text().splitlines()]
    web = [r for r in rows if r.get("kind") == "web_check"]
    assert {r["refs"]["action"] for r in web} == {"settle", "skip"}
    blob = json.dumps(web)
    for text in (FILM_URL, "films.film-example.net", "Example Film film", "science-fiction", "secret-phrase-xyz"):
        assert text not in blob


def test_the_settled_list_and_undo_routes(bank, monkeypatch):
    from fastapi.testclient import TestClient

    from api import config, main

    _run(bank, _fake(_answers))
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    config.get_settings.cache_clear()
    try:
        with TestClient(main.app) as client:
            rows = client.get("/inbox/settled").json()
            assert {r["id"] for r in rows} == {"inbox-101", "inbox-102"}
            assert {"ref", "quote", "answer", "hasPage", "settledByKind"} <= set(rows[0])
            assert client.post("/inbox/settled/inbox-101/undo").json() == {"status": "reopened", "id": "inbox-101"}
            assert client.post("/inbox/settled/inbox-101/undo").status_code == 404
            assert {r["id"] for r in client.get("/inbox/settled").json()} == {"inbox-102"}
    finally:
        config.get_settings.cache_clear()
    log = _git(bank, "log", "-3", "--format=%s%n%b")
    assert "Web check undone" in log and "Cicada-Author: user" in log
    assert (bank / "inbox" / "inbox-101.md").exists()


def test_a_new_question_never_takes_a_settled_questions_number(bank):
    _run(bank, _fake(_answers))
    nums = [int(p.stem.split("-")[1]) for p in (bank / "inbox" / "settled").glob("inbox-*.md")]
    assert inbox_service.next_inbox_num(bank / "inbox") > max(nums)


def test_the_plan_call_gets_the_web_search_as_its_only_tool():
    plain = agent_engine.build_argv(model="sonnet", system_prompt="s")
    assert plain[plain.index("--tools") + 1] == "" and "--allowedTools" not in plain
    argv = agent_engine.build_argv(model="sonnet", system_prompt="s", tools=("WebSearch",))
    assert argv[argv.index("--tools") + 1] == "WebSearch"
    assert argv[argv.index("--allowedTools") + 1] == "WebSearch"
    with pytest.raises(ValueError):
        agent_engine.build_argv(model="sonnet", system_prompt="s", tools=("Bash",))
    stream = agent_stream.parse_stream("\n".join([
        json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "WebSearch", "input": {"query": "Example Film film"}}]}}),
        json.dumps({"type": "result", "result": "{}", "usage": {}}),
    ]))
    assert stream.tool_uses == [("WebSearch", {"query": "Example Film film"})]


def test_a_metered_call_asks_the_provider_for_one_search(monkeypatch):
    seen = {}

    def completion(**kw):
        seen.update(kw)
        return {"choices": [{"message": {"content": "{}"}}], "usage": {}}
    settings = SimpleNamespace(llm_mode="byok", litellm_model="anthropic/claude-x", ollama_model="x",
                               ollama_base_url="http://localhost", openrouter_app_url=None, openrouter_app_name=None)
    fn = providers.resolve_llm_fn(settings, stage="web_check", completion=completion, sink=lambda e: None, bank="b")
    fn(messages=[{"role": "user", "content": "q"}], web_search=True)
    assert seen["web_search_options"] == {"search_context_size": "low"} and "web_search" not in seen
    seen.clear()
    fn(messages=[{"role": "user", "content": "q"}])
    assert "web_search_options" not in seen


# ---------- what a thing IS: type / is-a conflicts (owner, 2026-10-16) ----------


def _type_item(memory, item_id="inbox-108", **over):
    """The owner's own example's shape: "Is <tool-b> an agent harness for running models or an AI agent itself?" — an
    ``is-a`` conflict (multi-valued in the vocabulary) with the item's "Both are true (different contexts)" option."""
    body = write_claims("## Summary\nA tool.\n", [
        Claim(id="clm_th", text="Tool B is an agent harness", subject="tool-b", predicate="is-a",
              object="agent harness for running models", valid_from="2026-05-01", recorded_at="2026-05-01"),
        Claim(id="clm_ta", text="Tool B is an AI agent", subject="tool-b", predicate="is-a",
              object="AI agent itself", valid_from="2026-08-01", recorded_at="2026-08-01"),
    ])
    if not (memory / "entities" / "tool-b.md").exists():
        _entity(memory, "tool-b", type="tool", name="Tool B", body=body)
    fm = dict(kind="conflict", entity_id="tool-b", entity_name="Tool B", predicate="is-a",
              question="Is Tool B an agent harness for running models or an AI agent itself?",
              title="Is Tool B an agent harness for running models or an AI agent itself?",
              options=[{"key": "a", "label": "agent harness for running models", "claim_id": "clm_th"},
                       {"key": "b", "label": "AI agent itself", "claim_id": "clm_ta"},
                       {"key": "both", "label": "Both are true (different contexts)", "claim_id": None}])
    fm.update(over)
    _item(memory, item_id, **fm)
    _commit(memory, f"seed {item_id}")


def _only_tool_b(answer):
    return lambda user: answer if "Tool B" in user else {"sure": False}


def test_an_is_a_conflict_is_eligible_and_its_prompt_offers_the_items_own_both_option(bank):
    from api.services import predicates

    assert predicates.cardinality(bank, "is-a") == "multi", "the shape under test: a multi-valued type predicate"
    _type_item(bank)
    parsed = markdown_parser.parse(bank / "inbox" / "inbox-108.md")
    assert web_settle.classify(bank, parsed.frontmatter, parsed.body, web_settle.bank_facts(bank)) == (
        "public", "public")
    c = web_settle.candidate(bank, bank / "inbox" / "inbox-108.md", web_settle.bank_facts(bank))
    assert c.type_question and c.both_key == "both"
    assert c.options == [("a", "agent harness for running models"), ("b", "AI agent itself")]
    user = web_lookup.build_messages(c)[-1]["content"]
    assert "option_key 'both'" in user and "rule out every other option" in user
    # What the thing IS is the question: no category word would answer it, so the query is the bare name (2026-10-16).
    assert web_settle.query_for(c) == "Tool B"


def test_a_page_that_supports_both_settles_on_both_with_one_cited_claim_each_and_nothing_closed(bank):
    _type_item(bank)
    before_page = (bank / "entities" / "tool-b.md").read_text()
    report = _run(bank, _fake(_only_tool_b({
        "sure": True, "option_key": "both", "url": TOOL_URL,
        "quote": "Tool B is an agent harness for running models and an AI agent itself."})))
    assert report.settled == 1
    (row,) = [r for r in web_settle.list_settled(bank) if r["id"] == "inbox-108"]
    claims = {c.id: c for c in parse_claims(markdown_parser.parse(bank / "entities" / "tool-b.md").body)}
    assert claims["clm_th"].valid_to is None and claims["clm_ta"].valid_to is None, "both hold: nothing closes"
    web = [c for c in claims.values() if c.origin == "web-check"]
    assert sorted(c.object for c in web) == ["AI agent itself", "agent harness for running models"]
    assert all(c.observer == "agent" and c.evidence[0].kind == "page" for c in web)
    rec = markdown_parser.parse(bank / "inbox" / "settled" / "inbox-108.md").frontmatter["settled"]
    assert sorted(rec["claim_ids"]) == sorted(c.id for c in web)
    web_settle.undo(bank, "inbox-108")
    assert (bank / "entities" / "tool-b.md").read_text() == before_page, "undo takes back every claim it wrote"


def test_one_option_settles_a_type_question_only_when_the_page_rules_the_others_out(bank):
    _type_item(bank)
    quote = "Tool B is an agent harness for running models; it is not an agent itself."
    loose = _run(bank, _fake(_only_tool_b({"sure": True, "option_key": "a", "url": TOOL_URL, "quote": quote})))
    assert loose.skipped.get("not_exclusive") == 1 and (bank / "inbox" / "inbox-108.md").exists()
    # an option the item does not have is never settled on
    _type_item(bank, item_id="inbox-109")
    invented = _run(bank, _fake(_only_tool_b({"sure": True, "option_key": "c", "others_ruled_out": True,
                                               "url": TOOL_URL, "quote": quote})))
    assert invented.skipped.get("no_option") == 1 and (bank / "inbox" / "inbox-109.md").exists()
    _type_item(bank, item_id="inbox-110")
    strict = _run(bank, _fake(_only_tool_b({"sure": True, "option_key": "a", "others_ruled_out": True,
                                             "url": TOOL_URL, "quote": quote})))
    assert strict.settled == 1
    claims = {c.id: c for c in parse_claims(markdown_parser.parse(bank / "entities" / "tool-b.md").body)}
    assert claims["clm_ta"].valid_to == date.today().isoformat(), "the ruled-out option closes"
    assert claims["clm_th"].valid_to is None


def test_a_both_answer_is_refused_where_the_item_has_no_both_option():
    c = web_settle.Candidate("inbox-1", "conflict", "public", "x", "X", "tool", True, "is-a",
                             [("a", "one"), ("b", "two")], [], type_question=True, both_key=None)
    a = web_lookup.parse_answer(c, json.dumps({"sure": True, "option_key": "both", "url": TOOL_URL, "quote": "q"}))
    assert (a.ok, a.reason) == (False, "no_option")


def test_an_option_label_that_names_a_person_or_says_my_keeps_the_question_home(bank):
    facts = web_settle.bank_facts(bank)
    base = dict(kind="conflict", status="pending", entity_id="tool-a", entity_name="Tool A", predicate="made-by")
    named = {**base, "options": [{"key": "a", "label": "built by Alice Example and her team"},
                                 {"key": "b", "label": "Acme Example"}]}
    assert web_settle.classify(bank, named, "", facts) == (None, "person")
    mine = {**base, "options": [{"key": "a", "label": "my side project"}, {"key": "b", "label": "Acme Example"}]}
    assert web_settle.classify(bank, mine, "", facts) == (None, "personal")
    owner_in_name = {**base, "entity_name": "Owner Example Toolkit",
                     "options": [{"key": "a", "label": "x1"}, {"key": "b", "label": "y1"}]}
    assert web_settle.classify(bank, owner_in_name, "", facts) == (None, "person")


def test_an_undone_question_is_never_settled_again(server, bank):
    _run(bank, _fake(_answers))
    web_settle.undo(bank, "inbox-101")
    parsed = markdown_parser.parse(bank / "inbox" / "inbox-101.md")
    assert web_settle.classify(bank, parsed.frontmatter, parsed.body, web_settle.bank_facts(bank)) == (
        None, "undone")
    out = server.handle_tool("cicada_record_check", {
        "item_id": "inbox-101", "source": FILM_URL, "outcome": "settles",
        "proposed_value": "a film", "quotes": [{"quote": "Example Film is a film."}]})
    assert out.startswith("Not recorded")


def test_every_inbox_allocator_skips_a_settled_number(bank):
    from api.services import clarification_manager, inbox_generator, inbox_migration, role_people

    _run(bank, _fake(_answers))
    top = max(int(p.stem.split("-")[1]) for p in (bank / "inbox" / "settled").glob("inbox-*.md"))
    for p in (bank / "inbox").glob("inbox-*.md"):
        p.unlink()
    inbox = bank / "inbox"
    assert inbox_service.next_inbox_num(inbox) > top
    assert inbox_generator._next_inbox_num(inbox) > top
    assert inbox_migration._next_inbox_num(inbox) > top
    assert int(role_people._next_item(inbox).stem.split("-")[1]) > top
    cm = clarification_manager.ClarificationManager.__new__(clarification_manager.ClarificationManager)
    cm.dir = inbox
    assert int(cm._next_id().split("-")[1]) > top


# ---------- a metered engine searches only where litellm reports the search ----------


def test_a_metered_engine_whose_searches_go_unreported_skips_before_any_paid_call(bank, monkeypatch):
    """OpenRouter (the owner's scheduled engine) and OpenAI's search models report no query, so the pinned-query check
    could never pass: the step skips with `search_unreported` before a single call — nothing is paid for."""
    import asyncio

    import litellm

    def never(**kw):
        raise AssertionError("no capability probe, no call")
    monkeypatch.setattr(litellm, "supports_web_search", never)
    for model in ("openrouter/anthropic/claude-haiku-4-5", "openrouter/openai/gpt-4o-search-preview",
                  "openai/gpt-4o-search-preview", "gemini/gemini-2.5-flash", "xai/grok-3"):
        async def metered(settings, registry=None, *, user_triggered=True, _m=model):
            return SimpleNamespace(llm_mode="byok", litellm_model=_m), "byok"
        monkeypatch.setattr(engine_select, "resolve_settings", metered)
        calls: list = []
        report = asyncio.run(web_lookup.run_tail(bank, _settings(), user_triggered=False,
                                                 llm_fn=_fake(_answers, calls=calls)))
        assert (report.reason, calls, report.settled) == ("search_unreported", [], 0), model
    assert web_settle.list_settled(bank) == []


def test_an_anthropic_metered_lookup_settles_end_to_end_through_litellms_own_response(bank, monkeypatch):
    """The real litellm Anthropic transform: a `server_tool_use` web search comes back as a `web_search` tool call with
    its query, so the pinned-query check passes and the answer settles; the call is priced as an `llm_call`."""
    import asyncio

    import httpx
    from litellm.llms.anthropic.chat.transformation import AnthropicConfig
    from litellm.types.utils import ModelResponse

    async def metered(settings, registry=None, *, user_triggered=True):
        return SimpleNamespace(llm_mode="byok", litellm_model="anthropic/claude-haiku-4-5-20251001"), "byok"
    import litellm

    monkeypatch.setattr(engine_select, "resolve_settings", metered)
    # the capability table varies with litellm's cost map (bundled or fetched): pinned here, the transform is real
    monkeypatch.setattr(litellm, "supports_web_search", lambda model: model.startswith("anthropic/claude"))
    resolved, _label, why = asyncio.run(web_lookup.engine_for(object(), user_triggered=False))
    assert why == "metered", "a model with web search, on a provider whose searches are reported"

    def completion(**kw):
        assert kw["web_search_options"] == {"search_context_size": "low"}
        user = kw["messages"][-1]["content"]
        query = user.split("Search query (use exactly this): ", 1)[1].split("\n", 1)[0]
        raw = {"id": "msg_x", "type": "message", "role": "assistant", "model": "claude-haiku-4-5-20251001",
               "content": [{"type": "server_tool_use", "id": "srvtoolu_x", "name": "web_search",
                            "input": {"query": query}},
                           {"type": "web_search_tool_result", "tool_use_id": "srvtoolu_x", "content": []},
                           {"type": "text", "text": json.dumps(_answers(user))}],
               "stop_reason": "end_turn",
               "usage": {"input_tokens": 50, "output_tokens": 20, "server_tool_use": {"web_search_requests": 1}}}
        return AnthropicConfig().transform_parsed_response(
            completion_response=raw, raw_response=httpx.Response(200, json=raw), model_response=ModelResponse())
    events: list = []
    settings = SimpleNamespace(llm_mode="byok", litellm_model="anthropic/claude-haiku-4-5-20251001", ollama_model="x",
                               ollama_base_url="http://localhost", openrouter_app_url=None, openrouter_app_name=None)
    fn = providers.resolve_llm_fn(settings, stage="web_check", completion=completion, sink=events.append, bank="b")
    report = _run(bank, fn, engine=(resolved, "byok-anthropic", "metered"))
    assert report.settled == 2 and report.skipped == {"unsure": 1}
    assert {r["id"] for r in web_settle.list_settled(bank)} == {"inbox-101", "inbox-102"}
    assert {e.kind for e in events} == {"llm_call"} and {e.stage for e in events} == {"web_check"}


# ---------- a failed commit leaves nothing dangling ----------


def test_a_failed_web_check_commit_puts_every_settle_back(bank, monkeypatch):
    import asyncio

    from api.services import sleep_cycle

    async def engine(settings, *, user_triggered):
        return "resolved", "claude-cli", "plan"
    monkeypatch.setattr(web_lookup, "engine_for", engine)
    monkeypatch.setattr(web_lookup, "default_llm_fn", lambda resolved: _fake(_answers))
    monkeypatch.setattr(sleep_cycle._state, "cycle_id", "cyc-web-fail")
    monkeypatch.setattr(sleep_cycle._state, "drain", None)
    head = _git(bank, "rev-parse", "HEAD")
    page = (bank / "entities" / "tool-a.md").read_bytes()
    episodes = sorted(p.name for p in (bank / "episodes").glob("*.md"))

    def boom(memory_path, message, paths, **kw):
        from api.services import git_service

        git_service.run_git_write_sync(memory_path, "add", "-A", "--", *[p for p in paths
                                                                        if (memory_path / p).exists()])
        raise git_service.GitError("commit failed")
    monkeypatch.setattr(web_settle, "commit_sync", boom)
    asyncio.run(sleep_cycle._web_check_safely(bank, _settings(), user_triggered=True))
    assert _git(bank, "rev-parse", "HEAD") == head
    assert _git(bank, "status", "--porcelain").strip() == "", "nothing staged or dirty for a later `git add -A`"
    assert (bank / "entities" / "tool-a.md").read_bytes() == page
    assert (bank / "inbox" / "inbox-101.md").exists() and (bank / "inbox" / "inbox-102.md").exists()
    assert web_settle.list_settled(bank) == []
    assert sorted(p.name for p in (bank / "episodes").glob("*.md")) == episodes
    memo = web_lookup.load_memo(bank)
    assert "inbox-101" not in memo and "inbox-102" not in memo, "the next run may look them up again"


# ---------- local context (owner ruling 2026-10-16, amends ruling 27: "Yes, use local context") ----------

LEAKY = ("We watched Example Film with Alice Example last night, notes in ~/Documents/notes/plan.md and "
         "https://notes.example-host.net/private/123 — mail alice@example.org, api_key=abcdef1234567890abcdef, and "
         "@ali_handle liked it. " + "Long tail of the same line about nothing much at all. " * 12)


def _episode(memory, ep_id, body, **fm):
    base = {"id": ep_id, "timestamp": "2026-09-03T10:00:00+00:00", "processed": True, "title": "An evening"}
    base.update(fm)
    markdown_parser.write(memory / "episodes" / f"{ep_id}.md", base, body)


def _snapshot_tree(*roots):
    out = {}
    for root in roots:
        if not root.exists():
            continue
        for p in sorted(root.rglob("*")):
            if p.is_file() and ".git" not in p.relative_to(root).parts:
                out[str(p)] = p.read_bytes()
    return out


def test_the_local_context_is_bounded_scrubbed_names_no_one_and_never_enters_the_query(bank):
    _episode(bank, "ep_2026-09-03_001", "user: what a week\n\nuser: " + LEAKY + "\nassistant: noted.")
    markdown_parser.write(bank / "inbox" / "inbox-101.md",
                          {**markdown_parser.parse(bank / "inbox" / "inbox-101.md").frontmatter,
                           "source_episode": "ep_2026-09-03_001"}, SECRET)
    _commit(bank, "ep")
    facts = web_settle.bank_facts(bank)
    c = web_settle.candidate(bank, bank / "inbox" / "inbox-101.md", facts)
    context = web_settle.local_context(bank, c, facts)
    text = "\n".join(context)
    assert len(text) <= web_settle.MAX_CONTEXT_CHARS
    assert all(len(line) <= web_settle.MAX_LINE_CHARS + len("Mentioned: ") for line in context)
    assert context[0].startswith("Cicada's description: ") and "film" in context[0].lower()
    assert web_settle.has_mentions(context) and "Example Film" in text
    for leak in ("Alice", "alice", "~/Documents", "plan.md", "https://", "example-host", "@example.org",
                 "abcdef1234567890abcdef", "@ali_handle", "user:", "secret-phrase-xyz", "dinner"):
        assert leak not in text, leak
    assert "someone" in text and "[path]" in text
    # Each line is cleaned whole before it is cut: links, addresses, handles, secrets and paths never survive.
    line = web_settle.clean_context_line(LEAKY, facts, limit=2000)
    assert all(t in line for t in ("[link]", "[address]", "[handle]", "[path]", "someone"))
    assert not any(t in line for t in ("Alice", "https://", "alice@", "abcdef1234567890abcdef", "@ali_handle", "~/"))
    # The query is unchanged in kind: the name and at most one category word, never a word of the context.
    assert web_settle.query_for(c) == "Example Film film"
    calls: list = []
    _run(bank, _fake(_answers, calls=calls))
    film_prompt = next(m[-1]["content"] for m in calls if "Subject: Example Film" in m[-1]["content"])
    assert "Mentioned: " in film_prompt and "never search for these words" in film_prompt
    assert film_prompt.split("Search query (use exactly this): ", 1)[1].split("\n", 1)[0] == "Example Film film"


def test_the_pinned_query_check_still_rejects_a_search_carrying_the_context(bank):
    _episode(bank, "ep_2026-09-03_002", "user: Example Film was on at the old cinema downtown")
    markdown_parser.write(bank / "inbox" / "inbox-101.md",
                          {**markdown_parser.parse(bank / "inbox" / "inbox-101.md").frontmatter,
                           "source_episode": "ep_2026-09-03_002"}, "Context.")
    _commit(bank, "ep")

    def fn(*, messages, web_search=False, timeout=None, **kw):
        user = messages[-1]["content"]
        query = user.split("Search query (use exactly this): ", 1)[1].split("\n", 1)[0]
        return {"choices": [{"message": {"content": json.dumps(_answers(user))}}], "model": "fake-model",
                "tool_uses": [["WebSearch", {"query": query + " old cinema downtown"}]]}

    report = _run(bank, fn)
    assert report.settled == 0 and report.skipped.get("query_strayed") == report.looked_up > 0
    assert not list((bank / "inbox" / "settled").glob("*.md")) if (bank / "inbox" / "settled").exists() else True


def test_a_type_question_carries_its_mentions_but_not_cicadas_own_guess(bank):
    _episode(bank, "ep_2026-09-04_001", "user: I set up Tool B yesterday to run my local models in a loop.")
    body = write_claims("## Summary\nTool B is an AI agent.\n", [
        Claim(id="clm_th", text="Tool B is an agent harness", subject="tool-b", predicate="is-a",
              object="agent harness for running models", valid_from="2026-05-01", recorded_at="2026-05-01",
              source_episodes=["ep_2026-09-04_001"]),
        Claim(id="clm_ta", text="Tool B is an AI agent", subject="tool-b", predicate="is-a",
              object="AI agent itself", valid_from="2026-08-01", recorded_at="2026-08-01"),
    ])
    _entity(bank, "tool-b", type="tool", name="Tool B", description="An AI agent", body=body)
    _type_item(bank)
    facts = web_settle.bank_facts(bank)
    c = web_settle.candidate(bank, bank / "inbox" / "inbox-108.md", facts)
    context = web_settle.local_context(bank, c, facts)
    assert context == ["Mentioned: I set up Tool B yesterday to run my local models in a loop."]
    user = web_lookup.build_messages(c, context)[-1]["content"]
    assert "the notes decide which one the person meant" in user and "An AI agent" not in user


# ---------- category words: from Cicada's own description, one at most, none when unsure ----------


def test_the_category_word_comes_from_the_description_never_the_type_alone(bank):
    _entity(bank, "corner-example", type="company", name="Corner Example",
            body="## Summary\nA small restaurant two streets from the station.\n")
    _entity(bank, "lib-example", type="tool", name="Lib Example",
            description="An open-source library and framework for parsing feeds")
    _entity(bank, "year-example", type="company", name="Year Example", description="A software company")
    _item(bank, "inbox-111", kind="clarification", entity_id="corner-example", entity_name="Corner Example",
          title="Who or what is Corner Example?")
    _item(bank, "inbox-112", kind="clarification", entity_id="lib-example", entity_name="Lib Example",
          title="Who or what is Lib Example?")
    _item(bank, "inbox-113", kind="conflict", entity_id="year-example", entity_name="Year Example",
          predicate="founded-in", options=[{"key": "a", "label": "2019"}, {"key": "b", "label": "2020"}])
    _item(bank, "inbox-114", kind="conflict", entity_id="year-example", entity_name="Year Example",
          predicate="made-by", options=[{"key": "a", "label": "a software studio"}, {"key": "b", "label": "x"}])
    _commit(bank, "seed categories")
    facts = web_settle.bank_facts(bank)
    q = {i: web_settle.query_for(web_settle.candidate(bank, bank / "inbox" / f"{i}.md", facts))
         for i in ("inbox-111", "inbox-112", "inbox-113", "inbox-114")}
    assert q["inbox-111"] == "Corner Example"           # typed company, described as a restaurant: no "company"
    assert q["inbox-112"] == "Lib Example library"      # one word, the first the description names
    assert q["inbox-113"] == "Year Example software"
    assert q["inbox-114"] == "Year Example"             # the word an option carries is not sent


# ---------- order: clarifications first, then conflicts the context can answer ----------


def test_clarifications_come_first_then_conflicts_with_a_mention_line(bank):
    _episode(bank, "ep_2026-09-04_002", "user: Tool B keeps crashing when the harness restarts.")
    body = write_claims("## Summary\nA tool.\n", [
        Claim(id="clm_th", text="x", subject="tool-b", predicate="is-a", object="agent harness for running models",
              valid_from="2026-05-01", recorded_at="2026-05-01", source_episodes=["ep_2026-09-04_002"]),
        Claim(id="clm_ta", text="y", subject="tool-b", predicate="is-a", object="AI agent itself",
              valid_from="2026-08-01", recorded_at="2026-08-01"),
    ])
    _entity(bank, "tool-b", type="tool", name="Tool B", body=body)
    _type_item(bank, priority=0.1)   # lower priority than 102, but it has a mention line
    _item(bank, "inbox-102", **{**markdown_parser.parse(bank / "inbox" / "inbox-102.md").frontmatter,
                                "priority": 0.9})
    _commit(bank, "order")
    facts = web_settle.bank_facts(bank)
    todo, eligible = web_lookup.select(bank, facts, {}, date(2026, 10, 16), cap=10)
    assert eligible == 4
    order = [c.item_id for c, _ in todo]
    assert [c.kind for c, _ in todo] == ["clarification", "clarification", "conflict", "conflict"]
    assert order.index("inbox-108") < order.index("inbox-102"), "a conflict the context can answer goes first"


# ---------- the dry run writes nothing ----------


def test_the_dry_run_counts_and_writes_nothing(bank, monkeypatch, tmp_path):
    import asyncio
    import os

    _type_item(bank)
    home = tmp_path / "home"
    before = _snapshot_tree(bank, home)
    head = _git(bank, "rev-parse", "HEAD")
    calls: list = []
    out = asyncio.run(web_lookup.dry_run(bank, _settings(), limit=8, llm_fn=_fake(_answers, calls=calls),
                                         engine=("resolved", "claude-cli", "plan")))
    assert out["looked_up"] == len(calls) == 4 and out["eligible"] == 4
    assert out["would_settle"] == 2   # the film (clarification) and Tool A (conflict); 103 and Tool B unsure
    assert out["by_kind"]["clarification"] == {"looked_up": 2, "would_settle": 1, "reasons": {"unsure": 1}}
    # Tool A's `description` conflict is a type question too: it settles (ruled out); Tool B's stays unsure.
    assert out["by_kind"]["type_conflict"] == {"looked_up": 2, "would_settle": 1, "reasons": {"unsure": 1}}
    assert _snapshot_tree(bank, home) == before, "no settle, no memo, no ledger row"
    assert _git(bank, "rev-parse", "HEAD") == head and not _git(bank, "status", "--porcelain").strip()
    assert not (home / "web_check").exists() and not (home / "telemetry").exists()
    # A second dry run looks the same questions up again: nothing was remembered.
    calls.clear()
    asyncio.run(web_lookup.dry_run(bank, _settings(), limit=8, llm_fn=_fake(_answers, calls=calls),
                                   engine=("resolved", "claude-cli", "plan")))
    assert len(calls) == 4
    # The script: counts only — never an id, a name, a query, a link or a quote.
    from api.scripts import web_check_dry_run

    async def fake_engine_for(settings, *, user_triggered):
        assert user_triggered is True
        return "resolved", "claude-cli", "plan"

    monkeypatch.setattr(web_lookup, "engine_for", fake_engine_for)
    monkeypatch.setattr(web_lookup, "default_llm_fn", lambda resolved, sink=None: _fake(_answers))
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert web_check_dry_run.main(["--bank", str(bank), "--limit", "3"]) == 0
    printed = buf.getvalue()
    assert json.loads(printed)["looked_up"] == 3
    for word in ("inbox-", "Example Film", "Tool A", "Tool B", "film", "https", "quote", "2401"):
        assert word not in printed, word
    assert _snapshot_tree(bank, home) == before
    assert web_check_dry_run.main(["--bank", str(tmp_path / "nope")]) == 2
    assert os.environ.get("CICADA_HOME") == str(home)
