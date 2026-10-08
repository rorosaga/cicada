"""Stage 2 judges a batch's names with bounded concurrency and decides exactly as the serial loop did.

A batch of 25 conversations spent most of its wall time in Stage 2's disambiguation judge: one call per
(name, same-type page sharing a name token), awaited one after another. The judgments against EXISTING pages
depend only on the name's own extraction and the page — never on what the loop decided for an earlier name —
so they are taken ahead of the loop under a bounded gate, while everything that does depend on the loop (a
direct match to an in-cycle create, an in-cycle create as a candidate) is still decided inline, in order.

These tests pin: the same decisions and the same judged pairs at any concurrency; the bound; a plan limit is
still the exception ``resolve`` raises (the drain's pause) and starts nothing further; a cancel starts nothing
new and writes nothing; and every conversation is still credited (G118 sibling folding). Synthetic data only.
"""
import asyncio
import hashlib
from types import SimpleNamespace

import pytest

from api.services import engine_errors
from api.services import entity_resolver as er

WORDS = ["alpha", "bravo", "cobalt", "delta", "ember", "fjord", "garnet", "harbor", "indigo", "juniper",
         "kelvin", "lumen", "mosaic", "nectar", "onyx", "prism"]
TYPES = ["concept", "project", "tool", "person"]


def _settings(bank, concurrency):
    return SimpleNamespace(memory_path=bank, litellm_model="synthetic-model", litellm_disambiguation_model="",
                           sleep_promotion_threshold=2, sleep_resolve_concurrency=concurrency)


def _page(name, etype="concept", **fm):
    return {"id": name.lower().replace(" ", "-"), "frontmatter": {"name": name, "type": etype, "confidence": 0.8, **fm},
            "body": f"A synthetic page about {name}."}


def _entity(name, etype, ep, **extra):
    return {"name": name, "type": etype, "confidence": 0.6, "description": f"{name} came up in {ep}.",
            "source_episode": ep, "source_episode_timestamp": f"2026-10-0{1 + int(ep[-1]) % 8}T12:00:00Z", **extra}


def _bank_and_batch():
    """~100 pages and ~60 names that share tokens with them and with each other (in-cycle candidates too)."""
    pages, seen = [], set()
    for i, a in enumerate(WORDS):
        for j, b in enumerate(WORDS):
            if (i * 7 + j * 3) % 5 == 0 and a != b:
                name = f"{a} {b}".title()
                if name.lower() not in seen:
                    seen.add(name.lower())
                    pages.append(_page(name, TYPES[(i + j) % len(TYPES)]))
    extracted = []
    for ep_n in range(6):
        ep = f"ep_2026-10-01_00{ep_n}"
        ents = []
        for k in range(12):
            a, b = WORDS[(ep_n * 5 + k) % len(WORDS)], WORDS[(k * 3 + 1) % len(WORDS)]
            name = (f"{a} {b} hub" if k % 3 == 0 else a if k % 4 == 1 else f"{b} {a}").title()
            extra = {"history_entries": [{"date": "2026-10-01", "event": "e1"}, {"date": "2026-10-02", "event": "e2"}]} \
                if k % 3 == 0 else {}
            ents.append(_entity(name, TYPES[(ep_n + k) % len(TYPES)], ep, **extra))
        extracted.append({"episode_id": ep, "entities": ents, "relationships": []})
    return pages, extracted


def _verdict(new_name, existing_name):
    h = int(hashlib.sha1(f"{new_name}|{existing_name}".encode()).hexdigest()[:6], 16) % 10
    return "same" if h == 0 else "unsure" if h == 1 else "different"


class _Judge:
    """A fake judge: deterministic verdicts, a small latency, the in-flight peak and every pair it saw."""

    def __init__(self, *, delay=0.005, fail_on=None, verdict=None):
        self.verdict = verdict or _verdict
        self.pairs: list[tuple[str, str]] = []
        self.inflight = 0
        self.peak = 0
        self.delay = delay
        self.fail_on = fail_on

    async def __call__(self, new_name, new_type, new_description, existing_name, existing_type, existing_body,
                       settings, **extra):
        self.pairs.append((new_name, existing_name))
        if self.fail_on is not None and len(self.pairs) == self.fail_on:
            raise engine_errors.EngineThrottled("synthetic plan limit")
        self.inflight += 1
        self.peak = max(self.peak, self.inflight)
        try:
            await asyncio.sleep(self.delay)
        finally:
            self.inflight -= 1
        return self.verdict(new_name, existing_name)


@pytest.fixture
def bank(tmp_path, monkeypatch):
    root = tmp_path / "synthetic-bank"
    for name in ("entities", "episodes", "inbox"):
        (root / name).mkdir(parents=True)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(root))
    monkeypatch.setattr(er, "SqliteVecIndexer", lambda *a, **k: None)
    return root


