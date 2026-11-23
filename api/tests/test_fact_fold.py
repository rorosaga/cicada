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
    return fact_fold.ask_from_pair(pair)


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
        if fact_fold.covers(pair["keep"], pair["drop"], allowed=allowed, people=ask.people) != pair["guard"]:
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
            # A translated repeat shares too few words with its keeper (`MIN_SHARED`): kept, a miss and never a loss.
            assert found == ({pair["drop"]: pair["keep"]} if pair["guard"] else {}), pair["id"]
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


# ---------------------------------------------------------------- a page's neighbourhood (review 2026-11-23)

OWNER_NAME = "Alex Example"
PAGE_LINES = [
    "Favourite artist of [[Alex's girlfriend]]",
    "Vinyl options suggested were Blue Hour or Low Tide",
    "Favorite artist of [[Mira Lund]]",
    "Musical artist who is the favorite of [[Mira Lund]].",
    "Alex's girlfriend's favourite artist.",
    "Sam Rivers is [[Alex's girlfriend]]'s favourite artist. Alex planned to buy one of his vinyl records as a gift.",
    "[[Mira Lund]]'s favourite artist is Sam Rivers.",
    "Is [[Girlfriend]]'s favourite artist",
    "A singer who is [[Girlfriend]]'s favourite artist, noted in Alex's gift guide.",
    "Sam Rivers is a musician who is Alex's girlfriend's favourite artist, according to the guide.",
    "Is [[Pip]]'s favorite artist.",
    "Sam Rivers is Alex's partner's favourite artist.",
    "Sam Rivers is a musician who is Alex's partner's favourite artist.",
    "Sam Rivers is a musical artist and is [[Pip]]'s favorite artist, according to Alex's gift notes.",
    "Sam Rivers is Pip's favorite artist.",
    "Sam Rivers is a musical artist and Pip's favorite artist, as noted in Alex's gift list.",
]


def _pg(page_id, name, aliases=(), related=(), body=""):
    return {"id": page_id, "frontmatter": {"name": name, "type": "person", "status": "active", "aliases": list(aliases),
                                           "related": list(related)}, "body": body}


def _bank_pages(**extra):
    return [
        _pg("sam-rivers", "Sam Rivers", related=["mira-lund", "alex-example", *extra.get("related", [])]),
        _pg("mira-lund", "Mira Lund", ["girlfriend", "gf", "partner", "his girlfriend", "Pip"]),
        _pg("alex-example", OWNER_NAME),
        _pg("jo-park", "Jo Park", ["partner", "Jojo"]),
        _pg("lee-ng", "Lee Ng", ["Lee"]),
        *extra.get("more", []),
    ]


def _ask_for(existing, incoming, pages=None, page_id="sam-rivers"):
    names = link_names.Names(pages or _bank_pages())
    ask = fact_fold.build(page_id, "Sam Rivers", existing, incoming, heal=True, names=names, own=[OWNER_NAME],
                          owner=OWNER_NAME)
    assert ask is not None
    return ask


def _line(ask, text):
    return next(line for line in ask.lines if line.text == text)


def test_a_related_pages_other_names_are_one_person_plain_or_linked():
    people = _ask_for(PAGE_LINES[:1], PAGE_LINES[1:]).people
    assert people is not None and set(people.names) == {"mira-lund"}
    for text in ("Is [[Girlfriend]]'s favourite", "Is Pip's favourite", "Alex's partner's favourite", "Alex Example's girlfriend's favourite",
                 "Is [[Alex's girlfriend]]'s favourite", "Is [[Mira Lund]]'s favourite", "Is gf’s favourite"):
        assert people.canon(text)[1] == {"mira-lund"}, text
    assert people.canon("Is Jojo's favourite")[1] == frozenset()          # not a page this page relates to


def test_the_neighbourhood_is_not_the_bank():
    # No relation to Mira: "Pip" and "girlfriend" mean no one here, and the guard treats the lines as different people.
    pages = _bank_pages()
    pages[0]["frontmatter"]["related"] = []
    ask = _ask_for(["Favourite artist of [[Mira Lund]]"], ["Is Pip's favourite artist."], pages)
    assert ask.people is not None and "mira-lund" in ask.people.names          # her own-name link in a line still counts
    assert not fact_fold.covers("Favourite artist of [[Mira Lund]]", "Is Pip's favourite artist.", people=None)
    ask = _ask_for(["Likes jazz"], ["Is Pip's favourite artist."], pages)
    assert ask.people is None
    assert not fact_fold.covers("Likes [[Mira Lund]]", "Is Pip's favourite", people=ask.people)


