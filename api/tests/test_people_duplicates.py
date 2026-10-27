"""One person, three People cards (G209, 2026-10-27) — the three mechanisms behind it, on synthetic banks only.

Measured on the owner's bank (real values redacted): one person held three person pages — a page born from a
dictated misspelling of her name that carried her nickname as an alias, a page titled by a nickname, and the main page
— while a fourth page, another person's, listed her name and nickname among its aliases. Covered here:

1. **Resolve weighs a new name's own aliases and its close spellings.** Candidates used to be found by the new name
   only (a page listing it, or a page sharing a word with it). Two spellings of one name share no word and score under
   the direct match's 85, and the new extraction's aliases were never looked up, so the misspelling met no page at all
   and was born silently. Now a page that shares an alias with the new name, or whose name or alias it is a close
   spelling of, goes to the judge; a page that is BOTH a close spelling and a shared alias is never cleared by the judge
   alone — "different" reads as "unsure": the name is held and asked about, never a silent page.
2. **An alias comes from words that name this page, never co-occurrence.** Stage 1 gave one person the names of
   another person in the same conversation, and Stage 5 unions every new alias onto the page for good. Now an alias that
   names another thing extracted from the same conversation, or that is another same-type page's name or alias, is
   dropped before anything is written.
3. **Two person pages holding one exclusive relation to the owner raise one question.** Nothing compared pages by the
   relation they hold. Now, when a page a batch touched holds a partner / mother / father relation another page holds
   too, Sleep asks "Is <A> the same as <B>?" once per pair — never a merge without the person's answer.

Plus the ruling-29 name settle: a word the person only calls someone by in passing is not the name the question asks.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from api.services import entity_resolver as er
from api.services import inbox_tend, markdown_parser, merge_rejections, role_people
from api.services.claims import Claim, write_claims


# ---------- 1. close spellings and shared aliases ----------

@pytest.mark.parametrize("a, b, expected", [
    ("Talvik", "Talwyk", True),      # two letters heard differently, six letters each
    ("Talvik", "Talvic", True),
    ("Talvik", "Tálvik", False),     # an accent is the same spelling: the direct match's, not a lead
    ("Mara", "Mora", True),          # one edit on a short name
    ("Mara", "Myro", False),         # two edits on a short name
    ("Talvik", "Telwyx", False),     # three edits
    ("Marta", "Berta", False),       # another first letter
    ("Bob", "Rob", False),           # too short to tell
    ("Delphina", "Delphine", False), # over the direct match's 85: the same name, not a lead
    ("Corvin Hale", "Korvin Hale", False),
])
def test_close_spelling(a, b, expected):
    assert er.close_spelling(a, b) is expected


def _page(name, etype="person", aliases=(), status="active", eid=None):
    fm = {"name": name, "type": etype, "confidence": 0.8, "status": status,
          **({"aliases": list(aliases)} if aliases else {})}
    return {"id": eid or name.lower().replace(" ", "-"), "frontmatter": fm,
            "body": f"## Summary\nA synthetic page about {name}."}


def _settings(bank, concurrency=1):
    return SimpleNamespace(memory_path=bank, litellm_model="synthetic-model", litellm_disambiguation_model="",
                           sleep_promotion_threshold=2, sleep_resolve_concurrency=concurrency)


def _mention(name, n, aliases=(), etype="person", others=()):
    ep = f"ep_2026-10-0{n}_001"

    def entity(nm, al):
        return {"name": nm, "type": etype, "confidence": 0.7, "summary": f"{nm} in {ep}.", "aliases": list(al),
                "source_episode": ep, "source_episode_timestamp": f"2026-10-0{n}T12:00:00Z"}
    return {"episode_id": ep, "relationships": [],
            "entities": [entity(name, aliases), *(entity(nm, al) for nm, al in others)]}


class _Judge:
    """A verdict per existing name (default for the rest); records every call."""

    def __init__(self, default="different", **by_name):
        self.default, self.by_name, self.calls = default, by_name, []

    async def __call__(self, new_name, new_type, new_description, existing_name, existing_type, existing_body,
                       settings, **extra):
        self.calls.append({"new_name": new_name, "existing_name": existing_name, **extra})
        return self.by_name.get(existing_name, self.default)


@pytest.fixture
def bank(tmp_path, monkeypatch):
    root = tmp_path / "synthetic-bank"
    for name in ("entities", "episodes", "inbox"):
        (root / name).mkdir(parents=True)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(root))
    monkeypatch.setattr(er, "SqliteVecIndexer", lambda *a, **k: None)
    return root


def _resolve(bank, monkeypatch, pages, extracted, judge, concurrency=1):
    async def batch(new_name, new_type, new_description, entries, settings, *, new_connections=""):
        return [await judge(new_name, new_type, new_description, e["name"], e["type"], e["body"], settings,
                            note=e.get("note", "")) for e in entries]
    monkeypatch.setattr(er, "_llm_judge_same_entity", judge)
    monkeypatch.setattr(er, "_llm_judge_batch", batch)
    return asyncio.run(er.resolve(extracted, pages, _settings(bank, concurrency)))


def _questions(bank):
    out = []
    for path in sorted((bank / "inbox").glob("inbox-*.md")):
        fm = markdown_parser.parse(path).frontmatter
        out.append((fm.get("kind"), fm.get("entity_id"), fm.get("merge_target_hint")))
    return out


def _creates(result):
    return sorted(c["id"] for c in result["changes"] if c["action"] == "create")


def _three_holders():
    """An alias three pages hold: the person's page, another person's page that wrongly lists it, an archived page."""
    return [_page("Talvik", aliases=["Tal"]), _page("Orsa", aliases=["Tal", "Talvik"]),
            _page("Tal", status="archived")]


@pytest.mark.parametrize("concurrency", [1, 3])
@pytest.mark.parametrize("spelling", ["Talwyk", "Talvic", "Talvyk"])
def test_a_close_spelling_sharing_an_alias_is_never_a_silent_page(bank, monkeypatch, spelling, concurrency):
    judge = _Judge("different")
    extracted = [_mention(spelling, 1, aliases=["Tal"]), _mention(spelling, 2, aliases=["Tal"])]
    result = _resolve(bank, monkeypatch, _three_holders(), extracted, judge, concurrency)
    assert "talvik" in {c["existing_name"].lower() for c in judge.calls}
    assert _creates(result) == []                       # held, not born
    assert ("merge_suggestion", spelling.lower(), "talvik") in _questions(bank)


def test_the_judge_is_told_why_the_page_was_brought(bank, monkeypatch):
    judge = _Judge("different")
    _resolve(bank, monkeypatch, _three_holders(), [_mention("Talwyk", 1, aliases=["Tal"]),
                                                   _mention("Talwyk", 2, aliases=["Tal"])], judge)
    note = next(c["note"] for c in judge.calls if c["existing_name"] == "Talvik")
    assert '"Tal"' in note and 'close spelling of "Talvik"' in note


def test_a_same_verdict_joins_the_close_spelling_to_its_page(bank, monkeypatch):
    result = _resolve(bank, monkeypatch, _three_holders(),
                      [_mention("Talwyk", 1, aliases=["Tal"]), _mention("Talwyk", 2, aliases=["Tal"])],
                      _Judge("different", Talvik="same"))
    assert _creates(result) == []
    assert result["name_to_id"]["talwyk"] == "talvik"


def test_a_shared_alias_alone_is_the_judges_call_and_the_alias_stays_off_the_new_page(bank, monkeypatch):
    """No close spelling: a "different" verdict stands, and the shared alias is another page's, so it is not written."""
    result = _resolve(bank, monkeypatch, _three_holders(),
                      [_mention("Quenby", 1, aliases=["Tal"]), _mention("Quenby", 2, aliases=["Tal"])],
                      _Judge("different"))
    assert _creates(result) == ["quenby"]
    page = next(c for c in result["changes"] if c["id"] == "quenby")
    assert "Tal" not in (page["entity"].get("aliases") or [])


