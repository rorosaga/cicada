"""Ruling 71 — the inbox is ordered by the expected change in what gets read (``question_order``).

Synthetic bank, invented names. The argued pairs below are the evidence for the formula: each pair says which question
should come first and WHY, and four formulations are run on every pair - F0 (the old order), F1 (additive), F2 (the
product without the visibility term) and F3 (production). F0-F2 are small functions in this file, not in production.
``test_the_table`` records which formulation fails which pair; ``test_f3_passes_every_argued_pair`` is the gate.

Every constant in the formula is judgment on two recorded answers (there is no outcome data): the pairs are the argument,
not a fit. A pair is never changed to make F3 pass.
"""
from __future__ import annotations

import math
import subprocess
from datetime import date, timedelta

import pytest

from api.services import (bank_index, bank_registry, inbox_service, markdown_parser, page_reads, page_use,
                          pending_store, question_order)
from api.services.claims import Claim, write_claims

TODAY = date.today()
OWNER = "owner-example"


def d(days: int) -> str:
    return (TODAY + timedelta(days=days)).isoformat()


def _git(bank, *args):
    return subprocess.run(["git", *args], cwd=bank, capture_output=True, text=True, check=True).stdout


def page(bank, pid, *, name=None, type_="concept", said=-5, convs=1, claims=0, claim_eps=None, **extra):
    """``claim_eps`` maps a claim's index to its ``source_episodes`` (default: one undated id, which says nothing of when)."""
    fm = {"type": type_, "name": name or pid.replace("-", " ").title(), "status": "active", "confidence": 0.7,
          "created": d(-400), "last_referenced": d(said),
          "source_episodes": [f"ep_{d(-i - 1)}_001" for i in range(convs)], "related": [], **extra}
    body = f"# {fm['name']}\n"
    if claims:
        rows = [Claim(id=f"clm_{pid}_{i}", text=f"fact {i}", subject=pid, predicate="note", object=f"o{i}",
                      object_kind="literal", valid_from=d(-30), recorded_at=d(-30),
                      source_episodes=list((claim_eps or {}).get(i, ["ep_x"])))
                for i in range(claims)]
        body = write_claims(body, rows)
    markdown_parser.write(bank / "entities" / f"{pid}.md", fm, body)
    bank_index.invalidate()
    page_use.reset()


def item(bank, num, **fm):
    base = {"kind": "conflict", "status": "pending", "priority": 0.8, "created_date": d(-1), "required_input": "choice"}
    path = bank / "inbox" / f"inbox-{num:03d}.md"
    markdown_parser.write(path, {**base, **fm}, "body")
    bank_index.invalidate()
    return path.stem


def options(n: int, page_id: str, *, start: int = 0, observed: str | None = None, last_ref: str | None = None) -> list[dict]:
    """``n`` contested options on claims ``start..``; ``observed``/``last_ref`` are the dates the generator stores."""
    out = []
    for i in range(start, start + n):
        o = {"key": f"o{i}", "label": f"v{i}", "claim_id": f"clm_{page_id}_{i}"}
        if observed:
            o["observed_at"] = observed
        if last_ref or observed:
            o["last_referenced"] = last_ref or observed
        out.append(o)
    return out


def ep(days: int) -> list[str]:
    """One source episode said ``days`` from today (negative: ago); its id carries the conversation's own day."""
    return [f"ep_{d(days)}_001"]


@pytest.fixture(autouse=True)
def _counter_on(monkeypatch):
    monkeypatch.setenv("CICADA_TELEMETRY", "on")
    page_reads.reset()
    question_order.reset()
    yield
    page_reads.reset()
    question_order.reset()


@pytest.fixture
def bank(tmp_path):
    b = tmp_path / "bank"
    for sub in ("entities", "inbox", "episodes"):
        (b / sub).mkdir(parents=True)
    markdown_parser.write(b / "_state.md", {"type": "state", "owner_id": OWNER}, "")
    # The owner's page is evergreen on a real bank (`owner_identity` writes it): "never archived", not "every fact true".
    page(b, OWNER, name="Owner Example", type_="person", convs=40, decay_class="evergreen", decay_rate=0.0)
    _git(b, "init", "-q")
    _git(b, "config", "user.email", "t@example.com")
    _git(b, "config", "user.name", "t")
    _git(b, "add", "-A")
    _git(b, "commit", "-qm", "init")
    bank_registry.ensure_bank_ids(b)
    bank_index.invalidate()
    page_use.reset()
    return b


def open_pages(bank, page_id, days, surface="app"):
    """Count ``page_id`` on each of the last ``days`` days (yesterday back)."""
    for k in range(days, 0, -1):   # oldest first: a day's count only ever comes after the earlier ones
        page_reads.count(bank, page_id, surface, today=TODAY - timedelta(days=k))
    page_reads.reset()   # a fresh process: nothing memoised, the file is the only memory


# --------------------------------------------------------------------------- the formulations


def f0(t: question_order.Tables, fm: dict, parts: question_order.Parts) -> float:
    """The old order: stored priority + 0.5 x the busier page's use (``page_use.rank``)."""
    ids = [str(fm.get("entity_id") or ""), str(fm.get("merge_target_hint") or "")]
    use = max((t.use.get(i, 0.0) for i in ids if i), default=0.0)
    return float(fm.get("priority") or 0.0) + 0.5 * use


def f1(t: question_order.Tables, fm: dict, parts: question_order.Parts) -> float:
    """Additive: priority + 0.5 use + 0.5 log-impact (reach on a log scale, saturating at ~127 claims)."""
    return f0(t, fm, parts) + 0.5 * min(1.0, math.log2(1 + parts.reach) / 7.0)


def f2(t: question_order.Tables, fm: dict, parts: question_order.Parts) -> float:
    """The product WITHOUT the visibility term: reach counts in full, whatever page it lives on."""
    seen = min(float(question_order.SHOWN), float(parts.reach))
    return (parts.p * parts.stake / parts.effort * (question_order.FLOOR + t.exposure(parts.pages))
            * math.sqrt(max(0.0, seen)))


def f3(t: question_order.Tables, fm: dict, parts: question_order.Parts) -> float:
    """Production."""
    return t.score(fm, informational=bool(fm.get("_informational")))


FORMULATIONS = {"F0": f0, "F1": f1, "F2": f2, "F3": f3}


def key(score: float, fm: dict, ident: str):
    """The production sort key: score, then newest, then id."""
    return (-score, inbox_service._neg_date_key(str(fm.get("created_date") or "")), ident)


# --------------------------------------------------------------------------- the argued pairs