def test_two_related_pages_sharing_an_alias_make_it_no_ones():
    ask = _ask_for(["Favourite artist of [[Mira Lund]]"], ["Favourite artist of Alex's partner."],
                   _bank_pages(related=["jo-park"]))
    assert ask.people.canon("Alex's partner")[1] == frozenset()        # Mira and Jo are both "partner" here
    assert ask.people.canon("Pip")[1] == {"mira-lund"}                  # her unshared names still work
    assert not fact_fold.covers("Favourite artist of [[Mira Lund]]", "Favourite artist of Alex's partner.",
                                people=ask.people)


def test_the_judge_is_told_the_names_are_one_person():
    ask = _ask_for(PAGE_LINES[:2], PAGE_LINES[2:])
    text = fact_fold.prompt(ask)
    assert "Mira Lund is also called:" in text and "Alex's girlfriend" in text and "Pip" in text


def test_the_guard_reads_each_spelling_of_the_one_person_as_her():
    ask = _ask_for(["Sam Rivers is [[Mira Lund]]'s favourite artist"], [])  if False else None
    keep = "[[Mira Lund]]'s favourite artist is Sam Rivers."
    people = _ask_for([keep], ["Is Pip's favorite artist."]).people
    for drop in ("Is Pip's favorite artist.", "Alex's girlfriend's favourite artist.", "Is [[Girlfriend]]'s favourite artist",
                 "Sam Rivers is Alex's partner's favourite artist.", "Is [[Alex's girlfriend]]'s favourite artist"):
        assert fact_fold.covers(keep, drop, people=people), drop


def test_a_yes_to_everything_still_refuses_another_person_number_date_or_negation():
    keep = "[[Mira Lund]]'s favourite artist is Sam Rivers."
    refused = [
        "Is [[Jo Park]]'s favourite artist.",                    # a different related page
        "Sam Rivers is Jojo's favourite artist.",                # a different person by another name
        "Is [[Lee Ng]]'s favourite artist.",                     # a different page
        "Is Pip's favourite artist, since 2019.",                # a number
        "Is Pip's favourite artist on 3 May.",                   # a date
        "Is not Alex's girlfriend's favourite artist.",          # a negation
        "Was Pip's favourite artist until March.",               # a tense/status and a month
    ]
    pages = _bank_pages(related=["jo-park", "lee-ng"], more=[])
    pages[3]["frontmatter"]["aliases"] = ["Jojo"]                # Jo no longer shares "partner"
    names = link_names.Names(pages)
    ask = fact_fold.build("sam-rivers", "Sam Rivers", [keep], refused, heal=True, names=names, own=[OWNER_NAME],
                          owner=OWNER_NAME)
    assert fact_fold.decide(ask, Scripted()) == {}
    assert fact_fold.decide(ask, Scripted()) == {} and not any(
        fact_fold.covers(keep, d, allowed=fact_fold._allowed(ask, keep), people=ask.people) for d in refused)


def test_the_reported_page_collapses_under_a_judge_that_says_yes_where_the_code_agrees():
    """The guard alone, with a judge that names line 1 for everything, still folds the lines that are the same fact under
    another name for the same person — and none that adds a month, a number, a negation or another person."""
    ask = _ask_for(PAGE_LINES[:1], PAGE_LINES[1:])
    found = fact_fold.decide(ask, Scripted())
    assert found, "the guard refuses every name the page relates to: the neighbourhood is not read"
    assert PAGE_LINES[1] not in found                                    # the vinyl options: other names, not "her"
    for text in ("Alex's girlfriend's favourite artist.", "Is [[Girlfriend]]'s favourite artist",
                 "Is [[Pip]]'s favorite artist.", "Sam Rivers is Alex's partner's favourite artist."):
        assert text in found, text
    for dropped, holder in found.items():
        assert fact_fold._link_ids(dropped, ask.people) <= fact_fold._link_ids(holder, ask.people), dropped


# --- a fold never loses a link


def test_a_dropped_line_that_links_a_page_the_holder_does_not_is_never_lost():
    people = _ask_for(["x"], ["y"]).people
    plain = "Alex's girlfriend's favourite store is Casa Example."
    linked = "Is [[Girlfriend]]'s favourite store"
    lines = [fact_fold.Line(1, plain, False), fact_fold.Line(2, linked, True)]
    ask = fact_fold.Ask("sam-rivers", "Sam Rivers", lines, {}, fact_fold._held_words([OWNER_NAME]), True, people)
    # the linked line is the one dropped; the holder only names her in plain text: no fold, nothing lost
    assert fact_fold.orient([(lines[1], lines[0])], ask) == []
    assert fact_fold.folds([(lines[1], lines[0])], ask) == {}
    assert fact_fold.decide(ask, Scripted()) == {}


