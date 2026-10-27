"""Light web context for public pages, kept current (owner ruling 44, 2026-10-27; G121) and "why it matters to you".

Synthetic banks only (Owner Example, Grace Example, Bob Example, Example Fellowship …); public figures are synthetic
too. The search tool and Wikidata are fakes that record what they were sent; git is real; nothing reaches a network or
a paid API."""
from __future__ import annotations

import asyncio
import json
import subprocess
from datetime import date, timedelta

import pytest

from _synthetic_bank import _bank, _entity
from api.services import bank_index, markdown_parser, page_relevance, web_context, web_settle
from api.services.claims import Claim, Evidence, parse_claims, write_claims

TODAY = date.today()
RECENT = (TODAY - timedelta(days=3)).isoformat()


def _git(memory, *args):
    return subprocess.run(["git", "-C", str(memory), *args], check=True, capture_output=True, text=True).stdout


def _episode(memory, ep_id, body="user: talked about it", source="chatgpt"):
    markdown_parser.write(memory / "episodes" / f"{ep_id}.md",
                          {"id": ep_id, "timestamp": f"{ep_id[3:13]}T09:00:00+00:00", "processed": True,
                           "source": source, "title": "a chat"}, body)


def _claim(cid, subject, predicate, obj, *, kind="node", **kw):
    return Claim(id=cid, text=kw.pop("text", f"{subject} {predicate} {obj}"), subject=subject, predicate=predicate,
                 object=obj, object_kind=kind, valid_from=kw.pop("valid_from", "2026-01-01"),
                 recorded_at=kw.pop("recorded_at", "2026-01-01"), **kw)