def build_pairs(bank):
    """Writes every pair's pages and questions; returns ``[(name, reason, better_id, worse_id)]``.

    The worse question of each pair is the NEWER one with the lower id, so a tie in score falls to it: a formulation
    passes a pair only by scoring the better question strictly higher."""
    pairs = []
    num = [0]

    def new(**fm):
        num[0] += 1
        return item(bank, num[0], **fm)

    # Shared pages. `hub` is the busiest page in the bank (use 1.0) and holds 8,000 claims.
    page(bank, "hub", convs=30, said=-2, claims=8000)
    page(bank, "mid-a", convs=4, said=-10, claims=40)
    pending_store.save(bank, [pending_store.PendingEntity(
        name="Held Name", type="concept", description="", source_episode="ep_x", confidence=0.5, tags=[],
        history_entries=[], held_claims=[{"id": "h1"}, {"id": "h2"}])])

    # 1. a one-mention held name that only inherits a huge page's use < a conflict on a moderately used page
    worse = new(kind="merge_suggestion", priority=0.5, entity_id="held-name", entity_name="Held Name",
                merge_target_hint="hub", required_input="merge", created_date=d(0))
    better = new(kind="conflict", entity_id="mid-a", entity_name="Mid A", predicate="uses",
                 options=options(2, "mid-a"), created_date=d(-1))
    pairs.append(("held name on a huge page < conflict on a moderate page",
                  "answering the held name moves 3 claims that live among 8,000 nobody reads whole; the conflict "
                  "settles two beliefs on a page read now", better, worse))

    # 2. a same-person pair of two mid pages > one conflict on an 8,000-claim hub
    page(bank, "pair-a", type_="person", convs=4, said=-10, claims=60)
    page(bank, "pair-b", type_="person", convs=4, said=-10, claims=60)
    worse = new(kind="conflict", entity_id="hub", entity_name="Hub", predicate="uses", options=options(2, "hub"),
                created_date=d(0))
    better = new(kind="merge_suggestion", priority=0.5, entity_id="pair-a", entity_name="Pair A",
                 merge_target_hint="pair-b", suggested_confidence=0.7, suggested_classification="person",
                 required_input="merge", created_date=d(-1))
    pairs.append(("same-person pair of two mid pages > conflict on an 8,000-claim hub",
                  "a join moves ~60 claims between two pages a reader meets; two claims among 8,000 are almost "
                  "never in front of one", better, worse))

    # 3. opened daily, rarely talked about > the same question on an unopened page
    page(bank, "quiet-opened", convs=1, said=-200, claims=10)
    page(bank, "quiet-unopened", convs=1, said=-200, claims=10)
    open_pages(bank, "quiet-opened", 20, "app")
    worse = new(kind="conflict", entity_id="quiet-unopened", entity_name="Quiet Unopened", predicate="uses",
                options=options(2, "quiet-unopened"), created_date=d(0))
    better = new(kind="conflict", entity_id="quiet-opened", entity_name="Quiet Opened", predicate="uses",
                 options=options(2, "quiet-opened"), created_date=d(-1))
    pairs.append(("opened daily, rarely talked about > the same question unopened",
                  "use is derived from what was said; the reads say the page is in front of the person every day",
                  better, worse))

    # 4. a big merge on a page nobody opens > a trivial question on a moderately busy page
    page(bank, "big-a", type_="person", convs=1, said=-300, claims=200)
    page(bank, "big-b", type_="person", convs=1, said=-300, claims=200)
    page(bank, "busy-mid", convs=4, said=-10, claims=20)
    worse = new(kind="clarification", priority=0.4, entity_id="busy-mid", entity_name="Busy Mid", required_input="freetext",
                created_date=d(0))
    better = new(kind="merge_suggestion", priority=0.5, entity_id="big-a", entity_name="Big A", merge_target_hint="big-b",
                 suggested_confidence=0.6, suggested_classification="person", required_input="merge", created_date=d(-1))
    pairs.append(("big merge on an unopened page > trivial question on a moderately busy page",
                  "the floor keeps a large question from sinking on a quiet page: 400 claims change for whoever opens "
                  "it, one claim is added on the busy page", better, worse))

    # 5. recall-only < opened (the same number of days, equally used pages)
    page(bank, "shown-only", convs=1, said=-200, claims=10)
    page(bank, "was-opened", convs=1, said=-200, claims=10)
    open_pages(bank, "shown-only", 10, "mcp-recall")
    open_pages(bank, "was-opened", 10, "mcp")
    worse = new(kind="conflict", entity_id="shown-only", entity_name="Shown Only", predicate="uses",
                options=options(2, "shown-only"), created_date=d(0))
    better = new(kind="conflict", entity_id="was-opened", entity_name="Was Opened", predicate="uses",
                 options=options(2, "was-opened"), created_date=d(-1))
    pairs.append(("recall-only < opened",
                  "a page recall suggested may never have been read; a page someone opened was", better, worse))

    # 6. a 5-way conflict > a 2-way one (same page)
    page(bank, "five", convs=4, said=-10, claims=20)
    worse = new(kind="conflict", entity_id="five", entity_name="Five", predicate="uses", options=options(2, "five"),
                created_date=d(0))
    better = new(kind="conflict", entity_id="five", entity_name="Five", predicate="lives-in", options=options(5, "five"),
                 created_date=d(-1))
    pairs.append(("5-way conflict > 2-way", "settling five contested claims changes more of the page than two",
                  better, worse))

    # 7. a choice > free text, otherwise equal
    page(bank, "effort", convs=4, said=-10, claims=20)
    worse = new(kind="clarification", priority=0.4, entity_id="effort", entity_name="Effort", required_input="freetext",
                created_date=d(0))
    better = new(kind="clarification", priority=0.4, entity_id="effort", entity_name="Effort", required_input="choice",
                 created_date=d(-1))
    pairs.append(("choice > free text, otherwise equal", "one tap costs the person less than writing a sentence",
                  better, worse))

    # 8. informational last: a conflict the vocabulary calls a set is shown, never asked
    page(bank, "info", convs=4, said=-10, claims=20)
    worse = new(kind="conflict", entity_id="info", entity_name="Info", predicate="uses", options=options(5, "info"),
                created_date=d(0), _informational=True)
    better = new(kind="decay", priority=0.3, entity_id="info", entity_name="Info", claim_id="clm_info_0",
                 created_date=d(-1))
    pairs.append(("informational conflict last", "a set of true values is shown, never asked: an answer changes nothing",
                  better, worse))

    # ---- staleness (Rodrigo 2026-11-06, requirement 1). The shape of his complaint: both options said over a year ago,
    # one option's `last_referenced` bumped to today by a later re-reference, and the question itself created today.
    # 9. an old conflict < a recent one of the same stake on the same page
    page(bank, "stale-page", convs=4, said=-10, claims=40,
         claim_eps={0: ep(-400), 1: ep(-400), 2: ep(-3), 3: ep(-3), 4: ep(-400), 5: ep(-3), 6: ep(-400), 7: ep(-400)})
    worse = new(kind="conflict", entity_id="stale-page", entity_name="Stale Page", predicate="pays",
                options=[*options(1, "stale-page", start=0, observed=d(-400), last_ref=d(0)),
                         *options(1, "stale-page", start=1, observed=d(-400))], created_date=d(0))
    better = new(kind="conflict", entity_id="stale-page", entity_name="Stale Page", predicate="lives-in",
                 options=options(2, "stale-page", start=2, observed=d(-3)), created_date=d(-1))
    pairs.append(("conflict said over a year ago < a recent conflict of the same stake",
                  "what was said a year ago has mostly changed or stopped mattering, however recently it was re-referenced "
                  "or the question was asked", better, worse))

    # 10. a fact said again recently > the same shape said once long ago
    worse = new(kind="conflict", entity_id="stale-page", entity_name="Stale Page", predicate="owes",
                options=[*options(1, "stale-page", start=4, observed=d(-400)), *options(1, "stale-page", start=6, observed=d(-400))],
                created_date=d(0))
    better = new(kind="conflict", entity_id="stale-page", entity_name="Stale Page", predicate="owes-to",
                 options=[*options(1, "stale-page", start=5, observed=d(-400)), *options(1, "stale-page", start=7, observed=d(-400))],
                 created_date=d(-1))
    pairs.append(("a fact said again recently > the same fact said once, long ago",
                  "a newer source episode on the claim says it is still being said, whatever its first `observed_at`",
                  better, worse))

    # 11. an old fact on a small page opened daily > the same fact on a page nobody opens
    page(bank, "old-small-opened", convs=1, said=-300, claims=12, claim_eps={0: ep(-400), 1: ep(-400)})
    page(bank, "old-small-quiet", convs=1, said=-300, claims=12, claim_eps={0: ep(-400), 1: ep(-400)})
    open_pages(bank, "old-small-opened", 20, "app")
    worse = new(kind="conflict", entity_id="old-small-quiet", entity_name="Old Small Quiet", predicate="pays",
                options=options(2, "old-small-quiet", observed=d(-400)), created_date=d(0))
    better = new(kind="conflict", entity_id="old-small-opened", entity_name="Old Small Opened", predicate="pays",
                 options=options(2, "old-small-opened", observed=d(-400)), created_date=d(-1))
    pairs.append(("old fact on a small page opened daily > the same fact on an unopened page",
                  "old but in daily use is not stale: the person reads that page every day", better, worse))

    # 12. an old fact on a small page opened daily > the same on a very large page opened daily
    page(bank, "old-big-opened", convs=1, said=-300, claims=8000, claim_eps={0: ep(-400), 1: ep(-400)})
    open_pages(bank, "old-big-opened", 20, "app")
    worse = new(kind="conflict", entity_id="old-big-opened", entity_name="Old Big Opened", predicate="pays",
                options=options(2, "old-big-opened", observed=d(-400)), created_date=d(0))
    better = new(kind="conflict", entity_id="old-small-opened", entity_name="Old Small Opened", predicate="lives-in",
                 options=options(2, "old-small-opened", observed=d(-400)), created_date=d(-1))
    pairs.append(("old fact on a small page opened daily > the same on a very large page opened daily",
                  "opening a hub every day puts about 30 of its 8,000 claims in front of a reader: it does not keep "
                  "every old fact on it from fading", better, worse))
    return pairs


def measure(bank):
    pairs = build_pairs(bank)
    t = question_order.tables(bank)
    table = {}
    for name, reason, better, worse in pairs:
        row = {}
        fb = dict(markdown_parser.parse(bank / "inbox" / f"{better}.md").frontmatter)
        fw = dict(markdown_parser.parse(bank / "inbox" / f"{worse}.md").frontmatter)
        for label, fn in FORMULATIONS.items():
            sb = fn(t, fb, t.parts(fb, informational=bool(fb.get("_informational"))))
            sw = fn(t, fw, t.parts(fw, informational=bool(fw.get("_informational"))))
            row[label] = (key(sb, fb, better) < key(sw, fw, worse)) and sb != sw
        table[name] = row
    return pairs, table