def test_a_close_spelling_alone_is_brought_and_the_judge_decides(bank, monkeypatch):
    judge = _Judge("different")
    result = _resolve(bank, monkeypatch, [_page("Talvik")],
                      [_mention("Talwyk", 1), _mention("Talwyk", 2)], judge)
    assert [c["existing_name"] for c in judge.calls] == ["Talvik"]
    assert _creates(result) == ["talwyk"]


def test_a_lead_works_for_other_types_too(bank, monkeypatch):
    judge = _Judge("unsure")
    result = _resolve(bank, monkeypatch, [_page("Grovana", etype="company", aliases=["GRV"])],
                      [_mention("Grovanna Labs", 1, etype="company", aliases=["GRV"]),
                       _mention("Grovanna Labs", 2, etype="company", aliases=["GRV"])], judge)
    assert [c["existing_name"] for c in judge.calls] == ["Grovana"]
    assert _creates(result) == []


def test_two_person_names_one_letter_apart_go_to_the_judge_not_a_direct_join(bank, monkeypatch):
    """`fuzz.ratio > 85` joined them with no judge: a merge on a name's resemblance."""
    judge = _Judge("different")
    result = _resolve(bank, monkeypatch, [_page("Loreena")], [_mention("Lorena", 1), _mention("Lorena", 2)], judge)
    assert [c["existing_name"] for c in judge.calls] == ["Loreena"]
    assert _creates(result) == ["lorena"]


