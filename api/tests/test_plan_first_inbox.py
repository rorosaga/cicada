"""Owner rulings 2026-10-19: the inbox stops asking what a web search can answer.

"Questions like 'Is <a public tool> an AI agent or an AI code editor?' can be solved by an internet search. That's not
what the inbox is for." — which shapes a lookup may answer (and which stay the person's), Cicada's own settings never
asked, and the one-off sweep over the backlog: its dry run writes nothing, its real run settles each question with a
citation under the bank's write admission, one commit each, undoable under "Settled by a check".

Synthetic banks only (placeholder names, ``_inbox_shapes``); the search tool is a fake; git is real; nothing reaches a
network or a plan.
"""
from __future__ import annotations

import asyncio
import json
import subprocess

import pytest
from fastapi.testclient import TestClient

import _inbox_shapes as shapes
from _synthetic_bank import _bank
from test_sleep_engine_state import _seed, tail_spy  # noqa: F401 — the engine-state tests' seed and tail fixture
from api import config, main
from api.services import bank_index, inbox_tend, markdown_parser, sleep_cycle, web_lookup, web_settle

URL = "https://docs.thing-example.dev/page"
ENGINE = ("resolved", "claude-cli", "plan")


def _git(memory, *args):
    return subprocess.run(["git", "-C", str(memory), *args], check=True, capture_output=True, text=True).stdout


