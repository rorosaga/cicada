"""A link in new text is written under the page's own name (`link_names`); the article writer is told which spellings are
one page. Invented names only; no model call."""
import asyncio
from datetime import datetime

from api.config import Settings
from api.services import conflict_resolver as cr
from api.services import entity_article, link_names, markdown_parser, section_provenance


def _page(page_id, name, aliases=(), status="active", type="person"):
    return {"id": page_id, "frontmatter": {"name": name, "type": type, "status": status, "aliases": list(aliases)},
            "body": ""}


PAGES = [
    _page("alice-example", "Alice Example", ["Girlfriend", "Ally", "<owner>'s girlfriend"]),
    _page("bob-example", "Bob Example", ["Bob"]),
    _page("bob-other", "Bob Other", ["Bob"]),                      # "Bob" is two people (G227)
    _page("carol-example", "Carol Example", []),
    _page("old-example", "Old Example", ["Girlfriend"], status="dropped"),   # a dropped page answers to nothing
    _page("alpha-project", "Alpha Project", [], type="project"),
]
NAMES = link_names.Names(PAGES)


def test_an_alias_link_is_written_under_the_pages_name():
    text, done = link_names.rewrite("Favourite artist of [[Girlfriend]]", NAMES)
    assert text == "Favourite artist of [[Alice Example]]"
    assert done == [("Girlfriend", "Alice Example")]
    assert link_names.rewrite("[[<owner>'s girlfriend]]'s favourite", NAMES)[0] == "[[Alice Example]]'s favourite"


def test_every_spelling_of_one_page_becomes_one_string():
    spellings = ["[[Girlfriend]]", "[[Ally]]", "[[girlfriend]]", "[[Alice Example]]", "[[alice-example]]"]
    assert {link_names.rewrite(f"Favourite artist of {s}", NAMES)[0] for s in spellings} == {
        "Favourite artist of [[Alice Example]]"}


def test_a_name_two_pages_share_stays_as_written():
    assert link_names.rewrite("Met [[Bob]] today", NAMES) == ("Met [[Bob]] today", [])


def test_an_unknown_or_dropped_name_stays_as_written():
    for text in ("[[Nobody Here]]", "[[Girlfriend Of Someone Else]]"):
        assert link_names.rewrite(text, NAMES)[0] == text
    names = link_names.Names([_page("old-example", "Old Example", ["Girlfriend"], status="dropped")])
    assert link_names.rewrite("[[Girlfriend]]", names)[0] == "[[Girlfriend]]"


def test_a_pipe_keeps_its_display_text_and_only_its_target_moves():
    assert link_names.rewrite("[[Girlfriend|she]] left", NAMES)[0] == "[[Alice Example|she]] left"


def test_a_name_that_does_not_round_trip_is_never_written():
    # Two pages share the title, so a link to it means neither (`id_utils.link_targets`): the alias is not rewritten to it.
    pages = [_page("dana-1", "Dana Example", ["D"]), _page("dana-2", "Dana Example", [])]
    assert link_names.rewrite("[[D]]", link_names.Names(pages))[0] == "[[D]]"
    # A page whose name has link syntax in it cannot be written in a link.
    pages = [_page("odd", "Odd | Name", ["Odd"])]
    assert link_names.rewrite("[[Odd]]", link_names.Names(pages))[0] == "[[Odd]]"


def test_plain_text_is_never_touched():
    text = "Favourite artist of Girlfriend and Ally, the partner's pick"
    assert link_names.rewrite(text, NAMES) == (text, [])


def test_an_extraction_keeps_its_source_rows_under_the_new_text():
    entity = {
        "summary": "Loves [[Girlfriend]].",
        "key_facts": ["Favourite artist of [[Girlfriend]]", "Plain fact"],
        "history_entries": [{"date": "2026-11-19", "event": "Gift idea for [[Ally]]"}],
        "open_questions": ["Does [[Girlfriend]] own the record?"],
        section_provenance.INPUTS: [
            {"field": "key_facts", "text": "Favourite artist of [[Girlfriend]]", "evidence": [{"episode": "ep1"}]},
            {"field": "summary", "text": "Loves [[Girlfriend]].", "evidence": [{"episode": "ep1"}]},
        ],
    }
    assert link_names.rewrite_entity(entity, NAMES) == 4
    assert entity["key_facts"] == ["Favourite artist of [[Alice Example]]", "Plain fact"]
    assert entity["history_entries"][0]["event"] == "Gift idea for [[Alice Example]]"
    assert entity["open_questions"] == ["Does [[Alice Example]] own the record?"]
    assert [r["text"] for r in entity[section_provenance.INPUTS]] == [
        "Favourite artist of [[Alice Example]]", "Loves [[Alice Example]]."]


def _bank(tmp_path):
    entities = tmp_path / "entities"
    entities.mkdir()
    markdown_parser.write(entities / "alice-example.md",
                          {"name": "Alice Example", "type": "person", "status": "active", "confidence": 0.8,
                           "aliases": ["Girlfriend", "Ally"], "source_episodes": ["ep_2026-11-01_001"]},
                          "## Summary\nAlice is a friend.\n")
    markdown_parser.write(entities / "artist-example.md",
                          {"name": "Artist Example", "type": "person", "status": "active", "confidence": 0.8,
                           "aliases": [], "source_episodes": ["ep_2026-11-01_001"]},
                          "## Summary\nA singer.\n\n## Key Facts\n- Favourite artist of [[Alice Example]]\n")
    return [{"id": p.stem, "frontmatter": markdown_parser.parse(p).frontmatter, "body": markdown_parser.parse(p).body}
            for p in sorted(entities.glob("*.md"))]


def test_a_batch_writes_one_spelling_and_the_second_mention_folds_into_the_first(tmp_path):
    """End to end through Stage 3 and the writer: two conversations name one person two ways; the page says it once."""
    existing = _bank(tmp_path)
    changes = [{"id": "artist-example", "action": "update", "source_episode": "ep_2026-11-19_001",
                "entity": {"name": "Artist Example", "type": "person", "summary": "",
                           "key_facts": ["Favourite artist of [[Girlfriend]]", "Favourite artist of [[Ally]]"]}}]
    out = asyncio.run(cr.resolve_and_prune(changes, existing, Settings(), decay=False, now=datetime(2026, 11, 20)))
    cr.apply_changes(out, tmp_path)
    body = markdown_parser.parse(tmp_path / "entities" / "artist-example.md").body
    assert body.count("Favourite artist of [[Alice Example]]") == 1
    assert "[[Girlfriend]]" not in body and "[[Ally]]" not in body


def test_the_article_writer_is_told_which_spellings_are_one_page():
    class Src:
        def __init__(self, text):
            self.text = text

    found = entity_article.same_spellings(
        [Src("Favourite artist of [[Girlfriend]]"), Src("Favourite of [[Ally]] and [[Alice Example]]"),
         Src("[[Bob]] came along")], NAMES)
    assert found == [{"as": "Ally", "is": "Alice Example"}, {"as": "Girlfriend", "is": "Alice Example"}]


def test_linkable_offers_one_name_a_page():
    original = "## Key Facts\n- Favourite of [[Girlfriend]]\n- Also [[Ally]] and [[Alice Example]]\n"
    known = {"Alice Example", "Girlfriend", "Ally", "alice-example"}
    assert cr._linkable(original, {}, {}, known, NAMES) == ["Alice Example"]
    assert cr._linkable(original, {}, {}, known) == ["Alice Example", "Ally", "Girlfriend"]