@pytest.mark.parametrize("name, etype", [("Lóreena", "person"), ("Acme Lab", "company")])
def test_one_spelling_or_another_type_still_joins_directly(bank, monkeypatch, name, etype):
    page = _page("Loreena") if etype == "person" else _page("Acme Labs", etype="company")
    judge = _Judge("different")
    result = _resolve(bank, monkeypatch, [page], [_mention(name, 1, etype=etype)], judge)
    assert judge.calls == [] and _creates(result) == [] and [c["id"] for c in result["changes"]] == [page["id"]]


@pytest.mark.parametrize("pronoun", ["she", "her", "ella"])
def test_a_pronoun_is_no_alias_and_ties_no_pages(bank, monkeypatch, pronoun):
    from api.services import alias_policy

    assert alias_policy.is_reference(pronoun) and not alias_policy.is_reference(pronoun.capitalize() + "na")
    judge = _Judge("different")
    pages = [_page("Orsa", aliases=[pronoun]), _page("Pella Ray", aliases=[pronoun])]
    result = _resolve(bank, monkeypatch, pages, [_mention("Quenby", 1, aliases=[pronoun]),
                                                 _mention("Quenby", 2, aliases=[pronoun])], judge)
    assert judge.calls == [] and _creates(result) == ["quenby"]


def test_a_pair_the_person_said_were_different_is_not_brought_by_a_lead(bank, monkeypatch):
    merge_rejections.add_rejected(bank, "talwyk", "talvik")
    judge = _Judge("same")
    result = _resolve(bank, monkeypatch, [_page("Talvik")], [_mention("Talwyk", 1), _mention("Talwyk", 2)], judge)
    assert judge.calls == []
    assert _creates(result) == ["talwyk"]


# ---------- 2. an alias is a name this page goes by, never co-occurrence ----------

