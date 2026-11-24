"""What a save may add to the bank, and how much (G245, ruling 80's plan, Track 2c): `saves_bounded`.

Reading every save must not bloat the bank with what strangers' posts say. Three bounds, each with the counter that says
what was not kept:

* a page keeps at most twelve open facts that rest on saves alone (the newest by the post's own day; an older one is
  closed, never deleted), and the same fact from several authors is one fact with every author's source;
* a name met only in saves keeps at most three held claims and raises no question;
* a person's name met only in saves joins an existing page on an exact name or alias alone ("Sam" in a stranger's post
  never joins the friend "Sam Example").

Facts the person said, and names they said, are never touched. Synthetic people and posts (example.com); no engine, no
network, no bank of the person's.
"""
from __future__ import annotations

import asyncio
import random
from pathlib import Path
from types import SimpleNamespace

import pytest

from api.services import (bank_index, claim_pipeline, entity_resolver as er, evidence, markdown_parser, pending_store,
                          predicates, saves_bounded, sleep_cycle, telemetry)
from api.services.claim_reconciler import reconcile_stage3
from api.services.claims import Claim, Evidence, parse_claims
from api.services.pending_store import PendingEntity
from api.tests.test_entity_resolver_alias import _Judge, _page, per_pair

TODAY = "2026-11-24"
CONVERSATION = "ep_2026-11-01_001"


def _settings(memory: Path) -> SimpleNamespace:
    return SimpleNamespace(memory_path=memory, litellm_model="synthetic-model", litellm_disambiguation_model="",
                           archive_threshold=0.2, decay_nudge_threshold=0.4, sleep_promotion_threshold=2,
                           sleep_resolve_concurrency=1, link_enrich_enabled=False)


@pytest.fixture
def memory(tmp_path, monkeypatch):
    m = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (m / sub).mkdir(parents=True)
    predicates.install_predicate_map(m)
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(m))
    bank_index.invalidate(m)
    markdown_parser.write(m / "episodes" / f"{CONVERSATION}.md",
                          {"id": CONVERSATION, "timestamp": "2026-11-01T09:00:00+00:00", "processed": True,
                           "source": "claude-code", "harness": "claude-code"},
                          "user: Quillnote is what I use for the team notes.\nassistant: Noted.")
    return m


def _save(memory: Path, n: int, *, channel: str | None = None, posted: str | None = None, reason: str = "",
          ) -> str:
    """A saved post with no words of the person's (unless ``reason``), posted on ``posted``."""
    eid = f"ep_2026-11-20_{n:03d}"
    day = posted or f"2026-{1 + (n % 9):02d}-{1 + (n % 27):02d}"
    body = (f"# Post {n}\n\n**Channel:** {channel or f'author-{n}'}\n**URL:** https://example.com/p/{n}\n\n"
            f"## Description\nQuillnote ships feature {n}.\n")
    if reason:
        body += f"\n## Why it was saved\n{reason}\n"
    markdown_parser.write(memory / "episodes" / f"{eid}.md",
                          {"id": eid, "timestamp": "2026-11-20T09:00:00+00:00", "posted": f"{day}T08:00:00+00:00",
                           "processed": True, "source": "url", "origin": "x-bookmarks",
                           "media_entity_id": f"media-p{n}", "url": f"https://example.com/p/{n}"}, body)
    return eid


def _claim(cid: str, eid: str, obj: str, *, author: str, day: str, predicate: str = "uses",
           subject: str = "quillnote", observer: str | None = None, **kw) -> Claim:
    return Claim(id=cid, text=f"{subject} {predicate} {obj}", subject=subject, predicate=predicate, object=obj,
                 observer=observer or f"external:{author}", valid_from=day, source_episodes=[eid],
                 origin="x-bookmarks", evidence=[Evidence(episode=eid, start=0, end=10, kind="page", hash="0" * 12)], **kw)


def _reconcile(memory: Path, incoming: list[Claim], existing: dict[str, list[Claim]]):
    return reconcile_stage3(incoming, existing, _settings(memory), cardinality_fn=lambda _p: False,
                            now_date=TODAY, decay=False)


def _open_from_saves(memory: Path, claims: list[Claim]) -> list[Claim]:
    saves = saves_bounded.for_bank(memory)
    return [c for c in claims if c.valid_to is None and saves_bounded.is_save_only(c, saves)]