@pytest.fixture
def bank(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_ALLOW_CONNECTOR_FETCH", "on")
    memory = _bank(tmp_path)
    ep1, ep2, ep3 = f"ep_{RECENT}_001", f"ep_{RECENT}_002", f"ep_{RECENT}_003"
    for ep in (ep1, ep2, ep3):
        _episode(memory, ep, body="user: I said this myself about the thing.")
    _episode(memory, f"ep_{RECENT}_009", source="imessage")
    owner_claims = [
        _claim("clm_o1", "olive-ownerton", "is-friends-with", "bob-example"),
        _claim("clm_o2", "olive-ownerton", "applied-to", "example-fellowship", valid_from=RECENT, text="Owner Example "
               "applied to Example Fellowship"),
        _claim("clm_o3", "olive-ownerton", "worked-at", "acme-cloud", valid_to="2026-06-01",
               text="Owner Example worked at Acme Cloud"),
        _claim("clm_o4", "olive-ownerton", "watched", "grace-example"),
    ]
    _entity(memory, "olive-ownerton", type="person", owner=True, name="Olive Ownerton",
            body=write_claims("## Summary\nThe owner.\n", owner_claims))
    grace = write_claims("## Summary\nGrace Example is a founder and author known for databases.\n", [
        _claim("clm_g1", "grace-example", "works-at", "Old Corp", kind="literal",
               evidence=[Evidence(episode=ep1, start=0, end=10, kind="user", hash="x")]),
    ])
    _entity(memory, "grace-example", type="person", name="Grace Example", source_episodes=[ep1, ep2], body=grace)
    hal = write_claims("## Summary\nHal Example is an investor and author.\n", [
        _claim("clm_h1", "hal-example", "works-at", "Old Corp", kind="literal",
               evidence=[Evidence(episode=ep1, start=-1, end=-1, kind="assistant", hash="x")]),
    ])
    _entity(memory, "hal-example", type="person", name="Hal Example", source_episodes=[ep1], body=hal)
    _entity(memory, "bob-example", type="person", name="Bob Example", source_episodes=[ep1],
            body="## Summary\nBob Example is a founder of a small studio.\n")
    _entity(memory, "dana-example", type="person", name="Dana Example", source_episodes=[ep1],
            body="## Summary\nDana Example is a founder. Olive Ownerton met her at a meetup and they talked.\n")
    _entity(memory, "erin-example", type="person", name="Erin Example", source_episodes=[ep1],
            body="## Summary\nErin Example is an author.\n")
    _entity(memory, "ivan-example", type="person", name="Ivan Example", source_episodes=[f"ep_{RECENT}_009"],
            body="## Summary\nIvan Example is an author.\n")
    _entity(memory, "kim", type="person", name="Kim", source_episodes=[ep1], body="## Summary\nKim is an author.\n")
    fellowship = write_claims("## Summary\nExample Fellowship is a fellowship program.\n", [
        _claim("clm_f1", "example-fellowship", "deadline", "2026-11-01", kind="literal",
               evidence=[Evidence(episode=ep2, start=-1, end=-1, kind="assistant", hash="x")]),
    ])
    _entity(memory, "example-fellowship", type="company", name="Example Fellowship",
            source_episodes=[ep1, ep2, ep3], body=fellowship)
    _entity(memory, "acme-cloud", type="company", name="Acme Cloud", source_episodes=[ep3],
            body="## Summary\nAcme Cloud is a company.\n")
    _git(memory, "add", "-A")
    _git(memory, "commit", "-qm", "seed")
    bank_index.invalidate()
    return memory


class FakeWikidata:
    """Answers like Wikidata for the synthetic names; records every name it was sent."""

    def __init__(self):
        self.sent: list[str] = []
        self.humans = {"Grace Example": ["Q1"], "Hal Example": ["Q2"], "Erin Example": ["Q3", "Q4"],
                       "Example Fellowship": []}

    async def __call__(self, params):
        if params["action"] == "wbsearchentities":
            self.sent.append(params["search"])
            ids = self.humans.get(params["search"], [])
            return {"search": [{"id": q, "label": params["search"]} for q in ids]}
        if params["action"] == "wbgetclaims":
            return {"claims": {"P31": [{"mainsnak": {"datavalue": {"value": {"id": "Q5"}}}}]}}
        if params["action"] == "wbgetentities":
            return {"entities": {params["ids"]: {"sitelinks": {"enwiki": {"title": "x"}}}}}
        return None


def _engine_fn(answers, calls):
    def fn(*, messages, web_search=False, timeout=None, **kw):
        assert web_search is True
        user = messages[-1]["content"]
        calls.append(user)
        query = user.split("word for word):\n", 1)[1].split("\n", 1)[0].strip()
        subject = user.split("Subject: ", 1)[1].split("\n", 1)[0]
        return {"choices": [{"message": {"content": json.dumps(answers.get(subject, {"sure": False}))}}],
                "model": "fake-model", "tool_uses": [["WebSearch", {"query": query}]]}
    return fn


def _fact(pred, value, url="https://news.news-example.net/a", quote=None, as_of=""):
    return {"predicate": pred, "value": value, "as_of": as_of, "url": url, "quote": quote or f"{value} today."}


ANSWERS = {
    "Grace Example": {"sure": True, "facts": [_fact("works-at", "New Corp")]},
    "Hal Example": {"sure": True, "facts": [_fact("works-at", "New Corp", as_of=RECENT)]},
    "Example Fellowship": {"sure": True, "facts": [_fact("deadline", "2026-11-15",
                                                         url="https://apply.fellowship-example.net/apply")]},
    "Acme Cloud": {"sure": True, "facts": [_fact("headquartered-in", "Lisbon")]},
}
ENGINE = (object(), "claude-cli", "plan")


def _settings(**kw):
    from types import SimpleNamespace

    return SimpleNamespace(web_context_per_run=kw.get("per_run", 10), llm_mode="agent")


def _run(memory, *, per_run=10, get=None, calls=None, engine=ENGINE, answers=ANSWERS):
    calls = calls if calls is not None else []
    return asyncio.run(web_context.run_tail(memory, _settings(per_run=per_run), user_triggered=True,
                                            llm_fn=_engine_fn(answers, calls), engine=engine,
                                            get=get or FakeWikidata()))


# ---------------------------------------------------------------------------------------------------- public test


def test_public_test_and_private_names_never_leave(bank):
    wd, calls = FakeWikidata(), []
    facts = web_settle.bank_facts(bank)
    memo = web_context.load_memo(bank)
    verdicts = {}
    for eid in ("grace-example", "hal-example", "bob-example", "dana-example", "erin-example", "ivan-example", "kim",
                "olive-ownerton", "example-fellowship", "acme-cloud"):
        page = web_context.load_page(bank, eid)
        verdicts[eid] = asyncio.run(web_context.verdict(bank, page, facts, memo, get=wd, today=TODAY))
    assert verdicts["grace-example"].public and verdicts["grace-example"].reason == "encyclopedia_match"
    assert verdicts["hal-example"].public
    assert (verdicts["bob-example"].public, verdicts["bob-example"].reason) == (False, "personal_relation")
    assert (verdicts["dana-example"].public, verdicts["dana-example"].reason) == (False, "owner_in_prose")
    assert (verdicts["erin-example"].public, verdicts["erin-example"].reason) == (False, "ambiguous")
    assert (verdicts["ivan-example"].public, verdicts["ivan-example"].reason) == (False, "personal_channel")
    assert verdicts["kim"].reason == "single_name"
    assert verdicts["olive-ownerton"].reason == "owner"
    assert verdicts["example-fellowship"].public and verdicts["acme-cloud"].public, (verdicts["example-fellowship"], verdicts["acme-cloud"])
    # A private person's name never reached Wikidata.
    for private in ("Bob Example", "Dana Example", "Ivan Example", "Kim", "Olive Ownerton"):
        assert private not in wd.sent
    # …nor the search: a full run's prompts never carry them.
    _run(bank, calls=calls, get=wd)
    joined = "\n".join(calls)
    for private in ("Bob Example", "Dana Example", "Ivan Example", "Olive Ownerton"):
        assert private not in joined


def test_a_relation_word_or_a_project_name_is_private(bank):
    _entity(bank, "alpha-project-labs", type="company", name="Alpha Project", source_episodes=[f"ep_{RECENT}_001"])
    bank_index.invalidate()
    facts = web_settle.bank_facts(bank)
    page = web_context.load_page(bank, "alpha-project-labs")
    assert web_context.local_verdict(bank, page, facts).reason == "project"


# ---------------------------------------------------------------------------------------------------- write + order


def test_replacement_keeps_history_and_undo_takes_it_back(bank):
    report = _run(bank)
    assert report.written >= 2
    claims = {c.id: c for c in parse_claims(markdown_parser.parse(bank / "entities" / "example-fellowship.md").body)}
    old = claims["clm_f1"]
    new = [c for c in claims.values() if c.origin == web_context.ORIGIN]
    assert len(new) == 1 and new[0].object == "2026-11-15" and new[0].source_trust == "external"
    assert old.valid_to == TODAY.isoformat() and old.superseded_by == new[0].id   # history kept, closed
    assert new[0].evidence and new[0].evidence[0].kind == "page"
    fm = markdown_parser.parse(bank / "entities" / "example-fellowship.md").frontmatter
    assert "sources" not in fm   # a citation, never a tracked source
    hal = {c.id: c for c in parse_claims(markdown_parser.parse(bank / "entities" / "hal-example.md").body)}
    hal_new = [c for c in hal.values() if c.origin == web_context.ORIGIN][0]
    assert hal["clm_h1"].superseded_by == hal_new.id and hal_new.valid_from == RECENT
    # "Settled by a check" lists it and takes it back.
    rows = [r for r in web_settle.list_settled(bank) if r["entity_id"] == "example-fellowship"]
    assert rows and rows[0]["kind"] == "context" and rows[0]["group"] == "check"
    paths, _lines = web_context.undo(bank, rows[0]["id"])
    after = {c.id: c for c in parse_claims(markdown_parser.parse(bank / "entities" / "example-fellowship.md").body)}
    assert set(after) == {"clm_f1"} and after["clm_f1"].valid_to is None
    # The value taken back is never written again, even when the next lookup says it.
    memo = web_context.load_memo(bank)
    memo["pages"].pop("example-fellowship")
    web_context.save_memo(bank, memo)
    _run(bank)
    again = parse_claims(markdown_parser.parse(bank / "entities" / "example-fellowship.md").body)
    assert not [c for c in again if c.origin == web_context.ORIGIN]


def test_the_persons_own_words_are_never_overridden(bank):
    _run(bank)
    claims = {c.id: c for c in parse_claims(markdown_parser.parse(bank / "entities" / "grace-example.md").body)}
    assert claims["clm_g1"].valid_to is None and claims["clm_g1"].superseded_by is None
    assert not [c for c in claims.values() if c.origin == web_context.ORIGIN and c.predicate == "works-at"]


def test_order_most_used_and_unchecked_first_then_due_by_volatility(bank):
    facts = web_settle.bank_facts(bank)
    memo = web_context.load_memo(bank)
    todo = asyncio.run(web_context.plan(bank, cap=10, today=TODAY, memo=memo, get=FakeWikidata(), facts=facts))
    assert [t.priority for t in todo] == sorted((t.priority for t in todo), reverse=True)   # most used first
    by_id = {t.page.entity_id: t for t in todo}
    assert by_id["example-fellowship"].page.depth == "deep"   # a commitment: dates and deadlines
    assert by_id["example-fellowship"].why == "unchecked"     # model-knowledge facts no lookup wrote
    assert by_id["acme-cloud"].page.depth == "line" and by_id["acme-cloud"].why == "new"
    assert by_id["example-fellowship"].priority > by_id["acme-cloud"].priority
    fellowship = by_id["example-fellowship"].page
    assert "Example Fellowship deadline" in web_context.queries_for(fellowship, "deep")
    # Looked up 10 days ago: a volatile fact on a used page is due again; a fixed fact never on a schedule.
    memo["pages"]["example-fellowship"] = {"at": (TODAY - timedelta(days=10)).isoformat()}
    ok, why, _ = web_context.due(fellowship, memo, TODAY)
    assert ok and why == "recheck"
    memo["pages"]["example-fellowship"] = {"at": (TODAY - timedelta(days=1)).isoformat()}
    assert web_context.due(fellowship, memo, TODAY)[1] == "fresh"
    fellowship.world = [_claim("x", "example-fellowship", "founded", "1999", kind="literal")]
    memo["pages"]["example-fellowship"] = {"at": (TODAY - timedelta(days=900)).isoformat()}
    assert web_context.due(fellowship, memo, TODAY)[1] == "fixed"
    # Nobody has mentioned it in half a year: re-checked only when someone asks.
    fellowship.last_mentioned = (TODAY - timedelta(days=400)).isoformat()
    assert web_context.due(fellowship, memo, TODAY)[1] == "on_read"


def test_a_search_for_anything_else_writes_nothing(bank):
    def strays(*, messages, web_search=False, timeout=None, **kw):
        return {"choices": [{"message": {"content": json.dumps(ANSWERS["Acme Cloud"])}}], "model": "m",
                "tool_uses": [["WebSearch", {"query": "acme cloud owner example"}]]}

    report = asyncio.run(web_context.run_tail(bank, _settings(), user_triggered=True, llm_fn=strays, engine=ENGINE,
                                              get=FakeWikidata()))
    assert report.written == 0 and report.skipped.get("query_strayed")


# ---------------------------------------------------------------------------------------------------- budget + gates


def test_budget_caps_lookups_and_wikidata(bank):
    calls: list[str] = []
    report = _run(bank, per_run=1, calls=calls)
    assert report.looked_up == 1 and len(calls) == 1
    facts = web_settle.bank_facts(bank)
    memo = {"pages": {}, "wd": {}, "undone": {}}
    todo = asyncio.run(web_context.plan(bank, cap=10, today=TODAY, memo=memo, get=FakeWikidata(), facts=facts,
                                        wikidata_budget=0))
    assert all(t.page.type != "person" for t in todo)   # no budget left: every person stays private for now


def test_gate_off_and_step_off_send_nothing(bank, monkeypatch):
    wd, calls = FakeWikidata(), []
    monkeypatch.setenv("CICADA_ALLOW_CONNECTOR_FETCH", "off")
    assert _run(bank, calls=calls, get=wd).reason == "gate"
    monkeypatch.setenv("CICADA_ALLOW_CONNECTOR_FETCH", "on")
    assert _run(bank, per_run=0, calls=calls, get=wd).reason == "off"
    assert calls == [] and wd.sent == []


def test_a_metered_only_engine_skips_in_words(bank, monkeypatch):
    from api.services import web_lookup

    async def metered(settings, *, user_triggered):
        return object(), "anthropic/claude-x", "metered"

    monkeypatch.setattr(web_lookup, "engine_for", metered)
    resolved, _label, why = asyncio.run(web_context.engine_for(_settings(), user_triggered=True))
    assert resolved is None and why == "metered_only"
    wd, calls = FakeWikidata(), []
    report = asyncio.run(web_context.run_tail(bank, _settings(), user_triggered=True,
                                              llm_fn=_engine_fn(ANSWERS, calls), get=wd))
    assert report.reason == "metered_only" and "metered key" in report.words
    assert calls == [] and wd.sent == []


def test_deeper_refuses_a_private_person(bank):
    calls: list[str] = []
    out = asyncio.run(web_context.deeper(bank, _settings(), "bob-example", llm_fn=_engine_fn(ANSWERS, calls),
                                         engine=ENGINE, get=FakeWikidata(), commit=False))
    assert out == {"status": "private", "reason": "personal_relation"} and calls == []


# ---------------------------------------------------------------------------------------------------- relevance


def test_why_it_matters_reads_tense_from_the_record(bank):
    assert page_relevance.for_page(bank, "olive-ownerton").tense == "self"
    fellowship = page_relevance.for_page(bank, "example-fellowship")
    assert fellowship.tense == "is" and "applied to Example Fellowship" in fellowship.line
    acme = page_relevance.for_page(bank, "acme-cloud")
    assert acme.tense == "was" and acme.line.startswith("Why it mattered to you") and "until 2026-06-01" in acme.line
    hal = page_relevance.for_page(bank, "hal-example")
    assert hal.tense == "none" and hal.line.startswith("No personal relation on the record: it came up in 1 ")
    grace = page_relevance.for_page(bank, "grace-example")
    assert grace.tense == "is"   # the person's own words on the page, and a "watched" from the owner


# ---------------------------------------------------------------------------------------------------- routes


def test_routes_relevance_undo_and_a_ledger_without_text(bank, monkeypatch):
    from fastapi.testclient import TestClient

    from api import config, main
    from api.services import telemetry

    monkeypatch.setenv("CICADA_TELEMETRY", "on")
    _run(bank)
    _git(bank, "add", "-A")
    _git(bank, "commit", "-qm", "web context")
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    config.get_settings.cache_clear()
    try:
        with TestClient(main.app) as client:
            card = client.get("/entities/example-fellowship").json()
            assert card["relevance"]["tense"] == "is" and "Example Fellowship" in card["relevance"]["line"]
            rows = [r for r in client.get("/inbox/settled").json() if r["id"].startswith("ctx-")]
            assert rows
            first = rows[0]["id"]
            assert client.post(f"/inbox/settled/{first}/undo").json() == {"status": "undone", "id": first}
            assert client.post(f"/inbox/settled/{first}/undo").status_code == 404
            # A private person's "go deeper" sends nothing and says why.
            assert client.post("/entities/bob-example/web-context").json() == {"status": "private",
                                                                                "reason": "personal_relation"}
    finally:
        config.get_settings.cache_clear()
    log = _git(bank, "log", "-3", "--format=%s%n%b")
    assert "Web context undone" in log and "Cicada-Author: user" in log
    ledger = [json.loads(line) for f in telemetry.telemetry_dir().glob("*.jsonl")
              for line in f.read_text().splitlines()]
    blob = json.dumps([r for r in ledger if r.get("kind") == "web_check"])
    assert "context" in blob
    for text in ("New Corp", "2026-11-15", "fellowship-example.net", "Lisbon"):
        assert text not in blob