def test_an_alias_naming_another_person_in_the_same_conversation_is_dropped(bank, monkeypatch):
    extracted = [_mention("Mira Quell", 1, aliases=["Dax Venn", "Dax", "Mimi"],
                          others=[("Dax Venn", ["Dax"])])]
    result = _resolve(bank, monkeypatch, [_page("Mira Quell")], extracted, _Judge())
    mira = next(c for c in result["changes"] if c["id"] == "mira-quell")
    assert mira["entity"]["aliases"] == ["Dax", "Mimi"]   # "Dax" names nothing else extracted here
    dax = next(e for e in extracted[0]["entities"] if e["name"] == "Dax Venn")
    assert dax["aliases"] == ["Dax"]


@pytest.mark.parametrize("alias, kept", [
    ("Ostro Lane", False),   # another person page's name
    ("Pip", False),          # another person page's alias
    ("Ostro", True),         # a company's name: another type, not the same claim on a person
    ("Mimi", True),          # names no other page
])
def test_an_alias_another_page_already_answers_to_is_not_written(bank, monkeypatch, alias, kept):
    pages = [_page("Mira Quell"), _page("Ostro Lane"), _page("Pella Ray", aliases=["Pip"]),
             _page("Ostro", etype="company")]
    result = _resolve(bank, monkeypatch, pages, [_mention("Mira Quell", 1, aliases=[alias])], _Judge())
    mira = next(c for c in result["changes"] if c["id"] == "mira-quell")
    assert (alias in (mira["entity"].get("aliases") or [])) is kept


def _pair(n, full_aliases, nick_aliases):
    return _mention("Elspeth Moorcroft", n, aliases=full_aliases, others=[("Ellie", nick_aliases)])


@pytest.mark.parametrize("concurrency", [1, 3])
def test_two_entries_that_list_each_other_keep_the_alias_and_meet_the_judge(bank, monkeypatch, concurrency):
    """The extractor says "Elspeth Moorcroft" ↔ "Ellie" both ways: one thing by its own word, never dropped."""
    judge = _Judge("same")
    extracted = [_pair(1, ["Ellie"], ["Elspeth Moorcroft"]), _pair(2, ["Ellie"], ["Elspeth Moorcroft"])]
    result = _resolve(bank, monkeypatch, [], extracted, judge, concurrency)
    assert [(c["new_name"], c["existing_name"]) for c in judge.calls] == [("Ellie", "Elspeth Moorcroft")]
    assert "named together in one conversation" in judge.calls[0]["note"]
    assert _creates(result) == ["elspeth-moorcroft"]
    assert "Ellie" in next(c for c in result["changes"] if c["id"] == "elspeth-moorcroft")["entity"]["aliases"]


def test_a_one_way_alias_is_dropped_but_the_pair_still_meets_the_judge(bank, monkeypatch):
    judge = _Judge("unsure")
    extracted = [_pair(1, ["Ellie"], []), _pair(2, ["Ellie"], [])]
    result = _resolve(bank, monkeypatch, [], extracted, judge)
    assert [(c["new_name"], c["existing_name"]) for c in judge.calls] == [("Ellie", "Elspeth Moorcroft")]
    assert "named together in one conversation" in judge.calls[0]["note"]
    assert _creates(result) == ["elspeth-moorcroft"]          # "Ellie" held and asked, never an unjudged page
    assert ("merge_suggestion", "ellie", "elspeth-moorcroft") in _questions(bank)
    page = next(c for c in result["changes"] if c["id"] == "elspeth-moorcroft")
    assert "Ellie" not in (page["entity"].get("aliases") or [])


def test_the_pair_meets_the_judge_when_one_side_already_has_a_page(bank, monkeypatch):
    judge = _Judge("different")
    _resolve(bank, monkeypatch, [_page("Ellie")], [_pair(1, ["Ellie"], [])], judge)
    assert [(c["new_name"], c["existing_name"]) for c in judge.calls] == [("Elspeth Moorcroft", "Ellie")]