# --------------------------------------------------------------------------- a page's facts


def test_fifty_posts_about_one_page_leave_twelve_open_and_the_newest_stay(memory):
    said = Claim(id="clm_said", text="quillnote is what the person uses", subject="quillnote", predicate="relates-to",
                 object="team-notes", observer="agent", source_trust="user_stated", origin="clarification",
                 valid_from="2026-11-01", source_episodes=[CONVERSATION])
    posts = []
    for n in range(50):
        day = f"2025-{1 + n // 28:02d}-{1 + n % 28:02d}"          # 50 distinct days, in order of n
        eid = _save(memory, n, posted=day)
        posts.append(_claim(f"clm_p{n:02d}", eid, f"feature-{n}", author=f"author-{n}", day=day))
    random.Random(7).shuffle(posts)                               # arrival order is never the post's own order
    existing: dict[str, list[Claim]] = {"quillnote": [said]}
    audit_all: list[dict] = []
    for i in range(0, 50, 10):                                    # five nights' batches: the bound holds cumulatively
        existing, _nudges, audit = _reconcile(memory, posts[i:i + 10], existing)
        audit_all += audit
        assert len(_open_from_saves(memory, existing["quillnote"])) <= saves_bounded.MAX_OPEN_CLAIMS
    page = existing["quillnote"]
    kept = _open_from_saves(memory, page)
    assert len(kept) == saves_bounded.MAX_OPEN_CLAIMS == 12
    newest = sorted(range(50), key=lambda n: f"2025-{1 + n // 28:02d}-{1 + n % 28:02d}", reverse=True)[:12]
    assert sorted(c.id for c in kept) == sorted(f"clm_p{n:02d}" for n in newest), "the newest by the post's own day stay"
    # an older one is closed, never deleted; the person's own fact is untouched
    assert len(page) == 51
    assert all(c.valid_to for c in page if c.id.startswith("clm_p") and c not in kept)
    assert next(c for c in page if c.id == "clm_said").valid_to is None
    assert sum(1 for a in audit_all if a["action"] == "save_capped") == 38, "what was set aside is counted"


def test_the_same_fact_from_several_authors_is_one_claim_with_every_source(memory):
    posts = []
    for n, author in enumerate(("ana-example", "bo-example", "cy-example", "di-example", "ed-example")):
        posts.append(_claim(f"clm_s{n}", _save(memory, n, channel=author), "rust", author=author,
                            day=f"2026-0{n + 1}-10"))
    out, _nudges, audit = _reconcile(memory, posts, {"quillnote": []})
    (claim,) = [c for c in out["quillnote"] if c.valid_to is None]
    assert claim.id == "clm_s0" and claim.object == "rust"
    assert claim.source_episodes == [f"ep_2026-11-20_{n:03d}" for n in range(5)], "all five sources, one fact"
    assert {e.episode for e in claim.evidence} == set(claim.source_episodes)
    assert sum(1 for a in audit if a["action"] == "save_folded") == 4
    # a different object is a different fact, and another predicate too
    more = _claim("clm_x", _save(memory, 9), "go", author="author-9", day="2026-05-05")
    out, _n, _a = _reconcile(memory, [more], out)
    assert sorted(c.object for c in out["quillnote"] if c.valid_to is None) == ["go", "rust"]


def test_a_fact_the_person_stated_is_never_counted_closed_or_folded(memory):
    said = _claim("clm_said", CONVERSATION, "rust", author="x", day="2026-11-01", observer="agent",
                  source_trust="user_stated")
    mixed_save = _save(memory, 60, posted="2020-01-01")
    mixed = _claim("clm_mixed", mixed_save, "zig", author="author-60", day="2020-01-01")
    mixed.source_episodes.append(CONVERSATION)     # a conversation of his also says it
    existing = {"quillnote": [said, mixed]}
    posts = [_claim(f"clm_p{n}", _save(memory, n, posted=f"2026-02-{n + 1:02d}"), f"feature-{n}", author=f"author-{n}",
                    day=f"2026-02-{n + 1:02d}") for n in range(14)]
    posts.append(_claim("clm_dup", _save(memory, 61, posted="2026-03-01"), "rust", author="author-61", day="2026-03-01"))
    out, _nudges, audit = _reconcile(memory, posts, existing)
    by_id = {c.id: c for c in out["quillnote"]}
    assert by_id["clm_said"].valid_to is None and by_id["clm_mixed"].valid_to is None, "his words are never closed"
    assert "clm_dup" in by_id, "a save saying what he said is its own claim: nothing of his is folded into"
    assert len(_open_from_saves(memory, out["quillnote"])) == 12
    assert sum(1 for a in audit if a["action"] == "save_capped") == 3   # 15 save-only claims: 14 posts + the duplicate