@pytest.fixture
def bank(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    memory = _bank(tmp_path)
    for p in (memory / "inbox").glob("inbox-*.md"):
        p.unlink()
    shapes.build(memory)
    _git(memory, "add", "-A")
    _git(memory, "commit", "-qm", "seed")
    bank_index.invalidate()
    return memory


def _answers(user: str) -> dict:
    """A fake search tool: sure about the editor (both), the studio and the dataset; unsure about the rest."""
    if "Editor Example" in user:
        return {"sure": True, "option_key": "both", "url": URL, "quote": "Editor Example is an AI code editor with an "
                "agent built in."}
    if "Studio Example" in user:
        return {"sure": True, "answer": "an animation studio", "url": URL, "quote": "Studio Example is an animation "
                "studio."}
    if "dataset-example-1k" in user:
        return {"sure": True, "answer": "an image dataset", "url": URL, "quote": "dataset-example-1k is an image "
                "dataset."}
    return {"sure": False}


def _fake(calls: list):
    def fn(*, messages, web_search=False, timeout=None, **kw):
        assert web_search is True
        user = messages[-1]["content"]
        calls.append(user)
        query = user.split("Search query (use exactly this): ", 1)[1].split("\n", 1)[0]
        return {"choices": [{"message": {"content": json.dumps(_answers(user))}}], "model": "fake-model",
                "tool_uses": [["WebSearch", {"query": query}]]}
    return fn


def _settings(memory):
    return config.Settings(memory_path=memory)


# --------------------------------------------------------------------------- which shapes a lookup may answer


def test_each_measured_shape_is_classified_as_pinned(bank):
    facts = web_settle.bank_facts(bank)
    got = {}
    for item_id in shapes.EXPECTED:
        parsed = markdown_parser.parse(bank / "inbox" / f"{item_id}.md")
        got[item_id] = web_settle.classify(bank, parsed.frontmatter, parsed.body, facts)[1]
    assert got == shapes.EXPECTED


def test_the_speaker_is_not_a_cue_but_the_speakers_own_thing_is():
    assert not web_settle.person_context("A paper the person referenced by its id")
    assert not web_settle.person_context("A dataset the user mentioned")
    assert web_settle.person_context("A dataset built by the user for a class")
    assert web_settle.person_context("The user's own side project")
    assert web_settle.person_context("A friend of the user")
    assert web_settle.person_context("Used in his experiments"), "when in doubt, don't search"


def test_the_census_counts_enums_only(bank):
    census = web_settle.census(bank)
    assert census["public"] == sum(v == "public" for v in shapes.EXPECTED.values())
    assert census["by_kind"]["conflict"]["own_settings"] == 1
    assert census["by_kind"]["clarification"]["person"] == 1
    text = json.dumps(census)
    for word in ("inbox-", "Example", "dataset-example", "Cicada", "provider-a"):
        assert word not in text, word


# --------------------------------------------------------------------------- Cicada's own settings: never asked


def test_a_question_about_cicadas_own_settings_is_never_searched_and_never_asked(bank):
    fm = markdown_parser.parse(bank / "inbox" / "inbox-526.md").frontmatter
    assert web_settle.own_settings(fm)
    decision, why = inbox_tend.policy(bank, bank / "inbox" / "inbox-526.md", fm)
    assert why == "" and decision.rule == "own_settings" and decision.request is None   # retired, nothing touched
    assert decision.rule in inbox_tend.ENGINE_FREE and "Settings" in inbox_tend.RULES["own_settings"]
    # Only Cicada's own page, only its settings: a design question about it, or any other page's engine, stays.
    assert not web_settle.own_settings({**fm, "question": "Should Cicada keep pages as articles?", "title": "",
                                        "options": [{"key": "a", "label": "yes"}, {"key": "b", "label": "no"}]})
    assert not web_settle.own_settings({**fm, "entity_name": "Engine Example", "entity_id": "engine-example"})


def test_the_tidy_dismisses_it_and_the_person_can_take_it_back(bank):
    out = asyncio.run(inbox_tend.tidy(bank, _settings(bank), dry_run=False))
    assert out["by_kind"]["conflict"].get("own_settings") == 1
    assert not (bank / "inbox" / "inbox-526.md").exists()
    rows = {r["id"]: r for r in web_settle.list_settled(bank)}
    assert rows["inbox-526"]["group"] == "sleep"
    inbox_tend.undo(bank, "inbox-526")
    assert (bank / "inbox" / "inbox-526.md").exists()
    fm = markdown_parser.parse(bank / "inbox" / "inbox-526.md").frontmatter
    assert inbox_tend.policy(bank, bank / "inbox" / "inbox-526.md", fm)[1] == "undone", "never settled again"


# --------------------------------------------------------------------------- the sweep


def _tree(memory, home):
    out = {}
    for root in (memory, home):
        if root.exists():
            for p in sorted(root.rglob("*")):
                if p.is_file() and ".git" not in p.relative_to(root).parts:
                    out[str(p)] = p.read_bytes()
    return out


def test_the_sweeps_dry_run_counts_and_writes_nothing(bank, tmp_path):
    home = tmp_path / "home"
    before, head = _tree(bank, home), _git(bank, "rev-parse", "HEAD")
    calls: list = []
    out = asyncio.run(web_lookup.sweep(bank, _settings(bank), dry_run=True, llm_fn=_fake(calls), engine=ENGINE))
    assert out["eligible"] == out["looked_up"] == len(calls) == out["census"]["public"] == 11
    assert out["would_settle"] == 3 and out["settled"] == 0
    assert out["by_kind"]["type_conflict"]["would_settle"] == 1
    assert out["by_kind"]["clarification"]["would_settle"] == 2
    assert _tree(bank, home) == before and _git(bank, "rev-parse", "HEAD") == head
    text = json.dumps(out)
    for word in ("inbox-", "Example", "https", "quote"):
        assert word not in text, word
    census = asyncio.run(web_lookup.sweep(bank, _settings(bank), dry_run=True, limit=0, llm_fn=_fake(calls),
                                          engine=ENGINE))
    assert census["reason"] == "census_only" and len(calls) == 11, "a census makes no call"


def test_the_sweep_settles_each_with_a_citation_one_commit_each_and_each_is_undoable(bank):
    calls: list = []
    commits = int(_git(bank, "rev-list", "--count", "HEAD"))
    out = asyncio.run(web_lookup.sweep(bank, _settings(bank), dry_run=False, llm_fn=_fake(calls), engine=ENGINE))
    assert out["settled"] == 3 and out["looked_up"] == 11 and not out.get("stopped"), json.dumps(out["by_kind"])
    assert int(_git(bank, "rev-list", "--count", "HEAD")) >= commits + 3
    assert not _git(bank, "status", "--porcelain").strip(), "every settle committed its own paths"
    log = _git(bank, "log", "--format=%s%n%b", "-n", "8")
    assert "Web check" in log and "Cicada-Author: fake-model" in log
    settled = {r["id"]: r for r in web_settle.list_settled(bank)}
    assert set(settled) == {"inbox-501", "inbox-504", "inbox-521"}
    assert all(r["group"] == "check" and r["ref"] == URL for r in settled.values())
    # Unsure ones stay exactly as they were, and are remembered for 30 days (no second lookup).
    assert (bank / "inbox" / "inbox-505.md").exists()
    calls.clear()
    again = asyncio.run(web_lookup.sweep(bank, _settings(bank), dry_run=True, llm_fn=_fake(calls), engine=ENGINE))
    assert again["eligible"] == 0 and calls == []
    # Undo: the question returns, marked so no check settles it again.
    target, paths, lines = web_settle.undo(bank, "inbox-504")
    assert target == "inbox-504" and (bank / "inbox" / "inbox-504.md").exists()
    fm = markdown_parser.parse(bank / "inbox" / "inbox-504.md").frontmatter
    assert web_settle.classify(bank, fm, "", web_settle.bank_facts(bank))[1] == "undone"


def test_the_sweep_stops_when_sleep_starts_and_on_a_plan_limit(bank, monkeypatch):
    from api.services import agent_engine

    state = sleep_cycle.get_sleep_state()
    monkeypatch.setattr(state, "status", "running")
    calls: list = []
    out = asyncio.run(web_lookup.sweep(bank, _settings(bank), dry_run=False, llm_fn=_fake(calls), engine=ENGINE))
    assert out["stopped"] == "sleep_running" and calls == [] and out["settled"] == 0
    monkeypatch.setattr(state, "status", "idle")

    def limited(**_kw):
        raise RuntimeError("limit")

    monkeypatch.setattr(agent_engine, "breaker_reason", lambda **_kw: "throttled")
    out = asyncio.run(web_lookup.sweep(bank, _settings(bank), dry_run=False, llm_fn=limited, engine=ENGINE))
    assert out["stopped"] == "plan_limit" and out["looked_up"] == 1 and out["settled"] == 0
    assert web_lookup.load_memo(bank) == {}, "a lookup the engine never answered is offered again"


def test_the_sweep_has_no_engine_without_a_plan_and_never_a_key(bank, monkeypatch):
    async def none(settings, *, user_triggered):
        assert user_triggered is True
        return None, "none", "no_engine"

    monkeypatch.setattr(web_lookup, "engine_for", none)
    out = asyncio.run(web_lookup.sweep(bank, _settings(bank), dry_run=True))
    assert out["reason"] == "no_engine" and out["looked_up"] == 0


def test_the_sweep_route_dry_runs_by_default_and_refuses_while_one_runs(bank, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    config.get_settings.cache_clear()
    seen = {}

    async def fake_sweep(memory_path, settings, *, dry_run=True, limit=None, include_recent=False, **_kw):
        seen.update(dry_run=dry_run, limit=limit)
        return {"dry_run": dry_run, "looked_up": 0}

    monkeypatch.setattr(web_lookup, "sweep", fake_sweep)
    client = TestClient(main.app)
    assert client.post("/inbox/web-check?limit=5").json() == {"dry_run": True, "looked_up": 0}
    assert seen == {"dry_run": True, "limit": 5}
    monkeypatch.setitem(web_lookup._SWEEP, "running", True)
    assert client.post("/inbox/web-check").status_code == 409
    assert client.post("/inbox/tidy").status_code == 409, "a sweep and a tidy never run at once"
    assert client.get("/sleep/status").json()["inboxTidy"] is True, "an updater waits for a sweep"
    monkeypatch.setitem(web_lookup._SWEEP, "running", False)
    assert client.get("/inbox/web-check").json()["running"] is False
    config.get_settings.cache_clear()


# --------------------------------------------------------------------------- ruling 31: never a metered key by itself


@pytest.mark.shipped_engine_default
def test_a_run_with_no_engine_stops_before_stage_one_and_spends_nothing(tmp_path, monkeypatch, tail_spy):
    """Auto (the shipped default) with no plan and no local model, and a key in the environment nobody chose: the run
    stops before Stage 1, says so with the fix, and the queue is untouched."""
    from api.services import engine_select

    memory = _seed(tmp_path, unprocessed=2)
    monkeypatch.setattr(config.Settings, "memory_path", property(lambda self: memory))
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-example")

    async def not_connected(registry, connection_id):
        return False

    monkeypatch.setattr(engine_select, "_connected", not_connected)
    called: list = []

    async def extract(episodes, settings, **_kw):
        called.append(settings)
        return []

    monkeypatch.setattr("api.services.entity_extractor.extract", extract)
    assert config.Settings().llm_mode == "auto"
    asyncio.run(sleep_cycle.run(config.Settings(), "sleep_test"))
    state = sleep_cycle.get_sleep_state()
    assert called == [], "nothing was read"
    assert "No engine to read with" in (state.error or "") and "Settings → Engines" in state.error
    assert len(sleep_cycle._get_unprocessed_episodes(memory)) == 2


def test_an_answer_with_no_search_is_counted_unsure_or_strayed_and_never_settles(bank):
    facts = web_settle.bank_facts(bank)
    todo, _n = web_lookup.select(bank, facts, {}, __import__("datetime").date.today(), cap=1)

    def no_search(sure):
        def fn(**_kw):
            body = {"sure": True, "answer": "x", "url": URL, "quote": "x"} if sure else {"sure": False}
            return {"choices": [{"message": {"content": json.dumps(body)}}], "tool_uses": []}
        return fn

    (_c, a), = asyncio.run(web_lookup.look_up(no_search(False), todo, web_lookup.Report()))
    assert (a.ok, a.reason) == (False, "unsure")
    (_c, a), = asyncio.run(web_lookup.look_up(no_search(True), todo, web_lookup.Report()))
    assert (a.ok, a.reason) == (False, "query_strayed"), "a sure answer from no search settles nothing"