def _run(bank, monkeypatch, concurrency, *, judge=None, cancel_check=None, batch=None):
    judge = judge or _Judge()
    monkeypatch.setattr(er, "_llm_judge_same_entity", judge)
    pages, extracted = batch or _bank_and_batch()
    out = asyncio.run(er.resolve(extracted, pages, _settings(bank, concurrency), cancel_check=cancel_check))
    return out, judge


def _signature(out):
    changes = sorted((c["id"], c["action"], tuple(sorted(c.get("source_episodes") or [])),
                      (c.get("entity") or {}).get("name")) for c in out["changes"])
    return changes, sorted(out["name_to_id"].items())


def test_concurrent_resolution_decides_exactly_as_the_serial_loop(bank, monkeypatch):
    serial, serial_judge = _run(bank, monkeypatch, 1)
    concurrent, concurrent_judge = _run(bank, monkeypatch, 4)
    assert serial_judge.pairs, "the synthetic batch must reach the judge"
    assert any(c["action"] == "create" for c in serial["changes"]), "and promote names (in-cycle candidates)"
    assert _signature(concurrent) == _signature(serial)
    # The same calls — not just the same outcome: early exit and the inline in-cycle judgments are kept.
    assert sorted(concurrent_judge.pairs) == sorted(serial_judge.pairs)


def test_concurrency_is_bounded_and_one_is_the_serial_loop(bank, monkeypatch):
    _, serial = _run(bank, monkeypatch, 1)
    assert serial.peak == 1
    _, three = _run(bank, monkeypatch, 3)
    assert 2 <= three.peak <= 3


def test_a_plan_limit_still_raises_out_of_resolve_and_starts_nothing_more(bank, monkeypatch):
    _, full = _run(bank, monkeypatch, 3)
    filed = sorted((bank / "inbox").iterdir())
    judge = _Judge(fail_on=5)
    with pytest.raises(engine_errors.EngineThrottled):
        _run(bank, monkeypatch, 3, judge=judge)
    # At most the calls already in flight when the limit came back finish; nothing new is started.
    assert len(judge.pairs) <= 5 + 3 < len(full.pairs)
    assert judge.inflight == 0, "no judgment is left running behind the pause"
    assert sorted((bank / "inbox").iterdir()) == filed, "a paused batch files nothing"


def test_a_cancel_starts_no_new_judgment_and_writes_nothing(bank, monkeypatch):
    _, full = _run(bank, monkeypatch, 3)
    filed = sorted((bank / "inbox").iterdir())
    asked = {"n": 0}

    def cancel_after_two_names():
        asked["n"] += 1
        return asked["n"] > 2

    _, judge = _run(bank, monkeypatch, 3, cancel_check=cancel_after_two_names)
    assert len(judge.pairs) < len(full.pairs)
    assert judge.inflight == 0
    assert sorted((bank / "inbox").iterdir()) == filed


def test_a_name_that_matches_an_in_cycle_create_spends_no_lookahead_call(bank, monkeypatch):
    """"Alpha Bravo Hub" direct-matches the in-cycle create "Alpha Bravo Hubs" (fuzzy > 85): the serial loop
    never judged it, and the lookahead must not judge it either."""
    history = {"history_entries": [{"date": "2026-10-01", "event": "e1"}, {"date": "2026-10-02", "event": "e2"}]}
    pages = [_page("Alpha Cobalt", "project")]
    extracted = [{"episode_id": "ep_2026-10-01_001", "relationships": [], "entities": [
        _entity("Alpha Bravo Hubs", "project", "ep_2026-10-01_001", **history),
        _entity("Alpha Bravo Hub", "project", "ep_2026-10-01_001"),
    ]}]
    out, judge = _run(bank, monkeypatch, 4, judge=_Judge(verdict=lambda *a: "different"), batch=(pages, extracted))
    assert judge.pairs == [("Alpha Bravo Hubs", "Alpha Cobalt")]
    assert out["name_to_id"]["alpha bravo hub"] == "alpha-bravo-hubs"


def test_an_in_cycle_candidate_is_still_judged_after_the_existing_ones(bank, monkeypatch):
    history = {"history_entries": [{"date": "2026-10-01", "event": "e1"}, {"date": "2026-10-02", "event": "e2"}]}
    pages = [_page("Delta Onyx", "tool")]
    extracted = [{"episode_id": "ep_2026-10-01_002", "relationships": [], "entities": [
        _entity("Delta Ember Prism", "tool", "ep_2026-10-01_002", **history),
        _entity("Delta", "tool", "ep_2026-10-01_002"),
    ]}]
    def verdict(new, existing):
        return "same" if existing == "Delta Ember Prism" else "different"

    for concurrency in (1, 4):
        out, judge = _run(bank, monkeypatch, concurrency, judge=_Judge(verdict=verdict), batch=(pages, extracted))
        assert judge.pairs == [("Delta Ember Prism", "Delta Onyx"), ("Delta", "Delta Onyx"), ("Delta", "Delta Ember Prism")]
        assert out["name_to_id"]["delta"] == "delta-ember-prism"