def test_a_claim_nobody_can_show_is_a_save_is_not_bounded(memory):
    """No readable episode, an agent's observer, or a conversation: none is "resting on saves", so none is closed."""
    saves = saves_bounded.for_bank(memory)
    ghost = _claim("clm_g", "ep_2026-11-20_900", "x", author="a", day="2026-01-01")
    own = _claim("clm_o", CONVERSATION, "x", author="a", day="2026-01-01")
    agent = _claim("clm_a", _save(memory, 1), "x", author="a", day="2026-01-01", observer="agent")
    no_source = Claim(id="clm_n", text="t", subject="quillnote", observer="external:a")
    assert not any(saves_bounded.is_save_only(c, saves) for c in (ghost, own, agent, no_source))
    assert saves_bounded.is_save_only(_claim("clm_s", _save(memory, 2), "x", author="a", day="2026-01-01"), saves)


def test_a_save_he_wrote_a_reason_on_still_bounds_what_its_author_said_but_never_his_own_words(memory):
    eid = _save(memory, 3, reason="for the team notes")
    saves = saves_bounded.for_bank(memory)
    assert saves.is_save(eid) and not saves.of(eid), "a save, but not one with no words of his"
    assert saves_bounded.is_save_only(_claim("clm_r", eid, "x", author="a", day="2026-01-01"), saves)
    assert not saves.all_of([eid]), "a name that one such save carried is the person's, as ever"


def test_the_pipeline_reports_what_it_folded_and_closed(memory):
    markdown_parser.write(memory / "entities" / "quillnote.md",
                          {"name": "Quillnote", "type": "tool", "status": "active", "source_episodes": [CONVERSATION]},
                          "## Summary\nA synthetic note tool.\n")
    rels, extracted = [], []
    for n in range(16):
        day = f"2026-03-{n + 1:02d}"
        eid = _save(memory, n, posted=day)
        text = evidence.source_text(memory, eid)
        quote = f"Quillnote ships feature {n}."
        rel = {"source": "Quillnote", "target": f"Feature {n % 15}", "label": "uses", "source_episode": eid,
               "source_episode_timestamp": f"{day}T08:00:00Z", "observer": f"external:author-{n}",
               "evidence": [evidence.verify(None, eid, quote, text=text).to_dict()]}
        extracted.append({"episode_id": eid, "episode_timestamp": f"{day}T08:00:00Z", "origin": "x-bookmarks",
                          "entities": [], "relationships": [rel]})
    result = claim_pipeline.run_claim_pipeline(extracted, [], memory, _settings(memory), now_date=TODAY,
                                               name_to_id={"quillnote": "quillnote"})
    claims = parse_claims(markdown_parser.parse(memory / "entities" / "quillnote.md").body)
    assert result["saves_folded"] == 1, "feature 0 said by two authors (posts 0 and 15)"
    assert result["saves_closed"] == 3, "15 distinct facts, 12 kept"
    assert len([c for c in claims if c.valid_to is None]) == 12 and len(claims) == 15


