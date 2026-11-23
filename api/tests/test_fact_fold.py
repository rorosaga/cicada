"""A fact a page already states in full is not added again (`fact_fold`, G148). Invented names; a scripted judge, no model.

The model proposes and a second reader confirms; the code check (`covers`) is what no answer can talk past, so the tests
that matter here hand the judge answers that are wrong ("yes" to everything) and look at what still happens."""
import asyncio
import json
from datetime import datetime
from pathlib import Path

from api.config import Settings
from api.services import conflict_resolver as cr
from api.services import fact_fold, link_names, markdown_parser, section_provenance

PAIRS = json.loads((Path(__file__).parent / "fixtures" / "fact_fold_pairs.json").read_text())["pairs"]


def _ask(pair) -> fact_fold.Ask:
    lines = [fact_fold.Line(1, pair["keep"], False), fact_fold.Line(2, pair["drop"], True)]
    own = fact_fold._held_words(pair.get("own") or [])
    return fact_fold.Ask("page-example", "Page Example", lines, dict(pair.get("names") or {}), own)


class Scripted:
    """A judge that says yes to everything: the first call (the ask) names line 1 for every other line, the second (the
    check) lets every pair through with nothing missing — the worst a model can do."""

    def __init__(self, *, missing=()):
        self.calls: list[str] = []
        self.missing = list(missing)

    def __call__(self, prompt: str) -> dict:
        self.calls.append(prompt)
        if "LINES:" in prompt:
            n = len([r for r in prompt.split("LINES:")[1].splitlines() if r[:1].isdigit()])
            return {"answers": [{"line": i, "in_full_by": 1} for i in range(2, n + 1)]}
        pairs = prompt.count("DROP:")
        return {"pairs": [{"pair": i, "missing": self.missing, "same": not self.missing} for i in range(1, pairs + 1)]}


def test_the_guard_agrees_with_the_invented_pairs():
    wrong = []
    for pair in PAIRS:
        ask = _ask(pair)
        allowed = fact_fold._allowed(ask, pair["keep"])
        if fact_fold.covers(pair["keep"], pair["drop"], allowed=allowed) != pair["guard"]:
            wrong.append(pair["id"])
    assert wrong == []


def test_a_yes_to_everything_still_loses_no_date_number_name_or_negation():
    """Every pair a person would not let go and a word can tell apart stays; the pairs marked blind need the model."""
    folded, blind_slips = [], []
    for pair in PAIRS:
        ask = _ask(pair)
        found = fact_fold.decide(ask, Scripted())
        if found and not pair["fold"]:
            (blind_slips if pair.get("blind") else folded).append(pair["id"])
        if pair["fold"]:
            assert found == {pair["drop"]: pair["keep"]}, pair["id"]
    assert folded == []                      # nothing the code can see is ever lost
    assert sorted(blind_slips) == ["artist_for_album", "done_for_plan", "other_relation"]   # the model's alone


def test_a_check_that_lists_something_missing_stops_the_fold():
    pair = next(p for p in PAIRS if p["id"] == "reworded")
    assert fact_fold.decide(_ask(pair), Scripted(missing=["the gift guide"])) == {}


def test_an_unreadable_or_failed_answer_folds_nothing():
    pair = next(p for p in PAIRS if p["id"] == "reworded")
    for answer in ({}, {"answers": "yes"}, {"answers": [{"line": 2, "in_full_by": 9}]}, {"answers": [{"line": 2}]}):
        assert fact_fold.decide(_ask(pair), lambda _p, a=answer: a) == {}

    def boom(_prompt):
        raise RuntimeError("engine down")
    assert fact_fold.decide(_ask(pair), boom) == {}


def test_a_proposal_the_guard_refuses_is_never_checked():
    pair = next(p for p in PAIRS if p["id"] == "adds_a_date")
    judge = Scripted()
    assert fact_fold.decide(_ask(pair), judge) == {}
    assert len(judge.calls) == 1             # the ask; no second reader was bothered


def test_no_call_for_a_page_that_gains_no_new_fact():
    existing = ["Likes jazz", "Rolling admissions with no deadline"]
    # equal after normalisation, and one the existing bullet extends word for word: the code folds those itself
    assert fact_fold.build("p", "P", existing, ["likes jazz.", "Rolling admissions"], heal=True) is None
    assert fact_fold.build("p", "P", existing, ["Plays the saxophone"], heal=True) is not None


def test_what_is_shown_is_bounded_and_is_the_most_alike():
    existing = [f"Fact number {i} about topic{i}" for i in range(200)] + ["Favourite artist of [[Alice Example]]"]
    ask = fact_fold.build("p", "P", existing, ["[[Alice Example]]'s favourite artist is Artist X"], heal=True)
    assert len(ask.lines) <= fact_fold.MAX_LINES
    assert "Favourite artist of [[Alice Example]]" in [line.text for line in ask.lines if not line.new]