def test_the_pairs_stand_on_the_use_they_name(bank):
    """The setup is what each pair says it is - a pair resting on an accident of the fixture proves nothing."""
    build_pairs(bank)
    use = page_use.scores(bank)
    assert use["hub"] == 1.0 or use["hub"] >= max(v for k, v in use.items() if k not in (OWNER, "hub"))
    assert 0.2 < use["mid-a"] < 0.7 and 0.2 < use["busy-mid"] < 0.7
    assert use["big-a"] < 0.1 and use["quiet-opened"] < 0.1 and use["quiet-unopened"] < 0.1
    assert abs(use["quiet-opened"] - use["quiet-unopened"]) < 1e-9
    assert abs(use["shown-only"] - use["was-opened"]) < 1e-9
    t = question_order.tables(bank)
    assert t.claims("hub") == 8000 and t.claims("pair-a") == 60 and t.held("Held Name") == 2


def test_f3_passes_every_argued_pair(bank):
    pairs, table = measure(bank)
    failed = [name for name, row in table.items() if not row["F3"]]
    assert failed == [], f"F3 fails an argued pair (report it, do not tune it away): {failed}"


HELD, PAIR, OPENED, BIG, RECALL, FIVE, EFFORT, INFO, OLD, AGAIN, RELIEF, HUB = (
    "held name on a huge page < conflict on a moderate page",
    "same-person pair of two mid pages > conflict on an 8,000-claim hub",
    "opened daily, rarely talked about > the same question unopened",
    "big merge on an unopened page > trivial question on a moderately busy page",
    "recall-only < opened", "5-way conflict > 2-way", "choice > free text, otherwise equal",
    "informational conflict last",
    "conflict said over a year ago < a recent conflict of the same stake",
    "a fact said again recently > the same fact said once, long ago",
    "old fact on a small page opened daily > the same fact on an unopened page",
    "old fact on a small page opened daily > the same on a very large page opened daily")
#: Measured by ``test_the_table`` (pinned so the docs' table cannot drift from what the code does). F0 passes only the
#: held-name pair, by a margin its use term alone happens to give (a conflict outranks a merge by priority, and the
#: mid page is used); F1 cannot see reads, effort, p, dilution or age; F2 sees reads, effort and p but not that three
#: claims among 8,000 are almost never in front of a reader, nor that a fact said a year ago asks less (the four staleness
#: pairs; only the unopened-versus-opened one it passes, through reads in its exposure).
EXPECTED_FAILURES = {
    "F0": {PAIR, OPENED, BIG, RECALL, FIVE, EFFORT, INFO, OLD, AGAIN, RELIEF, HUB},
    "F1": {HELD, PAIR, OPENED, RECALL, EFFORT, INFO, OLD, AGAIN, RELIEF, HUB},
    "F2": {HELD, OLD, AGAIN, HUB},
}


def test_the_table(bank, capsys):
    pairs, table = measure(bank)
    lines = ["pair".ljust(78) + "  F0   F1   F2   F3"]
    for name, row in table.items():
        lines.append(name.ljust(78) + "  " + "   ".join("ok" if row[f] else "NO" for f in FORMULATIONS))
    fails = {f: {n for n, row in table.items() if not row[f]} for f in FORMULATIONS}
    with capsys.disabled():
        print("\n" + "\n".join(lines))
    assert {f: v for f, v in fails.items() if f != "F3"} == EXPECTED_FAILURES


# --------------------------------------------------------------------------- the counter and the order


def _ranked(bank, reads=True):
    t = question_order.tables(bank, reads=reads)
    rows = []
    for f in sorted((bank / "inbox").glob("inbox-*.md")):
        fm = dict(markdown_parser.parse(f).frontmatter)
        rows.append((key(t.score(fm), fm, f.stem), f.stem))
    return [stem for _k, stem in sorted(rows)]


def test_an_empty_or_wiped_or_unreadable_counter_orders_like_reads_off(bank):
    build_pairs(bank)
    page_reads.reset()
    question_order.reset()
    with_reads = _ranked(bank)
    off = _ranked(bank, reads=False)
    assert with_reads != off, "the fixture's counter must matter, or this proves nothing"
    # wiped: the file is gone
    key_ = page_reads.bank_key(bank)
    for f in page_reads._files(key_):
        f.unlink(missing_ok=True)
    page_reads.reset()
    assert _ranked(bank) == off
    # unreadable: garbage where the file was
    page_reads.path_for(key_).write_bytes(b"this is not a database" * 40)
    page_reads.reset()
    assert _ranked(bank) == off
    # absent entirely: another memory that never counted
    assert _ranked(bank, reads=False) == off


def test_the_remote_doors_order_is_computed_without_the_counter(bank):
    from api.services import mcp_tools

    build_pairs(bank)
    page_reads.reset()
    seen = []
    real = question_order.tables

    def spy(memory_path, **kw):
        seen.append(kw.get("reads", True))
        return real(memory_path, **kw)

    import pytest as _p  # noqa: F401
    mp = _p.MonkeyPatch()
    mp.setattr(question_order, "tables", spy)
    try:
        for connector in (None, "conn-1"):
            ctx = mcp_tools.ToolContext(memory_path=lambda: bank, session_id="s", harness="claude-code",
                                        connector_id=connector)
            mcp_tools.ask_nudges(ctx, "uses the quiet opened page")
    finally:
        mp.undo()
    assert seen == [True, False]


def test_a_bad_item_falls_back_to_its_priority_and_the_inbox_still_loads(bank, monkeypatch):
    page(bank, "fine", convs=4, said=-10, claims=20)
    page(bank, "broken", convs=4, said=-10, claims=20)
    ok = item(bank, 1, entity_id="fine", entity_name="Fine", predicate="uses", options=options(2, "fine"), title="t")
    bad = item(bank, 2, entity_id="broken", entity_name="Broken", predicate="uses", options=options(2, "broken"),
               title="t", priority=0.35)
    real = question_order.claim_count

    def boom(mp, pid):
        if pid == "broken":
            raise ValueError("unreadable")
        return real(mp, pid)

    monkeypatch.setattr(question_order, "claim_count", boom)
    inbox_service.reset_built()
    ids = [i.id for i in inbox_service.load_inbox(bank)]
    assert set(ids) == {ok, bad}
    t = question_order.tables(bank)
    assert t.score({"kind": "conflict", "entity_id": "broken", "priority": 0.35,
                    "options": options(2, "broken")}) == 0.35


def test_sensitive_sits_on_the_formulas_scale():
    assert 0.01 < question_order.SENSITIVE_SCORE < 6


def test_a_still_question_reads_the_topic_page_alone_and_an_older_one_earns_the_floor(bank):
    """`parts.pages` once held `[owner, object]` and `exposure` takes the busiest page: the owner's page is pinned at 1.0, so
    every "still?" scored full exposure whatever its topic."""
    page(bank, "busy", convs=30, said=-2, claims=10)   # use is relative to the busiest page that is not the owner's
    page(bank, "topic", convs=1, said=-300, claims=10)
    page(bank, OWNER, name="Owner Example", type_="person", convs=40, claims=6000, decay_class="evergreen", decay_rate=0.0)
    t = question_order.tables(bank)
    still = {"kind": "conflict", "asks": "still", "entity_id": OWNER, "object_id": "topic", "priority": 0.5,
             "options": [{"key": "a", "label": "x", "claim_id": "clm_1"}, {"key": "neither", "label": "Not anymore"}]}
    parts = t.parts(still)
    assert parts.n == 0 and parts.pages == ["topic"]
    assert t.use[OWNER] == 1.0 and t.use["topic"] < 0.1
    assert t.exposure(parts.pages) == pytest.approx(t.use["topic"]) and t.use["topic"] < 0.1, "the topic page's exposure, not the owner's"
    older = {k: v for k, v in still.items() if k != "object_id"}
    assert t.parts(older).pages == [] and t.exposure(t.parts(older).pages) == 0.0
    expected = 0.5 * question_order.FLOOR   # p x (FLOOR + 0) x sqrt(1)
    assert t.score(older) == pytest.approx(expected)
    assert t.score(older) < t.score(still) < 0.5 * (question_order.FLOOR + 0.1)
    assert t.parts(still).said is None, "with no date to go on it does not fade"


def test_kinds_have_a_reach_of_at_least_one_and_a_removal_never_scores_zero(bank):
    page(bank, "gone-empty", convs=4, said=-10, claims=0)
    t = question_order.tables(bank)
    assert t.score({"kind": "removal", "entity_id": "gone-empty", "priority": 0.4}) > 0
    assert t.score({"kind": "decay", "entity_id": "gone-empty", "priority": 0.4}) > 0
    assert t.score({"kind": "merge_suggestion", "entity_id": "nobody", "merge_target_hint": "nobody-else",
                    "suggested_confidence": "not a number"}) > 0