def test_what_sleep_drew_from_saves_with_none_of_his_words_is_the_authors_whatever_drew_it(memory):
    """A relation the Stage 2 judge drew from two posts' descriptions (observer `agent`, `reasoning` evidence) is the first
    post's author's; with his reason on the save, or a conversation also citing it, it stays Cicada's own reading."""
    from api.services import entity_relations

    markdown_parser.write(memory / "entities" / "quillnote.md",
                          {"name": "Quillnote", "type": "tool", "status": "active", "source_episodes": [CONVERSATION]},
                          "## Summary\nA synthetic note tool.\n")
    plain, reasoned = _save(memory, 1, channel="author-one"), _save(memory, 2, reason="for the team notes")
    rels = [entity_relations.relationship("made_by", "Quillnote Pro", "Quillnote", a_id="quillnote", b_id="quillnote-pro", episode=plain),
            entity_relations.relationship("version_of", "Quillnote 2", "Quillnote", a_id="quillnote", b_id="quillnote-2", episode=reasoned),
            entity_relations.relationship("part_of", "Quillnote API", "Quillnote", a_id="quillnote", b_id="quillnote-api", episode=CONVERSATION)]
    extracted = [{"episode_id": r["source_episode"], "episode_timestamp": "2026-11-20T08:00:00Z", "origin": "sleep",
                  "entities": [], "relationships": [r]} for r in rels]
    claim_pipeline.run_claim_pipeline(extracted, [], memory, _settings(memory), now_date=TODAY, name_to_id={"quillnote": "quillnote"})
    by_object = {c.object: c for c in parse_claims(markdown_parser.parse(memory / "entities" / "quillnote.md").body)}
    assert by_object["quillnote-pro"].observer == "external:author-one"
    assert by_object["quillnote-2"].observer == "agent"
    assert by_object["quillnote-api"].observer == "agent"
    assert saves_bounded.is_save_only(by_object["quillnote-pro"], saves_bounded.for_bank(memory))


def test_the_run_row_carries_the_save_counts(tmp_path, monkeypatch):
    from api.config import Settings
    from api.services import git_service

    events: list = []

    async def fake_status(_path):
        return ""

    async def fake_commit(_path, _message):
        return "abc1234"

    monkeypatch.setattr(git_service, "porcelain_status", fake_status)
    monkeypatch.setattr(git_service, "commit_changes", fake_commit)
    monkeypatch.setattr(telemetry, "record", events.append)
    for key, value in (("saves_folded", 4), ("saves_closed", 38), ("saves_held_capped", 2), ("saves_names_held", 5)):
        monkeypatch.setattr(sleep_cycle._state, key, value)
    asyncio.run(sleep_cycle._finalize(
        tmp_path, "sleep_1", [], Settings(llm_mode="agent"),
        engine="claude-cli", connection="claude-plan", billing="subscription", authors=["claude-sonnet-5"],
    ))
    (row,) = [e for e in events if e.kind == "sleep_run"]
    assert {k: row.refs[k] for k in ("saves_folded", "saves_closed", "saves_held_capped", "saves_names_held")} == {
        "saves_folded": 4, "saves_closed": 38, "saves_held_capped": 2, "saves_names_held": 5}


# --------------------------------------------------------------------------- a name's held lines


def _line(name: str, source_episode: str, **kw) -> PendingEntity:
    return PendingEntity(name=name, type="person", description="Came up.", source_episode=source_episode,
                         confidence=0.5, tags=[], history_entries=[], **kw)


def _held_claims(subject: str, eid: str, count: int) -> list[Claim]:
    return [_claim(f"clm_h{n}", eid, f"thing-{n}", author="author-1", day="2026-01-01", subject=subject)
            for n in range(count)]


def test_a_name_only_saves_named_keeps_three_held_claims_and_the_rest_is_counted(memory):
    eid = _save(memory, 1)
    pending_store.upsert(memory, _line("Sam", eid))
    out = pending_store.hold(memory, {"sam": _held_claims("sam", eid, 5)})
    assert (out["sam"].held, out["sam"].capped) == (3, 2)
    assert len(pending_store.load(memory)[0].held_claims) == 3
    assert pending_store.saves_refused(memory, {"sam": out["sam"].capped}) == 2, "reported as the saves' own"
    again = pending_store.hold(memory, {"sam": _held_claims("sam", eid, 5)})   # a re-read: held ones merge, none more
    assert (again["sam"].held, again["sam"].capped) == (3, 2)


def test_a_name_the_person_said_keeps_the_usual_fifty(memory):
    save = _save(memory, 1)
    pending_store.upsert(memory, _line("Sam", save, heard_in=[{"episode": CONVERSATION}]))
    out = pending_store.hold(memory, {"sam": _held_claims("sam", save, 5)})
    assert (out["sam"].held, out["sam"].capped) == (5, 0), "one conversation of his makes the name his"
    assert pending_store.saves_refused(memory, {"sam": 0}) == 0
    pending_store.upsert(memory, _line("Bo", CONVERSATION))
    assert pending_store.hold(memory, {"bo": _held_claims("bo", CONVERSATION, 5)})["bo"].held == 5


