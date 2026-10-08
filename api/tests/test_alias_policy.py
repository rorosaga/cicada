"""A reference ("the lock") is not a name: Sleep never records one as a NEW alias. The rule is narrow so real names
(Spanish titles, numbered names, possessives) are never caught, and it never touches what a page already lists.
Synthetic names only."""
import pytest

from api.services import alias_policy, conflict_resolver, entity_resolver, markdown_parser


@pytest.mark.parametrize("alias", [
    "the lock", "the session model", "the new claim format", "the alpha arm", "this project", "these notes",
    "la base", "esa herramienta", "the db", "an  idea", "aquel bar",
])
def test_a_reference_is_not_a_name(alias):
    assert alias_policy.is_reference(alias)


@pytest.mark.parametrize("alias", [
    # Names keep a capital at least at the start — Spanish titles of works only there (fix round 1, B1).
    "La casa de papel", "El señor de los anillos", "Las chicas del cable", "Un mundo feliz", "El laberinto del fauno",
    "The Economist", "La Liga", "Los Angeles", "The xx", "The Alpha Project",
    # A number makes a name.
    "The 1975", "The 100", "El 47", "the 1975",
    # A possessive is how the person refers to one thing (owner hypothesis 2026-10-08): kept.
    "my mom", "mi mamá", "our house", "my app",
    "Mongo", "the", "AlphaDataset", "alpha", "Q3 plan", "", None,
])
def test_a_name_is_kept(alias):
    assert not alias_policy.is_reference(alias)


def test_keep_filters_and_tolerates_junk():
    assert alias_policy.keep(["Mongo", "the db", "", 3, "La casa de papel"]) == ["Mongo", "La casa de papel"]
    assert alias_policy.keep("the db") == []
    assert alias_policy.keep(None) == []


def test_a_created_page_records_names_not_references(tmp_path):
    (tmp_path / "entities").mkdir()
    conflict_resolver.apply_changes([{"id": "alpha-db", "action": "create",
                                      "entity": {"name": "Alpha DB", "type": "tool",
                                                 "aliases": ["ADB", "the db", "this database"]}}], tmp_path)
    fm = markdown_parser.parse(tmp_path / "entities" / "alpha-db.md").frontmatter
    assert fm["aliases"] == ["ADB"]


def test_an_update_filters_only_what_sleep_adds(tmp_path):
    (tmp_path / "entities").mkdir()
    # What the page already lists (a hand-added one included) is the page's and stays.
    markdown_parser.write(tmp_path / "entities" / "alpha-db.md",
                          {"name": "Alpha DB", "type": "tool", "aliases": ["the lake house"]}, "## Summary\nA db.\n")
    conflict_resolver.apply_changes([{"id": "alpha-db", "action": "update",
                                      "entity": {"name": "Alpha DB", "aliases": ["ADB", "the session model"]}}],
                                    tmp_path)
    fm = markdown_parser.parse(tmp_path / "entities" / "alpha-db.md").frontmatter
    assert fm["aliases"] == ["the lake house", "ADB"]


def test_the_judge_index_reads_every_alias_a_page_lists():
    """Fix round 1 (B1/B2): the rule filters only what Sleep adds. A listed alias — a person's merge records the
    losing page's name, "the lake house" included — keeps bringing its page to the judge (#249)."""
    page = {"id": "alpha-db", "frontmatter": {"name": "Alpha DB", "aliases": ["the lake house", "ADB"]}}
    assert set(entity_resolver._alias_index({"alpha db": page})) == {"the lake house", "adb"}