def test_a_held_name_person_pair_gets_the_who_someone_is_stake_from_the_stored_string(bank):
    """`entity_resolver` stores "person - could refer to the same person as X", not the bare type: comparing the raw
    string to {"person"} never matched, so a held-name pair never got its 1.5."""
    page(bank, "known-person", type_="person", convs=4, said=-10, claims=20)
    page(bank, "a-tool", type_="tool", convs=4, said=-10, claims=20)
    t = question_order.tables(bank)
    stored = "person \u2014 could refer to the same person as Known Person"
    held = {"kind": "merge_suggestion", "entity_id": "no-page-yet", "entity_name": "No Page Yet",
            "merge_target_hint": "known-person", "suggested_classification": stored, "priority": 0.5}
    assert t.parts(held).stake == 1.5
    assert t.parts({**held, "suggested_classification": "person"}).stake == 1.5
    tool = {**held, "merge_target_hint": "a-tool", "suggested_classification": "tool \u2014 could refer to the same entity as A Tool"}
    assert t.parts(tool).stake == 1.0
    assert t.parts({**held, "suggested_classification": "concept \u2014 could refer to the same thing as Known Person"}).stake == 1.0


def test_a_merge_side_with_no_page_counts_no_claims_not_the_other_sides(bank):
    page(bank, "big-target", convs=4, said=-10, claims=300)
    t = question_order.tables(bank)
    parts = t.parts({"kind": "merge_suggestion", "entity_id": "no-page-yet", "entity_name": "No Page Yet",
                     "merge_target_hint": "big-target", "priority": 0.5})
    assert parts.reach == 1, "the held name moves nothing and holds nothing"
    page(bank, "small-side", convs=4, said=-10, claims=12)
    both = t.parts({"kind": "merge_suggestion", "entity_id": "small-side", "merge_target_hint": "big-target"})
    assert both.reach == 13 and both.n == 312


def test_plain_clarifications_add_one_claim_and_a_name_ask_earns_the_page(bank):
    page(bank, "role-person", type_="person", convs=2, said=-10, claims=50)
    t = question_order.tables(bank)
    plain = t.parts({"kind": "clarification", "entity_id": "role-person", "priority": 0.4})
    name = t.parts({"kind": "clarification", "asks": "name", "entity_id": "role-person", "priority": 0.4})
    assert plain.reach == 1 and name.reach == 50 and name.stake == 1.5


def test_a_divergence_has_a_reach_of_two_and_a_page_edit_counts_its_changes(bank):
    page(bank, "edit-me", convs=2, said=-10, claims=100)
    t = question_order.tables(bank)
    assert t.parts({"kind": "divergence", "entity_id": "edit-me"}).reach == 2
    edit = {"kind": "page_edit", "entity_id": "edit-me",
            "edit": {"edits": [{"old": "a", "new": "b"}], "add_aliases": ["x"], "remove_aliases": ["y", "z"]}}
    parts = t.parts(edit)
    assert parts.reach == 4 and parts.n == 0, "prose has its own read budget: visibility 1"
    join = {"kind": "page_edit", "entity_id": "edit-me", "join": {"op": "merge", "into": "edit-me"}}
    assert t.parts(join).reach == 101


def test_the_sources_review_counts_its_rows_at_half_the_stake(bank):
    t = question_order.tables(bank)
    parts = t.parts({"kind": "clarification", "asks": "sources", "entity_id": "x",
                     "rows": [{"id": "1", "page": "p1", "ref": "r"}, {"id": "2", "page": "p2", "ref": "r"}]})
    assert parts.reach == 2 and parts.stake == 0.5 and parts.pages == ["p1", "p2"]


def test_the_impact_bucket_is_an_enum_of_the_score():
    assert question_order.bucket(2.0) == "high" and question_order.bucket(0.5) == "mid"
    assert question_order.bucket(0.01) == "low" and question_order.bucket(None) is None


def test_claim_counts_are_raw_counts_memoised_by_the_files_stamp(bank):
    page(bank, "counted", claims=7)
    assert question_order.claim_count(bank, "counted") == 7
    ledger = bank / "entities" / "counted.claims.jsonl"
    ledger.write_text('{"id": "clm_extra_1", "text": "x"}\n{"id": "clm_extra_2", "text": "y"}\n', encoding="utf-8")
    assert question_order.claim_count(bank, "counted") == 9, "a ledger line counts and moves the stamp"
    assert question_order.claim_count(bank, "never-existed") == 0


def test_a_new_still_question_names_its_topic(bank):
    from api.services import still_questions

    cand = still_questions.Candidate(claim_id="clm_1", predicate="works-at", family="role", label="Org Gamma",
                                     object_id="org-gamma", last_said=d(-200), said_in=3, episode="ep_x", cue=None, use=0.1)
    fm = still_questions.item_frontmatter(OWNER, "Owner Example", cand, TODAY)
    assert fm["object_id"] == "org-gamma"
    cand2 = still_questions.Candidate(claim_id="clm_2", predicate="works-at", family="role", label="Org Delta",
                                      object_id="", last_said=d(-200), said_in=3, episode="", cue=None, use=0.0)
    assert "object_id" not in still_questions.item_frontmatter(OWNER, "Owner Example", cand2, TODAY)


# --------------------------------------------------------------------------- staleness (Rodrigo 2026-11-06, requirement 1)
#
# The shape of his complaint, with invented values: a conflict on the owner's evergreen page, both options said over a
# year ago, one option's `last_referenced` read today (a later re-reference), the question created today.

ACTIVE_HALF_LIFE = math.log(2) / 0.05 * 7   # ln2 / the active rate, in days: ~97


def conflict(page_id, *, start=0, observed=None, last_ref=None, n=2, **extra):
    return {"kind": "conflict", "entity_id": page_id, "priority": 0.8, "created_date": d(0),
            "options": options(n, page_id, start=start, observed=observed, last_ref=last_ref), **extra}


def owner_with_old_and_recent(bank, claims=600):
    page(bank, OWNER, name="Owner Example", type_="person", convs=40, claims=claims,
         decay_class="evergreen", decay_rate=0.0,
         claim_eps={0: ep(-400), 1: ep(-400), 2: ep(-3), 3: ep(-3)})


def test_the_shape_of_the_complaint_falls_far_below_a_recent_conflict_and_does_not_lead_the_owners_page(bank):
    """Both options said over a year ago on the owner's page (evergreen: never archived, but not every fact stays true)."""
    owner_with_old_and_recent(bank)
    page(bank, "other", convs=4, said=-10, claims=20)
    t = question_order.tables(bank)
    old = conflict(OWNER, start=0, observed=d(-400), last_ref=d(0))
    recent = conflict(OWNER, start=2, observed=d(-3))
    ratio = t.score(old) / t.score(recent)
    assert ratio < 0.1, f"a year-old conflict must score well under a recent one of the same stake, got {ratio:.3f}"
    assert t.parts(old).half_life == pytest.approx(ACTIVE_HALF_LIFE, rel=1e-6), "the owner's page fades at the active rate"
    # the queue of the owner's page: the old question was created TODAY, three newer-in-substance ones wait behind it
    # one single-valued predicate throughout: a multi-valued one is "informational" at read (p .05), which is another test
    item(bank, 1, entity_id=OWNER, entity_name="Owner Example", predicate="lives-in", created_date=d(0),
         options=options(1, OWNER, start=0, observed=d(-400), last_ref=d(0)) + options(1, OWNER, start=1, observed=d(-400)))
    for num, lo in enumerate([2, 3, 2], start=2):
        item(bank, num, entity_id=OWNER, entity_name="Owner Example", predicate="lives-in", created_date=d(-1),
             options=options(2 if lo == 2 else 1, OWNER, start=lo, observed=d(-3)))
    order = _ranked(bank)
    assert order[-1] == "inbox-001" and set(order) == {"inbox-001", "inbox-002", "inbox-003", "inbox-004"}, order
    inbox_service.reset_built()
    served = [i.id for i in inbox_service.load_inbox(bank)]
    assert served[-1] == "inbox-001", "the served list agrees with the scorer"


def test_a_later_re_reference_or_a_question_created_today_does_not_rescue_an_old_fact(bank):
    """`last_referenced` is bumped by a re-reference and `created_date` is when the question was asked: neither says when
    the fact was said, which is what ages it."""
    owner_with_old_and_recent(bank)
    t = question_order.tables(bank)
    bumped = conflict(OWNER, observed=d(-400), last_ref=d(0), created_date=d(0), updated_date=d(0), recorded_at=d(0))
    quiet = conflict(OWNER, observed=d(-400), last_ref=d(-400), created_date=d(-400), updated_date=d(-400))
    assert t.score(bumped) == pytest.approx(t.score(quiet))
    assert t.parts(bumped).said == date.fromisoformat(d(-400))