def test_an_alias_a_page_born_in_the_same_batch_answers_to_is_not_written_elsewhere(bank, monkeypatch):
    """Two conversations in one batch: one introduces Dax Venn ("Dax"), another wrongly gives "Dax" to Mira."""
    extracted = [_mention("Dax Venn", 1, aliases=["Dax"]), _mention("Dax Venn", 2, aliases=["Dax"]),
                 _mention("Mira Quell", 3, aliases=["Dax"])]
    result = _resolve(bank, monkeypatch, [_page("Mira Quell")], extracted, _Judge())
    assert _creates(result) == ["dax-venn"]
    assert "Dax" in next(c for c in result["changes"] if c["id"] == "dax-venn")["entity"]["aliases"]
    assert "Dax" not in (next(c for c in result["changes"] if c["id"] == "mira-quell")["entity"].get("aliases") or [])


def test_a_page_keeps_an_alias_it_already_holds(bank, monkeypatch):
    pages = [_page("Pella Ray", aliases=["Pip"]), _page("Orsa", aliases=["Pip"])]
    result = _resolve(bank, monkeypatch, pages, [_mention("Pella Ray", 1, aliases=["Pip"])], _Judge())
    pella = next(c for c in result["changes"] if c["id"] == "pella-ray")
    assert pella["entity"]["aliases"] == ["Pip"]


def test_a_handle_the_record_paired_is_still_kept(bank, monkeypatch):
    """G209's "Full Name (handle)" split adds the handle on purpose, after the co-occurrence rule."""
    extracted = [_mention("Mira Quell (mquell)", 1, others=[("mquell", [])])]
    result = _resolve(bank, monkeypatch, [_page("Mira Quell")], extracted, _Judge())
    mira = next(c for c in result["changes"] if c["id"] == "mira-quell")
    assert "mquell" in mira["entity"]["aliases"]


# ---------- 3. one exclusive relation, two pages ----------

OWNER = "alpha-owner"


def _claim(cid, subject, predicate, obj, **extra):
    return Claim(id=cid, text=f"{subject} {predicate} {obj}", subject=subject, predicate=predicate, object=obj,
                 valid_from="2026-01-01", **extra)


def _write(memory: Path, eid: str, fm: dict, claims=()):
    body = write_claims("## Summary\nSynthetic.", list(claims)) if claims else "## Summary\nSynthetic."
    markdown_parser.write(memory / "entities" / f"{eid}.md",
                          {"type": "person", "status": "active", "confidence": 0.8, **fm}, body)


@pytest.fixture
def family(tmp_path):
    memory = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (memory / sub).mkdir(parents=True)
    _write(memory, OWNER, {"name": "Alpha Owner", "owner": True},
           [_claim("c0", OWNER, "has-wife", "ivy-sample")])
    _write(memory, "kesa", {"name": "Kesa"}, [_claim("c1", "kesa", "girlfriend-of", OWNER)])
    _write(memory, "nim-(unnamed)", {"name": "Nim (unnamed)"}, [_claim("c2", "nim-(unnamed)", "partner-of", OWNER)])
    _write(memory, "partner", {"name": "Partner", "unnamed": True, "owner_roles": ["partner"]})
    _write(memory, "ivy-sample", {"name": "Ivy Sample"})
    _write(memory, "ruth-sample", {"name": "Ruth Sample"}, [_claim("c3", "ruth-sample", "mother-of", OWNER)])
    _write(memory, "mum", {"name": "Mum", "unnamed": True, "owner_roles": ["mum"]})
    _write(memory, "fenn-sample", {"name": "Fenn Sample"}, [_claim("c4", "fenn-sample", "father-of", OWNER)])
    # not exclusive holders: a past relation, a closed claim, a plural relation, an archived page, another relation
    _write(memory, "bram-sample", {"name": "Bram Sample"}, [_claim("c5", "bram-sample", "ex-girlfriend-of", OWNER)])
    _write(memory, "cole-sample", {"name": "Cole Sample"},
           [_claim("c6", "cole-sample", "boyfriend-of", OWNER, valid_to="2025-01-01")])
    _write(memory, "dara-sample", {"name": "Dara Sample"}, [_claim("c7", "dara-sample", "friend-of", OWNER)])
    _write(memory, "old-flame", {"name": "Old Flame", "status": "archived"},
           [_claim("c8", "old-flame", "girlfriend-of", OWNER)])
    _write(memory, "gil-sample", {"name": "Gil Sample"}, [_claim("c9", "gil-sample", "father-in-law-of", OWNER)])
    return memory