def test_the_pipeline_counts_held_claims_refused_for_a_save_only_name(memory):
    eid = _save(memory, 1)
    pending_store.upsert(memory, _line("Sam", eid))
    text = evidence.source_text(memory, eid)
    rels = [{"source": "Sam", "target": f"Thing {n}", "label": "uses", "source_episode": eid,
             "source_episode_timestamp": "2026-01-01T08:00:00Z", "observer": "external:author-1",
             "evidence": [evidence.verify(None, eid, "Quillnote ships feature 1.", text=text).to_dict()]}
            for n in range(5)]
    extracted = [{"episode_id": eid, "episode_timestamp": "2026-01-01T08:00:00Z", "origin": "x-bookmarks",
                  "entities": [], "relationships": rels}]
    result = claim_pipeline.run_claim_pipeline(extracted, [], memory, _settings(memory), now_date=TODAY, name_to_id={})
    assert (result["claims_held"], result["claims_hold_capped"], result["saves_held_capped"]) == (3, 2, 2)
    assert len(pending_store.load(memory)[0].held_claims) == 3


# --------------------------------------------------------------------------- a name's reach


def _resolve(memory, monkeypatch, pages, extracted, verdict="same", *, indexer=None):
    judge = _Judge({p["frontmatter"]["name"]: verdict for p in pages})
    monkeypatch.setattr(er, "_llm_judge_same_entity", judge)
    monkeypatch.setattr(er, "_llm_judge_batch", per_pair(judge))
    monkeypatch.setattr(er, "SqliteVecIndexer", (lambda *a, **k: indexer) if indexer is not None else (lambda *a, **k: None))
    out = asyncio.run(er.resolve(extracted, pages, _settings(memory)))
    return out, judge


class _Store:
    """What `SqliteVecIndexer` does with the pending file, without an embedding model."""

    def __init__(self, memory):
        self.memory = memory

    def index_pending_entity(self, line):
        pending_store.upsert(self.memory, line)

    def pending_by_name(self, name):
        return pending_store.held_line(self.memory, name)

    def rebuild_pending_index(self):
        return 0

    def promote_from_pending(self, name):
        return pending_store.take(self.memory, name)[0]


def _mention(eid: str, name: str, etype: str = "person", **extra) -> list[dict]:
    return [{"episode_id": eid, "relationships": [], "entities": [
        {"name": name, "type": etype, "confidence": 0.6, "description": f"{name} came up.", "source_episode": eid,
         "source_episode_timestamp": "2026-11-20T12:00:00Z", **extra}]}]


def _inbox(memory) -> list[Path]:
    return sorted((memory / "inbox").glob("inbox-*.md"))


def test_sam_in_a_strangers_post_stays_held_beside_sam_example(memory, monkeypatch):
    friend = _page("Sam Example", "person", body="## Summary\nA friend.\n")
    eid = _save(memory, 1, channel="stranger-example")
    out, judge = _resolve(memory, monkeypatch, [friend], _mention(eid, "Sam"), indexer=_Store(memory))
    assert judge.pairs == [], "the judge is never asked: a post's first name is nobody's"
    assert out["name_to_id"].get("sam") != "sam-example"
    assert [c for c in out["changes"] if c["id"] == "sam-example"] == [], "no alias, no fact, no source on that page"
    assert out["saves_names_held"] == 1
    assert [line.name for line in pending_store.load(memory)] == ["Sam"]
    assert _inbox(memory) == [], "no 'same person?' and no 'who is this?'"
    assert er._held_alias_questions([], [friend], {}, er.ClarificationManager(memory), memory) == []


def test_the_same_name_in_a_conversation_goes_by_the_usual_rules(memory, monkeypatch):
    """Control: the rule is the saves' alone. Said in a conversation of his, the judge's `same` joins as it always did."""
    friend = _page("Sam Example", "person", body="## Summary\nA friend.\n")
    out, judge = _resolve(memory, monkeypatch, [friend], _mention(CONVERSATION, "Sam"))
    assert judge.pairs, "the judge weighs it"
    assert out["name_to_id"]["sam"] == "sam-example"
    assert out["saves_names_held"] == 0


def test_a_save_with_his_own_reason_makes_the_name_his(memory, monkeypatch):
    friend = _page("Sam Example", "person", body="## Summary\nA friend.\n")
    eid = _save(memory, 1, reason="Sam wrote this and I want to remember it")
    out, judge = _resolve(memory, monkeypatch, [friend], _mention(eid, "Sam"))
    assert judge.pairs and out["name_to_id"]["sam"] == "sam-example"