def test_a_fact_said_again_recently_counts_as_fresh(bank):
    """A newer episode in the claim's `source_episodes` on the page is the fact being said again."""
    page(bank, "again", convs=4, said=-10, claims=20, claim_eps={0: ep(-400) + ep(-2), 1: ep(-400)})
    page(bank, "once", convs=4, said=-10, claims=20, claim_eps={0: ep(-400), 1: ep(-400)})
    t = question_order.tables(bank)
    again = conflict("again", observed=d(-400))
    once = conflict("once", observed=d(-400))
    assert t.parts(again).said == date.fromisoformat(d(-2))
    assert t.freshness(t.parts(again)) > 0.95
    assert t.freshness(t.parts(once)) < 0.1
    assert t.score(again) > 8 * t.score(once)


def test_one_side_being_recent_makes_the_conflict_fresh(bank):
    page(bank, "mixed", convs=4, said=-10, claims=20, claim_eps={0: ep(-400), 1: ep(-5)})
    t = question_order.tables(bank)
    fm = conflict("mixed", observed=d(-400))
    assert t.parts(fm).said == date.fromisoformat(d(-5))
    assert t.freshness(t.parts(fm)) > 0.9
    # the synthetic `both` says nothing of when, even when it carries a date
    with_both = {**fm, "options": [*fm["options"], {"key": "both", "label": "both", "observed_at": d(0)}]}
    assert t.parts(with_both).said == date.fromisoformat(d(-5))


def test_a_conflict_with_no_claims_ages_by_its_source_episode_never_the_day_it_was_raised(bank):
    """`build_entity_question` stamps `observed_at` with today: on a real bank that read 130 old description conflicts as
    days old. The question's `source_episode` is when it was said."""
    page(bank, "described", convs=4, said=-10, claims=20)
    t = question_order.tables(bank)
    raised_today = [{"key": "a", "label": "x", "claim_id": None, "observed_at": d(0), "last_referenced": d(0)},
                    {"key": "b", "label": "y", "claim_id": None, "observed_at": d(0), "last_referenced": d(0)}]
    old = {"kind": "conflict", "entity_id": "described", "predicate": "description", "options": raised_today,
           "source_episode": ep(-400)[0], "created_date": d(0)}
    recent = {**old, "source_episode": ep(-2)[0]}
    assert t.parts(old).said == date.fromisoformat(d(-400))
    assert t.freshness(t.parts(old)) < 0.1
    assert t.score(old) < 0.2 * t.score(recent)
    # nothing else to go on: no date, no fade, and the raise date still does not count
    assert t.parts({**old, "source_episode": ""}).said is None


def test_a_claim_on_the_page_is_dated_by_its_conversations_whatever_the_option_stored(bank):
    page(bank, "stored-late", convs=4, said=-10, claims=20, claim_eps={0: ep(-400), 1: ep(-400)})
    t = question_order.tables(bank)
    fm = conflict("stored-late", observed=d(-1))
    assert t.parts(fm).said == date.fromisoformat(d(-400)), "a recent `observed_at` never beats the claim's own day"
    assert t.freshness(t.parts(fm)) < 0.1


def test_a_claim_only_the_option_holds_is_dated_by_the_conversation_it_names(bank):
    """The new side of a conflict is written nowhere else (`_place_claim` returns None on CONFLICT_NUDGE)."""
    page(bank, "new-side", convs=4, said=-10, claims=20, claim_eps={0: ep(-400)})
    t = question_order.tables(bank)
    side = {"key": "b", "label": "y", "claim_id": "clm_not_on_page", "observed_at": d(-1),
            "description": f"Last mentioned {d(-1)} · yesterday · extracted from {ep(-300)[0]}"}
    fm = {"kind": "conflict", "entity_id": "new-side", "predicate": "pays", "options": [
        {"key": "a", "label": "x", "claim_id": "clm_new-side_0"}, side]}
    assert t.parts(fm).said == date.fromisoformat(d(-300))
    # an option's own `source_episode` wins over its description, and only with neither does `observed_at` count
    own = {**side, "source_episode": ep(-200)[0]}
    assert t.parts({**fm, "options": [fm["options"][0], own]}).said == date.fromisoformat(d(-200))
    # with neither, `observed_at` is the claim's `valid_from`: not when it was said, so it only counts with nothing better
    bare = {"key": "b", "label": "y", "claim_id": "clm_not_on_page", "observed_at": d(-250)}
    assert t.parts({**fm, "options": [fm["options"][0], bare]}).said == date.fromisoformat(d(-400))
    assert t.parts({**fm, "options": [bare]}).said == date.fromisoformat(d(-250))


def test_a_memory_export_entry_is_no_mention_only_a_no_later_than(bank):
    """Rail: "a memory export entry ... is no mention". A real date always wins; with none, the entry's own day is an upper
    bound, so a fact known only from an export still fades instead of leading the list for ever."""
    export = ep(-3)[0]
    markdown_parser.write(bank / "episodes" / f"{export}.md", {"id": export, "source": "claude_memory"}, "entry")
    bank_index.invalidate()
    page(bank, "exported", convs=4, said=-10, claims=20,
         claim_eps={0: ep(-400) + [export], 1: ep(-500), 2: [export], 3: [export]})
    t = question_order.tables(bank)
    assert t.untimed(export) and not t.untimed(ep(-400)[0]) and not t.untimed("")
    # the newer id on the claim is the export: the claim was last said 400 days ago
    assert t.parts(conflict("exported", n=2)).said == date.fromisoformat(d(-400))
    # another side's real date beats an export-only side
    mixed = {"kind": "conflict", "entity_id": "exported", "options": [
        {"key": "a", "label": "x", "claim_id": "clm_exported_1"}, {"key": "b", "label": "y", "claim_id": "clm_exported_2"}]}
    assert t.parts(mixed).said == date.fromisoformat(d(-500))
    # only the export on every side: no later than its day
    only = {"kind": "conflict", "entity_id": "exported", "options": [
        {"key": "a", "label": "x", "claim_id": "clm_exported_2"}, {"key": "b", "label": "y", "claim_id": "clm_exported_3"}]}
    assert t.parts(only).said == date.fromisoformat(d(-3))
    claimless = {"kind": "conflict", "entity_id": "exported", "source_episode": export, "options": [
        {"key": "a", "label": "x", "observed_at": d(0)}, {"key": "b", "label": "y", "observed_at": d(0)}]}
    assert t.parts(claimless).said == date.fromisoformat(d(-3))


def test_an_evergreen_page_that_is_not_the_owners_never_fades_and_the_classes_fade_at_their_own_rates(bank):
    for pid, cls in (("p-evergreen", "evergreen"), ("p-durable", "durable"), ("p-active", "active"),
                     ("p-volatile", "volatile")):
        page(bank, pid, convs=4, said=-10, claims=10, claim_eps={0: ep(-120), 1: ep(-120)},
             decay_class=cls, decay_rate={"evergreen": 0.0, "durable": 0.02, "active": 0.05, "volatile": 0.15}[cls])
    t = question_order.tables(bank)
    fresh = {cls: t.freshness(t.parts(conflict(f"p-{cls}", observed=d(-120)))) for cls in
             ("evergreen", "durable", "active", "volatile")}
    assert fresh["evergreen"] == 1.0, "nothing on a non-owner evergreen page fades (a bookmark does not become less true)"
    assert fresh["durable"] > fresh["active"] > fresh["volatile"] > question_order.FADE_FLOOR
    for cls, rate in (("durable", 0.02), ("active", 0.05), ("volatile", 0.15)):
        half = t.parts(conflict(f"p-{cls}", observed=d(-120))).half_life
        assert half == pytest.approx(math.log(2) / rate * 7)
        assert fresh[cls] == pytest.approx(0.5 ** (120 / half))
    assert [round(math.log(2) / r * 7) for r in (0.02, 0.05, 0.15)] == [243, 97, 32], "the documented half-lives"


def test_an_old_fact_on_a_small_page_opened_daily_is_relieved_and_on_a_very_large_one_mostly_is_not(bank):
    page(bank, "small", convs=1, said=-300, claims=12, claim_eps={0: ep(-400), 1: ep(-400)})
    page(bank, "huge", convs=1, said=-300, claims=8000, claim_eps={0: ep(-400), 1: ep(-400)})
    page(bank, "unopened", convs=1, said=-300, claims=12, claim_eps={0: ep(-400), 1: ep(-400)})
    open_pages(bank, "small", 20, "app")
    open_pages(bank, "huge", 20, "app")
    t = question_order.tables(bank)
    fade = 0.5 ** (400 / ACTIVE_HALF_LIFE)
    f = {pid: t.freshness(t.parts(conflict(pid, observed=d(-400)))) for pid in ("small", "huge", "unopened")}
    assert f["unopened"] == pytest.approx(fade)
    assert f["small"] > 0.75, "a page opened every day for 20 days keeps its old facts"
    assert f["huge"] < 0.15 and f["huge"] < f["small"] / 5, "30 of 8,000 claims in front of a reader do not rescue the rest"
    # an empty or absent counter is relief 0, and the order still works
    off = question_order.tables(bank, reads=False)
    assert off.freshness(off.parts(conflict("small", observed=d(-400)))) == pytest.approx(fade)