def test_the_holders_of_each_exclusive_relation(family):
    assert role_people.exclusive_holders(family) == {
        "partner": ["ivy-sample", "kesa", "nim-(unnamed)", "partner"],
        "mother": ["mum", "ruth-sample"],
    }


def _asked(memory):
    out = set()
    for path in sorted((memory / "inbox").glob("inbox-*.md")):
        fm = markdown_parser.parse(path).frontmatter
        out.add((fm["kind"], fm["entity_id"], fm["merge_target_hint"], fm.get(role_people.FOLD_PAGE_KEY)))
    return out


def test_a_touched_holder_raises_one_question_per_other_holder(family):
    asked = role_people.ask_exclusive(family, [{"id": "kesa", "action": "update"}])
    assert len(asked) == 3
    assert _asked(family) == {("merge_suggestion", "kesa", other, True)
                              for other in ("ivy-sample", "nim-(unnamed)", "partner")}
    body = markdown_parser.parse(family / asked[0]).body
    assert "your partner" in body and "Alpha Owner" not in body


def test_the_next_batch_asks_nothing_new_and_never_merges(family):
    before = {p.name: p.read_text() for p in (family / "entities").glob("*.md")}
    role_people.ask_exclusive(family, [{"id": "kesa", "action": "update"}])
    assert role_people.ask_exclusive(family, [{"id": "kesa", "action": "update"}]) == []
    assert {p.name: p.read_text() for p in (family / "entities").glob("*.md")} == before


def test_each_pair_is_asked_once_whichever_side_is_touched(family):
    role_people.ask_exclusive(family, [{"id": "kesa", "action": "update"}])
    again = role_people.ask_exclusive(family, [{"id": "nim-(unnamed)", "action": "update"}])
    pairs = {frozenset((e, t)) for _k, e, t, _f in _asked(family)}
    assert frozenset(("kesa", "nim-(unnamed)")) in pairs
    assert len(pairs) == len(_asked(family))          # no pair twice
    assert len(again) == 2                            # nim with ivy and with the placeholder


def test_a_pair_the_person_said_are_different_is_never_asked(family):
    merge_rejections.add_rejected(family, "ruth-sample", "mum")
    assert role_people.ask_exclusive(family, [{"id": "ruth-sample", "action": "update"}]) == []


def test_an_untouched_relation_asks_nothing(family):
    assert role_people.ask_exclusive(family, [{"id": "fenn-sample", "action": "update"}]) == []
    assert role_people.ask_exclusive(family, [{"id": "dara-sample", "action": "update"}]) == []


# ---------- the name settle: a nickname said in passing is not the name ----------

@pytest.mark.parametrize("answer, quote, expected", [
    ("Kesa", "Please forward the itinerary to Kesa tonight", True),
    ("bun", "Please forward the itinerary to bun tonight", False),       # a word they call her by, not her name
    ("kesa", "send it to kesa tonight", True),                         # someone who types everything lowercase
    ("Jose", "Ask José about it", True),                               # accents aside
    ("Ana Lima", "Her name is Ana Lima", True),
])
def test_a_name_settle_needs_the_answer_written_as_a_name(answer, quote, expected):
    assert inbox_tend.written_as_name(answer, quote) is expected
    fm = {"kind": "clarification", "asks": "name"}
    assert inbox_tend.answer_supported(Path("."), fm, {"action": "answer", "answer": answer}, quote) is expected