def test_the_direction_is_turned_round_when_the_linked_line_can_hold_the_other():
    people = _ask_for(["x"], ["y"]).people
    plain = "Is Alex's girlfriend's favourite artist."
    linked = "Is [[Mira Lund]]'s favourite artist"
    lines = [fact_fold.Line(1, linked, False), fact_fold.Line(2, plain, True)]
    ask = fact_fold.Ask("sam-rivers", "Sam Rivers", lines, {}, fact_fold._held_words([OWNER_NAME]), True, people)
    assert fact_fold.orient([(lines[1], lines[0])], ask) == [(lines[1], lines[0])]    # plain into linked: as proposed
    lines = [fact_fold.Line(1, plain, False), fact_fold.Line(2, linked, True)]         # the holder is the plain one
    ask = fact_fold.Ask("sam-rivers", "Sam Rivers", lines, {}, fact_fold._held_words([OWNER_NAME]), True, people)
    flipped = fact_fold.orient([(lines[1], lines[0])], ask)
    assert flipped == [(lines[0], lines[1])]                  # the old plain bullet goes into the linked one
    assert fact_fold.folds(flipped, ask) == {plain: linked} and ask.paths[plain] == "flipped"
    # a pinned or person-edited bullet is never the one that goes
    lines[0].held = True
    assert fact_fold.orient([(lines[1], lines[0])], ask) == []


def test_a_chain_ends_with_one_line_holding_every_conversation(tmp_path):
    """a said by b, b said by c, within one ask: both go, c holds all three conversations' rows."""
    _born(tmp_path, ["Moved to Berlin"], episode="ep_2026-11-01_001")
    (tmp_path / "entities" / "artist-example.md").touch()
    change = {"id": "artist-example", "action": "update", "source_episode": "ep_2026-11-19_001",
              "entity": _entity(["Moved to Berlin in March", "Moved to Berlin in March 2026"], "ep_2026-11-19_001")}
    ask = fact_fold.asks([change], {p["id"]: p for p in _existing(tmp_path)})[0][1]
    n = {line.text: line.n for line in ask.lines}
    a, b, c = n["Moved to Berlin"], n["Moved to Berlin in March"], n["Moved to Berlin in March 2026"]
    judge = lambda p: ({"answers": [{"line": a, "in_full_by": b}, {"line": b, "in_full_by": c}]} if "LINES:" in p
                       else {"pairs": [{"pair": i, "missing": [], "same": True} for i in (1, 2)]})
    parsed = _run(tmp_path, change, judge)
    assert _facts(parsed) == ["Moved to Berlin in March 2026"]
    assert _episodes(parsed, "Moved to Berlin in March 2026") == {"ep_2026-11-01_001", "ep_2026-11-19_001"}


def test_a_chain_across_writes_still_ends_with_one_line_holding_every_conversation(tmp_path):
    """Write 2 folds a into b (b holds ep1, ep2); write 3 replaces b by the fuller c: c holds all three."""
    _born(tmp_path, ["Moved to Berlin in March"], episode="ep_2026-11-01_001")
    second = {"id": "artist-example", "action": "update", "source_episode": "ep_2026-11-10_001",
              "entity": _entity(["Moved to Berlin"], "ep_2026-11-10_001")}
    parsed = _run(tmp_path, second, _asked_for(tmp_path, second, "Moved to Berlin", "Moved to Berlin in March"))
    assert _facts(parsed) == ["Moved to Berlin in March"]
    third = {"id": "artist-example", "action": "update", "source_episode": "ep_2026-11-19_001",
             "entity": _entity(["Moved to Berlin in March 2026"], "ep_2026-11-19_001")}
    parsed = _run(tmp_path, third, _asked_for(tmp_path, third, "Moved to Berlin in March", "Moved to Berlin in March 2026"))
    assert _facts(parsed) == ["Moved to Berlin in March 2026"]
    assert _episodes(parsed, "Moved to Berlin in March 2026") == {
        "ep_2026-11-01_001", "ep_2026-11-10_001", "ep_2026-11-19_001"}


def test_two_lines_that_share_only_their_names_and_numbers_do_not_fold():
    """Read on a real page (invented words here): a line saying ALL of a set is of one kind is not a count of that kind."""
    keep = "The app recorded 11 saved posts, 19 history posts and 9 subscribed publications from the Example account."
    drop = "All nine of the followed feeds in the app are Example feeds."
    assert not fact_fold.covers(keep, drop)
    # a reworded line shares most of its words and still folds
    assert fact_fold.covers("Listed as head of sales at Example Labs in the conference contacts note.",
                            "Listed in the conference contacts note as head of sales at Example Labs.")
    # a very short line is left to its names and numbers
    assert fact_fold.covers("Enjoys jazz a lot, and says so often", "Likes jazz")