NON_FADING = {
    "a duplicate pair": {"kind": "merge_suggestion", "entity_id": "age-a", "merge_target_hint": "age-b",
                         "suggested_classification": "person — could refer to the same person as Age B"},
    "who someone is": {"kind": "clarification", "asks": "name", "entity_id": "age-a"},
    "a held-name release": {"kind": "clarification", "entity_id": "held-no-page", "entity_name": "Held Name"},
    "decay": {"kind": "decay", "entity_id": "age-a", "claim_id": "clm_age-a_0"},
    "removal": {"kind": "removal", "entity_id": "age-a"},
    "normalization": {"kind": "normalization", "entity_id": "age-a"},
    "page edit": {"kind": "page_edit", "entity_id": "age-a", "edit": {"edits": [{"old": "a", "new": "b"}]}},
    "a sources review": {"kind": "clarification", "asks": "sources", "entity_id": "age-a",
                         "rows": [{"id": "1", "page": "age-a", "ref": "r"}]},
    "a sensitive hold": {"kind": "sensitive", "entity_id": "age-a"},
}


@pytest.mark.parametrize("name", sorted(NON_FADING))
def test_a_kind_that_is_not_a_fact_someone_said_keeps_its_score_with_age(bank, name):
    """Who someone is does not age (Rodrigo, 2026-11-06); decay asks about age itself; the rest are not facts someone said."""
    page(bank, "age-a", type_="person", convs=4, said=-10, claims=20, claim_eps={0: ep(-900), 1: ep(-900)})
    page(bank, "age-b", type_="person", convs=4, said=-10, claims=20, claim_eps={0: ep(-900)})
    pending_store.save(bank, [pending_store.PendingEntity(
        name="Held Name", type="concept", description="", source_episode="ep_x", confidence=0.5, tags=[],
        history_entries=[], held_claims=[{"id": "h1"}])])
    t = question_order.tables(bank)
    base = NON_FADING[name]
    aged = {**base, "source_episode": ep(-900)[0], "last_referenced": d(-900), "created_date": d(-900), "observed_at": d(-900)}
    young = {**base, "source_episode": ep(0)[0], "last_referenced": d(0), "created_date": d(0), "observed_at": d(0)}
    for fm in (aged, young):
        if "options" in fm:
            fm["options"] = [{**o, "observed_at": fm["observed_at"]} for o in fm["options"]]
    assert t.parts(aged).said is None and t.freshness(t.parts(aged)) == 1.0
    assert t.score(aged) == pytest.approx(t.score(young)) and t.score(aged) > 0


def test_the_fade_has_a_floor_no_date_means_no_fade_and_a_future_date_is_age_zero(bank):
    page(bank, "dated", convs=4, said=-10, claims=20, claim_eps={0: ep(-4000), 1: ep(-4000), 2: ep(30), 3: ["ep_x"]})
    t = question_order.tables(bank)
    ancient = conflict("dated", observed=d(-4000))
    assert t.freshness(t.parts(ancient)) == question_order.FADE_FLOOR == 0.05
    assert t.score(ancient) > 0, "the floor keeps a very old question on the list"
    undated = {"kind": "conflict", "entity_id": "dated", "options": [
        {"key": "a", "label": "x", "claim_id": "clm_dated_3"}, {"key": "b", "label": "y", "claim_id": "clm_dated_9"}]}
    assert t.parts(undated).said is None and t.freshness(t.parts(undated)) == 1.0
    future = conflict("dated", start=2, n=1, observed=d(40))
    assert t.parts(future).said > date.today() and t.freshness(t.parts(future)) == 1.0, "a future date clamps to age 0"
    junk = {"kind": "conflict", "entity_id": "dated", "options": [
        {"key": "a", "label": "x", "observed_at": "last spring"}, {"key": "b", "label": "y", "observed_at": 12}]}
    assert t.freshness(t.parts(junk)) == 1.0


def test_divergence_clarification_and_followup_age_by_their_source_episode(bank):
    page(bank, "said-page", convs=4, said=-10, claims=20)
    t = question_order.tables(bank)
    for kind in ("divergence", "clarification", "followup"):
        old = {"kind": kind, "entity_id": "said-page", "source_episode": ep(-400)[0], "created_date": d(0)}
        new = {"kind": kind, "entity_id": "said-page", "source_episode": ep(-2)[0], "created_date": d(-300)}
        assert t.parts(old).said == date.fromisoformat(d(-400)), kind
        assert t.score(old) < 0.2 * t.score(new), kind
        none = {"kind": kind, "entity_id": "said-page", "created_date": d(-400)}
        assert t.parts(none).said is None and t.freshness(t.parts(none)) == 1.0, kind


def test_said_records_read_the_page_and_its_ledger_memoised_by_stamp_and_built_only_for_conflict_pages(bank):
    page(bank, "ledgered", convs=4, said=-10, claims=3, claim_eps={0: ["ep_2025-01-02_003", "ep_2025-03-04_001"], 1: ["ep_x"]})
    ledger = bank / "entities" / "ledgered.claims.jsonl"
    ledger.write_text('{"id": "clm_old_9", "text": "x", "source_episodes": ["ep_2024-05-06_002"], "evidence": '
                      '[{"episode": "ep_2025-01-01_001"}, {"episode": "doc-1"}]}\n{"id": "broken\n', encoding="utf-8")
    question_order.reset()
    records = question_order.said_records(bank, "ledgered")
    assert records["clm_ledgered_0"][3] == ("ep_2025-01-02_003", "ep_2025-03-04_001")
    assert records["clm_old_9"][3] == ("ep_2024-05-06_002", "ep_2025-01-01_001"), "evidence counts; only a conversation"
    assert "broken" not in records
    assert question_order.said_records(bank, "never-existed") == {} and question_order.said_records(bank, "") == {}
    # memoised by stamp: the same dict comes back until a file moves
    assert question_order.said_records(bank, "ledgered") is question_order.said_records(bank, "ledgered")
    ledger.write_text('{"id": "clm_new", "source_episodes": ["ep_2026-01-01_001"]}\n', encoding="utf-8")
    assert question_order.said_records(bank, "ledgered")["clm_new"][3] == ("ep_2026-01-01_001",)
    # only a page that holds a conflict question is read for dates
    question_order.reset()
    page(bank, "no-conflict", type_="person", convs=4, said=-10, claims=5, claim_eps={0: ep(-400)})
    t = question_order.tables(bank)
    for fm in ({"kind": "removal", "entity_id": "no-conflict"}, {"kind": "decay", "entity_id": "no-conflict"},
               {"kind": "merge_suggestion", "entity_id": "no-conflict", "merge_target_hint": "ledgered"},
               {"kind": "conflict", "asks": "still", "entity_id": "no-conflict", "object_id": "ledgered"}):
        t.score(fm)
    assert question_order._SAID == {}
    t.score(conflict("no-conflict", observed=d(-400)))
    assert list(question_order._SAID) == [str(bank / "entities" / "no-conflict.md")]


def test_the_launch_warm_up_builds_the_tables_and_never_raises(bank, monkeypatch):
    """A hook has 300 ms: the first ask after launch must not read every page's header (measured: ~0.7 s on 8,000 pages,
    ~70 ms once the pages are parsed and only the tables are cold)."""
    page_use.reset()
    question_order.warm(bank)
    assert page_use._CACHE, "page use was built at launch"
    monkeypatch.setattr(question_order, "tables", lambda *a, **k: (_ for _ in ()).throw(OSError("nope")))
    question_order.warm(bank)   # a failure costs the warm-up, nothing else
    from api import main
    import inspect
    assert inspect.getsource(main).count("question_order.warm") == 2, "both lifespans (home and replica) warm it"


# --------------------------------------------------------------------------- one order everywhere (requirement 2)
#
# Each place below once ordered questions by file name or stored priority. In every case the question the formula asks
# first has the LOWEST priority and the HIGHEST file number, so only the score can put it first.


def _two_on_a_bank(bank):
    """`big` (a 5-way conflict, an unread-but-large change) must come before `small` (a plain clarification)."""
    page(bank, "routed", convs=4, said=-10, claims=20)
    small = item(bank, 1, kind="clarification", priority=0.9, entity_id="routed", entity_name="Routed", required_input="choice",
                 question="Small?", options=[{"key": "a", "label": "x"}, {"key": "b", "label": "y"}], created_date=d(0))
    big = item(bank, 2, kind="conflict", priority=0.1, entity_id="routed", entity_name="Routed", predicate="lives-in",
               question="Big?", options=options(5, "routed"), created_date=d(-1))
    return small, big


def _ctx(bank, **kw):
    from api.services import mcp_tools

    return mcp_tools.ToolContext(memory_path=lambda: bank, session_id="s", harness="claude-code", **kw)