def test_a_fact_nothing_shares_a_word_with_is_shown_beside_the_newest_bullets():
    existing = ["Likes jazz", "Plays the saxophone", "Moved to Berlin"]
    ask = fact_fold.build("p", "P", existing, ["Le gusta la musica"], heal=True)
    assert {line.text for line in ask.lines if not line.new} >= {"Moved to Berlin", "Plays the saxophone"}


def test_a_pinned_bullet_never_folds_and_a_person_edited_page_changes_no_bullet():
    lines = [fact_fold.Line(1, "Favourite artist of [[Alice Example]]", False),
             fact_fold.Line(2, "[[Alice Example]]'s favourite artist is Artist X", False, held=True),
             fact_fold.Line(3, "Alice Example's favourite artist: Artist X", True)]
    ask = fact_fold.Ask("p", "P", lines)
    judge = lambda p: {"answers": [{"line": 2, "in_full_by": 3}, {"line": 1, "in_full_by": 3}]} if "LINES" in p \
        else {"pairs": [{"pair": 1, "missing": [], "same": True}]}
    assert not fact_fold.proposals({"answers": [{"line": 2, "in_full_by": 3}]}, ask)            # pinned: never dropped
    ask.heal = False
    assert not fact_fold.proposals({"answers": [{"line": 1, "in_full_by": 3}]}, ask)            # an existing bullet stays
    assert fact_fold.proposals({"answers": [{"line": 3, "in_full_by": 1}]}, ask)                # a new fact may still go
    assert judge("LINES") is not None


def test_a_pair_that_says_the_same_both_ways_keeps_the_older_bullet():
    lines = [fact_fold.Line(1, "Likes jazz", False), fact_fold.Line(2, "Enjoys jazz", True)]
    ask = fact_fold.Ask("p", "P", lines)
    pairs = [(lines[0], lines[1]), (lines[1], lines[0])]
    assert fact_fold.folds(pairs, ask) == {"Enjoys jazz": "Likes jazz"}


def test_a_chain_is_followed_to_the_line_that_is_kept_and_the_guard_runs_on_it():
    lines = [fact_fold.Line(1, "Moved to Berlin", False), fact_fold.Line(2, "Moved to Berlin in March", True),
             fact_fold.Line(3, "Moved to Berlin in March 2026", True)]
    ask = fact_fold.Ask("p", "P", lines)
    # 2 is said by 1 (which says less: the guard refuses it on its own) and 1 by 3: 1 folds into 3, and 2, whose holder is
    # gone, follows it to 3 — which says all of 2 — so both go and only the fullest stays
    pairs = [(lines[1], lines[0]), (lines[0], lines[2])]
    found = fact_fold.folds(pairs, ask)
    assert found == {"Moved to Berlin": "Moved to Berlin in March 2026", "Moved to Berlin in March": "Moved to Berlin in March 2026"}
    # a chain whose root says less than the dropped fact stops at the guard
    assert fact_fold.folds([(lines[2], lines[0])], ask) == {}


# ---------------------------------------------------------------- the writer


def _page(tmp_path, name, bullets, **fm):
    entities = tmp_path / "entities"
    entities.mkdir(exist_ok=True)
    body = "## Summary\nA person.\n\n## Key Facts\n" + "\n".join(f"- {b}" for b in bullets) + "\n"
    markdown_parser.write(entities / f"{name}.md", {"name": name.title(), "type": "person", "status": "active",
                                                    "confidence": 0.8, "aliases": [], "source_episodes": ["ep_2026-11-01_001"],
                                                    **fm}, body)


def _existing(tmp_path):
    return [{"id": p.stem, "frontmatter": markdown_parser.parse(p).frontmatter, "body": markdown_parser.parse(p).body}
            for p in sorted((tmp_path / "entities").glob("*.md"))]


def _entity(facts, episode):
    entity = {"name": "Artist Example", "type": "person", "summary": "", "key_facts": list(facts)}
    section_provenance.attach(entity, episode, "the conversation")
    return entity


def _run(tmp_path, change, judge):
    out = asyncio.run(cr.resolve_and_prune([change], _existing(tmp_path), Settings(), decay=False,
                                           now=datetime(2026, 11, 20), fact_judge=judge))
    cr.apply_changes(out, tmp_path)
    return markdown_parser.parse(tmp_path / "entities" / "artist-example.md")


def _facts(parsed):
    return [i.text for i in section_provenance.scan(parsed.body).get("key_facts", [])]


def _episodes(parsed, text):
    item = next(i for i in section_provenance.scan(parsed.body)["key_facts"] if i.text == text)
    return {ev.episode for ev in section_provenance.matched(parsed.frontmatter, parsed.body)["key_facts"][item.key][1]}


def _born(tmp_path, bullets, episode="ep_2026-11-02_001"):
    """A page as Sleep writes one: created from an extraction, its facts carrying their source rows."""
    (tmp_path / "entities").mkdir(exist_ok=True)
    entity = _entity(bullets, episode)
    cr.apply_changes([{"id": "artist-example", "action": "create", "source_episode": episode, "entity": entity}], tmp_path)