def test_every_conversation_is_still_credited_under_concurrency(bank, monkeypatch):
    """G118 sibling folding: a name judged SAME by a lookahead call still credits every conversation."""
    pages = [_page("Garnet Harbor Works", "company")]
    extracted = [{"episode_id": f"ep_2026-10-01_00{n}", "relationships": [],
                  "entities": [_entity("Garnet Harbor", "company", f"ep_2026-10-01_00{n}")]} for n in range(1, 5)]
    out, judge = _run(bank, monkeypatch, 4, judge=_Judge(verdict=lambda *a: "same"), batch=(pages, extracted))
    assert judge.pairs == [("Garnet Harbor", "Garnet Harbor Works")]
    (change,) = out["changes"]
    assert change["id"] == "garnet-harbor-works" and change["action"] == "update"
    assert sorted(change["source_episodes"]) == [f"ep_2026-10-01_00{n}" for n in range(1, 5)]


def test_a_cancel_mid_name_still_finishes_the_name_the_loop_is_on(bank, monkeypatch):
    """The serial loop never stopped inside a name's candidates; the lookahead stops between them on a cancel,
    so the name the loop is waiting on is finished inline — never decided on half its judgments."""
    pages = [_page("Lumen Mosaic", "concept"), _page("Lumen Nectar", "concept"), _page("Lumen Onyx", "concept")]
    extracted = [{"episode_id": "ep_2026-10-01_003", "relationships": [],
                  "entities": [_entity("Lumen", "concept", "ep_2026-10-01_003")]}]
    cancelled = {"now": False}

    def verdict(new, existing):
        cancelled["now"] = True  # the cancel arrives during the name's first call
        return "same" if existing == "Lumen Onyx" else "different"

    out, judge = _run(bank, monkeypatch, 3, judge=_Judge(verdict=verdict), batch=(pages, extracted),
                      cancel_check=lambda: cancelled["now"])
    assert [p[1] for p in judge.pairs] == ["Lumen Mosaic", "Lumen Nectar", "Lumen Onyx"]
    assert out["name_to_id"]["lumen"] == "lumen-onyx"


def _aliased_bank_and_batch():
    """The synthetic batch over a bank whose pages carry aliases that share no word with their names: initials
    (one page each) and a first-word prefix (every page starting with that word: a shared acronym), plus bare
    words the batch also names, so alias holders join token-sharing candidates. Each acronym is named in two
    conversations as the type of one of its holders, so it reaches the judge and can be promoted."""
    pages, extracted = _bank_and_batch()
    acronyms: dict[str, str] = {}
    for i, page in enumerate(pages):
        words = page["frontmatter"]["name"].split()
        alias = "".join(w[0] for w in words).upper() if i % 2 else words[0][:3].upper()
        aliases = [alias] + ([words[-1].lower()] if i % 4 == 0 else [])
        page["frontmatter"]["aliases"] = aliases
        acronyms.setdefault(alias, page["frontmatter"]["type"])
    for n, (acronym, etype) in enumerate(sorted(acronyms.items())):
        for extraction in (extracted[n % len(extracted)], extracted[(n + 1) % len(extracted)]):
            extraction["entities"].append(_entity(acronym, etype, extraction["episode_id"]))
    return pages, extracted


def test_alias_candidates_decide_exactly_as_the_serial_loop(bank, monkeypatch):
    def verdict(new_name, existing_name):  # every outcome, on alias candidates too
        h = int(hashlib.sha1(f"{new_name}|{existing_name}".encode()).hexdigest()[:6], 16) % 3
        return ("same", "unsure", "different")[h]

    batch = _aliased_bank_and_batch()
    serial, serial_judge = _run(bank, monkeypatch, 1, batch=batch, judge=_Judge(verdict=verdict))
    concurrent, concurrent_judge = _run(bank, monkeypatch, 4, batch=_aliased_bank_and_batch(),
                                        judge=_Judge(verdict=verdict))
    acronyms = {p["frontmatter"]["aliases"][0].lower(): p["id"] for p in batch[0]}
    page_ids = {p["id"] for p in batch[0]}
    assert any(new.lower() in acronyms for new, _ in serial_judge.pairs), "acronyms must reach their pages"
    assert any(serial["name_to_id"].get(a) in page_ids for a in acronyms), "and some land on one"
    assert any(serial["name_to_id"].get(a) == a for a in acronyms), "and some get their own page"
    assert _signature(concurrent) == _signature(serial)
    assert sorted(concurrent_judge.pairs) == sorted(serial_judge.pairs)