def test_the_agents_inbox_list_is_in_the_apps_order_and_a_remote_one_is_computed_without_the_counter(bank, monkeypatch):
    from api.services import mcp_tools

    small, big = _two_on_a_bank(bank)
    for ctx in (_ctx(bank), _ctx(bank, connector_id="conn-1", read_surface="remote")):
        text = mcp_tools.check_nudges(ctx, None, mode="list")
        assert text.index(f"`{big}`") < text.index(f"`{small}`"), "the score, not the file order or the stored priority"
    seen = []
    real = question_order.tables
    monkeypatch.setattr(question_order, "tables", lambda mp, **kw: seen.append(kw.get("reads", True)) or real(mp, **kw))
    mcp_tools.check_nudges(_ctx(bank), None, mode="list")
    mcp_tools.check_nudges(_ctx(bank, connector_id="conn-1"), None, mode="list")
    assert seen == [True, False]


def test_recalls_question_block_is_ordered_only_when_more_pass_than_it_shows(bank, monkeypatch):
    from api.services import inbox_ask_gate, mcp_tools

    monkeypatch.setattr(inbox_ask_gate, "named_in", lambda *a, **k: True)
    monkeypatch.setattr(inbox_ask_gate, "relevant", lambda *a, **k: (True, ""))
    built = []
    real = question_order.tables
    monkeypatch.setattr(question_order, "tables", lambda mp, **kw: built.append(kw.get("reads", True)) or real(mp, **kw))
    small, big = _two_on_a_bank(bank)
    assert len(mcp_tools._relevant_inbox(bank, "anything")) == 2 and built == [], "two questions all show: no tables on the recall path"
    n = mcp_tools.RECALL_INBOX_SHOWN
    for num in range(3, n + 3):   # more than it shows, all lower than `big`
        item(bank, num, kind="clarification", priority=0.9, entity_id="routed", entity_name="Routed", required_input="choice",
             question=f"Filler {num}?", options=[{"key": "a", "label": "x"}], created_date=d(-5))
    blurbs = mcp_tools._relevant_inbox(bank, "anything")
    assert len(blurbs) == n + 2 and built == [True]
    assert "Big?" in blurbs[0], "the highest score comes first, ahead of the file-order first (priority .9) and the fillers"
    mcp_tools._relevant_inbox(bank, "anything", remote=True)
    assert built == [True, False]


def test_the_hooks_one_pointer_is_the_first_in_the_apps_order(bank, monkeypatch):
    from types import SimpleNamespace

    from api.services import hook_recall, inbox_ask_gate

    small, big = _two_on_a_bank(bank)
    monkeypatch.setattr(inbox_ask_gate, "relevant", lambda *a, **k: (True, ""))
    docs = [SimpleNamespace(ref=ref, meta={**dict(markdown_parser.parse(bank / "inbox" / f"{ref}.md").frontmatter)})
            for ref in (small, big)]
    reader = SimpleNamespace(inbox_docs=lambda: docs)
    pages = [hook_recall.PageNote(id="routed", name="Routed", type="concept", summary="")]
    line, ref = hook_recall._open_question(reader, pages, TODAY.isoformat(), memory_path=bank, prompt="routed")
    assert ref == big, "priority .1 and file number 2 still beat priority .9 and file number 1"
    assert hook_recall._open_question(SimpleNamespace(inbox_docs=lambda: docs[:1]), pages, TODAY.isoformat(),
                                      memory_path=bank, prompt="routed")[1] == small, "a lone candidate needs no order"


def test_a_web_lookups_candidates_follow_the_served_order_inside_a_kind(bank, monkeypatch):
    from types import SimpleNamespace

    from api.services import web_settle

    page(bank, "x-a", convs=4, said=-10, claims=20)
    low = item(bank, 1, kind="conflict", priority=0.9, entity_id="x-a", entity_name="X A", predicate="lives-in",
               options=options(2, "x-a"), created_date=d(0))
    high = item(bank, 2, kind="conflict", priority=0.1, entity_id="x-a", entity_name="X A", predicate="lives-in",
                options=options(5, "x-a"), created_date=d(-1))
    clar = item(bank, 3, kind="clarification", priority=0.1, entity_id="x-a", entity_name="X A", required_input="choice",
                question="Q?", options=[{"key": "a", "label": "x"}], created_date=d(-2))
    kinds = {low: "conflict", high: "conflict", clar: "clarification"}
    monkeypatch.setattr(web_settle, "candidate", lambda mp, path, facts, **k: SimpleNamespace(
        kind=kinds[path.stem], scope="public", item_id=path.stem))
    inbox_service.reset_built()
    out = [c.item_id for c in web_settle.candidates(bank, facts=object())]
    assert out[0] == clar, "a lookup's kind order first: it says what a lookup can answer"
    assert out[1:] == [high, low], "inside a kind, the order the inbox serves"


def test_a_source_scope_lookup_follows_the_served_order_too(bank, monkeypatch):
    """Ruling 54a's conflicts join the drain after `candidates` and its cap keeps the first few: file order would drop
    the biggest."""
    from types import SimpleNamespace

    from api.services import predicates, settling_agent, web_lookup, web_settle

    page(bank, "src-a", convs=4, said=-10, claims=20)
    low = item(bank, 1, kind="conflict", priority=0.9, entity_id="src-a", entity_name="Src A", predicate="lives-in",
               options=options(2, "src-a"), created_date=d(0))
    high = item(bank, 2, kind="conflict", priority=0.1, entity_id="src-a", entity_name="Src A", predicate="lives-in",
                options=options(5, "src-a"), created_date=d(-1))
    monkeypatch.setattr(predicates, "cardinality", lambda *a, **k: "single")
    monkeypatch.setattr(settling_agent, "tracked_public", lambda *a, **k: ({"https://example.org": "src-a"}, {}))
    monkeypatch.setattr(web_settle, "candidate", lambda mp, path, facts, **k: SimpleNamespace(
        item_id=path.stem, options=[1, 2]))
    inbox_service.reset_built()
    facts = SimpleNamespace(pages={"src-a": {}}, owner_id="someone-else")
    assert [c.item_id for c in web_lookup.source_items(bank, facts, already=set())] == [high, low]


# ---- Rodrigo's judgment of the real top 10 (2026-11-06)


def _still(num_days, *, obj="topic", **extra):
    return {"kind": "conflict", "asks": "still", "entity_id": OWNER, "object_id": obj, "priority": 0.5,
            "options": [{"key": "a", "label": "x", "claim_id": "clm_gone", "observed_at": d(num_days)},
                        {"key": "neither", "label": "Not anymore"}], **extra}


def test_a_still_question_fades_from_when_it_was_said_and_daily_reads_of_its_topic_relieve_it(bank):
    page(bank, "topic", convs=4, said=-10, claims=10)
    t = question_order.tables(bank)
    old, recent = _still(-400), _still(-3)
    assert t.parts(old).said == date.fromisoformat(d(-400))
    assert t.score(old) / t.score(recent) < 0.1
    # "Not anymore" says nothing, and a question raised today is not a fact said today
    assert t.parts(_still(-400, source_episode=f"ep_{d(0)}_001", created_date=d(0))).said == date.fromisoformat(d(-400))
    # an older item carrying only the generator's own `last_said`
    bare = {"kind": "conflict", "asks": "still", "entity_id": OWNER, "object_id": "topic", "last_said": d(-200),
            "options": [{"key": "neither", "label": "Not anymore"}]}
    assert t.parts(bare).said == date.fromisoformat(d(-200))
    open_pages(bank, "topic", 14)
    read = question_order.tables(bank)
    assert read.score(old) > t.score(old), "a topic still read daily keeps an old still? question up"


def test_merges_and_name_questions_do_not_fade_with_age(bank):
    page(bank, "a", convs=4, said=-400, claims=20, claim_eps={i: ep(-400) for i in range(20)})
    page(bank, "b", convs=4, said=-400, claims=20, claim_eps={i: ep(-400) for i in range(20)})
    t = question_order.tables(bank)
    merge = {"kind": "merge_suggestion", "entity_id": "a", "merge_target_hint": "b", "source_episode": f"ep_{d(-400)}_001"}
    name = {"kind": "clarification", "asks": "name", "entity_id": "a", "source_episode": f"ep_{d(-400)}_001"}
    for fm in (merge, name):
        parts = t.parts(fm)
        assert parts.said is None and t.freshness(parts) == 1.0, fm["kind"]