def test_a_name_an_earlier_conversation_held_stays_the_persons_when_a_post_names_it_again(memory, monkeypatch):
    friend = _page("Sam Example", "person", body="## Summary\nA friend.\n")
    store = _Store(memory)
    pending_store.upsert(memory, _line("Sam", CONVERSATION))
    eid = _save(memory, 1)
    assert er._from_saves_alone(saves_bounded.for_bank(memory), store, "Sam", [eid]) is False
    assert er._from_saves_alone(saves_bounded.for_bank(memory), store, "Nobody Here", [eid]) is True
    assert er._from_saves_alone(saves_bounded.for_bank(memory), store, "Sam", [eid, CONVERSATION]) is False
    out, judge = _resolve(memory, monkeypatch, [friend], _mention(eid, "Sam"), indexer=store)
    assert judge.pairs and out["name_to_id"]["sam"] == "sam-example"


def test_an_exact_full_name_or_alias_from_a_post_joins_with_no_judge(memory, monkeypatch):
    friend = _page("Sam Example", "person", aliases=["sx-handle"], body="## Summary\nA friend.\n")
    other = _page("Sam Sample", "person", body="## Summary\nAnother friend.\n")
    for name in ("Sam Example", "sx-handle"):
        eid = _save(memory, 1, channel="stranger-example")
        out, judge = _resolve(memory, monkeypatch, [friend, other], _mention(eid, name))
        assert judge.pairs == [], name
        assert out["name_to_id"][name.lower()] == "sam-example", name
        assert out["saves_names_held"] == 0


def test_a_name_two_pages_answer_to_is_not_joined_on_the_name_alone(memory, monkeypatch):
    a = _page("Sam Example", "person", aliases=["sx"], body="## Summary\nA friend.\n")
    b = _page("Sam Sample", "person", aliases=["sx"], body="## Summary\nAnother friend.\n")
    out, judge = _resolve(memory, monkeypatch, [a, b], _mention(_save(memory, 1), "sx"), indexer=_Store(memory))
    assert judge.pairs == [] and out["name_to_id"].get("sx") not in ("sam-example", "sam-sample")
    assert _inbox(memory) == []


def test_a_held_line_only_saves_named_asks_no_alias_question_a_conversations_does(memory):
    page = _page("Bea", "person", body="## Summary\nA friend.\n")
    eid = _save(memory, 1)
    pending_store.upsert(memory, _line("Bea Example", eid, aliases=["Bea"]))
    clarifier = er.ClarificationManager(memory)
    assert er._held_alias_questions([], [page], {}, clarifier, memory) == []
    pending_store.upsert(memory, _line("Bea Example", eid, aliases=["Bea"], heard_in=[{"episode": CONVERSATION}]))
    assert len(er._held_alias_questions([], [page], {}, clarifier, memory)) == 1, "his own words: asked, as before"


def test_a_bare_name_from_a_post_is_left_out_of_the_same_name_planning(memory, monkeypatch):
    """Two posts naming "Sam" and a person already on record under the name: today that is a judge call to tell the Sams
    apart. A post's name is nobody the person said anything of, so nothing is compared."""
    friend = _page("Sam", "person", body="## Summary\nA friend.\n")
    asked: list = []

    async def refuse(*_a, **_k):
        asked.append(1)
        raise AssertionError("the same-name judge was asked about a name only saves carried")

    monkeypatch.setattr(er, "_same_name_ask", refuse)
    first, second = _save(memory, 1), _save(memory, 2)
    extracted = _mention(first, "Sam") + _mention(second, "Sam")
    moves, compared, reviews = asyncio.run(er._plan_same_name_people(
        extracted, [friend], {"sam": [friend]}, _settings(memory), refs=er.owner_identity.self_references(
            [friend], extracted, memory, _settings(memory)), owner_page_id=None))
    assert (moves, compared, asked) == ({}, {}, [])


def test_stage_2_logs_the_names_held_count_as_an_integer():
    from api.services import sleep_cycle

    line = sleep_cycle._stage2_summary(2, 1, 3, 5)
    assert line == "Stage 2 complete: 2 new entities, 1 updates, 3 relationships, 5 name(s) met only in saves held"
    assert "held" not in sleep_cycle._stage2_summary(2, 1, 3, 0)