def _asked_for(tmp_path, change, drop_text, by_text):
    """A judge that, shown the real lines, says ``drop_text`` is said in full by ``by_text``, and the check agrees."""
    ask = fact_fold.asks([change], {p["id"]: p for p in _existing(tmp_path)})[0][1]
    drop = next(line.n for line in ask.lines if line.text == drop_text)
    keep = next(line.n for line in ask.lines if line.text == by_text)
    return lambda p: ({"answers": [{"line": drop, "in_full_by": keep}]} if "LINES:" in p
                      else {"pairs": [{"pair": 1, "missing": [], "same": True}]})


def test_a_fact_said_again_is_not_added_and_its_conversation_is_still_shown(tmp_path):
    _born(tmp_path, ["Favourite artist of [[Alice Example]]", "Sings in a choir"])
    change = {"id": "artist-example", "action": "update", "source_episode": "ep_2026-11-19_001",
              "entity": _entity(["Is [[Alice Example]]'s favourite artist", "Toured Europe in 2025"], "ep_2026-11-19_001")}
    judge = _asked_for(tmp_path, change, "Is [[Alice Example]]'s favourite artist", "Favourite artist of [[Alice Example]]")
    parsed = _run(tmp_path, change, judge)
    assert _facts(parsed) == ["Favourite artist of [[Alice Example]]", "Sings in a choir", "Toured Europe in 2025"]
    # the page still shows both conversations that said the first fact
    assert _episodes(parsed, "Favourite artist of [[Alice Example]]") == {"ep_2026-11-02_001", "ep_2026-11-19_001"}
    assert _episodes(parsed, "Toured Europe in 2025") == {"ep_2026-11-19_001"}


def test_a_fact_that_adds_a_date_stays(tmp_path):
    _page(tmp_path, "artist-example", ["Moved to Berlin"])
    change = {"id": "artist-example", "action": "update", "source_episode": "ep_2026-11-19_001",
              "entity": _entity(["Moved to Berlin in March 2026"], "ep_2026-11-19_001")}
    parsed = _run(tmp_path, change, Scripted())
    assert any("March 2026" in f for f in _facts(parsed))


def test_an_existing_bullet_a_new_one_says_in_full_is_replaced_and_its_rows_move(tmp_path):
    _born(tmp_path, ["Likes jazz", "Sings in a choir"])
    longer = "Enjoys jazz a lot, and says so often"
    change = {"id": "artist-example", "action": "update", "source_episode": "ep_2026-11-19_001",
              "entity": _entity([longer], "ep_2026-11-19_001")}
    parsed = _run(tmp_path, change, _asked_for(tmp_path, change, "Likes jazz", longer))
    assert _facts(parsed) == ["Sings in a choir", longer]
    assert _episodes(parsed, longer) == {"ep_2026-11-02_001", "ep_2026-11-19_001"}


def test_a_person_edited_page_keeps_every_bullet(tmp_path):
    _page(tmp_path, "artist-example", ["Likes jazz", "Favourite artist of [[Alice Example]]"], human_edited=True)
    longer = "Enjoys jazz a lot, and says so often"
    change = {"id": "artist-example", "action": "update", "source_episode": "ep_2026-11-19_001",
              "entity": _entity([longer], "ep_2026-11-19_001")}
    ask = fact_fold.asks([change], {p["id"]: p for p in _existing(tmp_path)})[0][1]
    assert ask.heal is False
    parsed = _run(tmp_path, change, _asked_for(tmp_path, change, "Likes jazz", longer))
    assert "Likes jazz" in _facts(parsed) and "Favourite artist of [[Alice Example]]" in _facts(parsed)


def test_without_a_judge_the_page_merges_as_it_did(tmp_path):
    _page(tmp_path, "artist-example", ["Likes jazz"])
    change = {"id": "artist-example", "action": "update", "source_episode": "ep_2026-11-19_001",
              "entity": _entity(["Enjoys jazz"], "ep_2026-11-19_001")}
    assert _facts(_run(tmp_path, change, None)) == ["Likes jazz", "Enjoys jazz"]


def test_the_cap_on_pages_a_batch_asks_about():
    existing = {f"p{i}": {"id": f"p{i}", "frontmatter": {"name": f"P{i}"}, "body": "## Key Facts\n- Likes jazz\n"}
                for i in range(fact_fold.MAX_ASKS + 5)}
    changes = [{"id": pid, "action": "update", "entity": {"key_facts": ["Plays the saxophone"]}} for pid in existing]
    assert len(fact_fold.asks(changes, existing)) == fact_fold.MAX_ASKS


def test_the_judge_asks_for_the_pages_other_names():
    pages = [{"id": "alice-example", "frontmatter": {"name": "Alice Example", "aliases": ["Girlfriend"]}, "body": ""}]
    ask = fact_fold.build("p", "P", ["Favourite artist of [[Alice Example]]"], ["Likes [[Alice Example]]'s songs"],
                          names=link_names.Names(pages))
    assert "Alice Example is also called: Girlfriend" in fact_fold.prompt(ask)