def test_the_owners_page_size_does_not_dilute_its_facts_but_does_not_rescue_old_ones_either(bank):
    page(bank, OWNER, name="Owner Example", type_="person", convs=40, decay_class="evergreen", decay_rate=0.0,
         claims=4000, claim_eps={0: ep(-3), 1: ep(-3), 2: ep(-400), 3: ep(-400)})
    page(bank, "hub", convs=40, said=-3, claims=4000, claim_eps={i: ep(-3) for i in range(4)})
    t = question_order.tables(bank)
    mine = conflict(OWNER, observed=d(-3))
    assert t.seen(t.parts(mine)) == 2.0, "reach, whatever the page's size"
    hub = conflict("hub", observed=d(-3))
    assert t.seen(t.parts(hub)) == pytest.approx(2 * question_order.visibility(4000)), "any other page still dilutes"
    assert t.score(mine) > 3 * t.score(hub)
    # Reading the owner's page every day still does not exempt every old fact on it.
    open_pages(bank, OWNER, 14)
    read = question_order.tables(bank)
    assert read.freshness(read.parts(conflict(OWNER, start=2, observed=d(-400)))) < 0.2


def _fam(row):
    return row[0]


def _longest_run(rows):
    best = run = 0
    last = object()
    for fam, _n in rows:
        run = run + 1 if fam == last else 1
        last = fam
        best = max(best, run)
    return best


@pytest.mark.parametrize("limit", [1, 2, 3])
def test_spaced_limits_a_run_keeps_the_top_and_each_familys_order(monkeypatch, limit):
    monkeypatch.setattr(question_order, "RUN_LIMIT", limit)
    rows = [("same", i) for i in range(6)] + [("conflict", 6), ("still", 7), ("conflict", 8), ("decay", 9), ("same", 10)]
    out = question_order.spaced(rows, _fam)
    assert out[0] == rows[0], "the top score always leads"
    assert _longest_run(out[:6]) <= limit
    for fam in ("same", "conflict", "still", "decay"):
        mine = [n for f, n in out if f == fam]
        assert mine == sorted(mine), "a family keeps its own score order"
    assert sorted(out) == sorted(rows), "nothing is lost"


@pytest.mark.parametrize("limit", [1, 2, 3])
def test_spaced_holds_the_limit_over_a_whole_list_while_anything_else_is_left(monkeypatch, limit):
    monkeypatch.setattr(question_order, "RUN_LIMIT", limit)
    rows = [("same", i) for i in range(6)] + [("conflict", 6 + i) for i in range(6)] + [("still", 12 + i) for i in range(6)]
    out = question_order.spaced(rows, _fam)
    for i in range(len(out) - limit):
        if len({fam for fam, _n in out[i:i + limit + 1]}) == 1:
            assert {fam for fam, _n in out[i:]} == {out[i][0]}, "a run over the limit only where nothing else is left"


def _on_topic_page(bank):
    page(bank, "orchid", name="Orchid", convs=4, said=-3, claims=20, claim_eps={i: ep(-3) for i in range(20)})


def _asked(bank, *ids):
    from api.services import mcp_tools

    # The gate wants the conversation to share a subject word with the question: its predicate's, here.
    text = mcp_tools.ask_nudges(_ctx(bank), "does orchid live or work under a tag", entity_ids=["orchid"])
    return sorted((i for i in ids if f"`{i}`" in text), key=lambda i: text.index(f"`{i}`"))


def test_ask_mode_scores_a_set_as_the_inbox_does(bank, monkeypatch):
    """A conflict on a set is shown, never asked (p .05 in `load_inbox`): ask mode once scored it as a real conflict."""
    from api.services import predicates

    _on_topic_page(bank)
    real = predicates.cardinality
    monkeypatch.setattr(predicates, "cardinality", lambda mp, pred, *a, **k: "multi" if pred == "tag" else real(mp, pred, *a, **k))
    item(bank, 1, entity_id="orchid", entity_name="Orchid", predicate="tag", question="Orchid: v0 or v1?", options=options(2, "orchid", observed=d(-3)))
    item(bank, 2, entity_id="orchid", entity_name="Orchid", predicate="lives-in", question="Orchid: v2 or v3?", options=options(2, "orchid", start=2, observed=d(-3)))
    assert _asked(bank, "inbox-001", "inbox-002")[0] == "inbox-002"


def test_ask_mode_breaks_a_tie_as_the_inbox_does(bank):
    _on_topic_page(bank)
    for num, created in ((1, d(-9)), (2, d(-5)), (3, d(-1))):
        item(bank, num, entity_id="orchid", entity_name="Orchid", predicate="lives-in", created_date=created,
             question="Orchid: v0 or v1?", options=options(2, "orchid", observed=d(-3)))
    inbox_service.reset_built()
    served = [i.id for i in inbox_service.load_inbox(bank)]
    assert served[0] == "inbox-003", "newest first on a tie"
    # the same family throughout, so `spaced` changes nothing: the first two are the two the inbox shows first
    assert _asked(bank, "inbox-001", "inbox-002", "inbox-003") == served[:2]


def test_ask_mode_spaces_its_two_picks(bank):
    _on_topic_page(bank)
    item(bank, 1, entity_id="orchid", entity_name="Orchid", predicate="lives-in", question="Orchid: v0 or v1?", options=options(2, "orchid", observed=d(-3)))
    item(bank, 2, entity_id="orchid", entity_name="Orchid", predicate="works-at", question="Orchid: v2 or v3?", options=options(2, "orchid", start=2, observed=d(-3)))
    item(bank, 3, kind="clarification", entity_id="orchid", entity_name="Orchid", required_input="freetext",
         predicate="lives-in", question="Which orchid is this?", source_episode=ep(-3)[0])
    t = question_order.tables(bank)
    assert t.score({"kind": "clarification", "entity_id": "orchid", "required_input": "freetext"}) < t.score(
        conflict("orchid", observed=d(-3))), "the conflicts score higher: only the limit brings the other forward"
    asked = _asked(bank, "inbox-001", "inbox-002", "inbox-003")
    assert len(asked) == 2 and "inbox-003" in asked, asked


def test_spaced_with_nothing_else_left_a_family_runs_on():
    rows = [("same", i) for i in range(5)]
    assert question_order.spaced(rows, _fam) == rows
    assert question_order.spaced([], _fam) == []


def test_spaced_never_brings_a_question_that_is_shown_not_asked_forward():
    rows = [("same", 0), ("same", 1), ("same", 2), (None, 3), ("same", 4)]
    assert question_order.spaced(rows, _fam) == rows, "no asked question to break with: the run goes on, the shown one stays"
    rows = [("same", 0), (None, 1), ("same", 2), ("conflict", 3)]
    assert question_order.spaced(rows, _fam) == [("same", 0), (None, 1), ("conflict", 3), ("same", 2)], (
        "a shown question keeps its place and does not reset the run")


def test_a_family_is_the_question_the_person_meets():
    fam = question_order.family
    assert fam({"kind": "merge_suggestion"}) == "same"
    assert fam({"kind": "page_edit", "join": {"op": "merge"}}) == "same"
    assert fam({"kind": "page_edit", "join": {"op": "split"}}) == "page_edit"
    assert fam({"kind": "conflict", "asks": "still"}) == "still"
    assert fam({"kind": "clarification", "asks": "name"}) == "name"
    assert fam({"kind": "conflict"}) == "conflict"
    assert fam({"kind": "conflict"}, informational=True) is None


def _a_wall(bank):
    for n in range(1, 6):
        page(bank, f"pa-{n}", convs=10, said=-3, claims=30)
        page(bank, f"pb-{n}", convs=10, said=-3, claims=30)
        item(bank, n, kind="merge_suggestion", entity_id=f"pa-{n}", merge_target_hint=f"pb-{n}", required_input="merge",
             suggested_confidence=0.9, entity_name=f"Pa {n}")
    page(bank, "small", convs=2, said=-20, claims=4, claim_eps={i: ep(-3) for i in range(4)})
    for n in (6, 7):
        item(bank, n, entity_id="small", entity_name="Small", predicate="lives-in", options=options(2, "small", observed=d(-3)))


def test_every_list_spaces_a_wall_the_same_way(bank):
    """`load_inbox` (Inbox, Home, every page's queue), the catch-up, and `ranked` (the hook, recall, list mode)."""
    from api.services import inbox_catchup

    _a_wall(bank)
    inbox_service.reset_built()
    served = [i.id for i in inbox_service.load_inbox(bank)]
    merges = {f"inbox-{n:03d}" for n in range(1, 6)}
    assert [x in merges for x in served[:6]] == [True, False, True, False, True, True], served
    rows = [(f.stem, dict(f.frontmatter or {})) for f in bank_index.files(bank, "inbox")]
    assert question_order.ranked(bank, rows) == served
    picked, _rest = inbox_catchup.select(bank, limit=6)
    assert [e.ids[0] in merges for e in picked] == [True, False, True, False, True, True]


def test_a_resolved_item_stays_behind_the_open_ones(bank):
    _a_wall(bank)
    item(bank, 8, kind="merge_suggestion", status="resolved", entity_id="pa-1", merge_target_hint="pb-2", required_input="merge")
    inbox_service.reset_built()
    served = inbox_service.load_inbox(bank)
    statuses = [str(i.status) for i in served]
    assert statuses == sorted(statuses, key=lambda s: 0 if s.endswith("pending") else 1)
