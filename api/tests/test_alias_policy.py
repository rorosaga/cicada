"""A reference ("the lock") is not a name: Sleep never records one as an alias, and the Stage 2 judge is never
offered a page because of one (#249 made every alias a candidate lead). Synthetic names only."""
import pytest

from api.services import alias_policy, conflict_resolver, entity_resolver, markdown_parser


@pytest.mark.parametrize("alias", [
    "the lock", "the session model", "the new claim format", "the alpha arm", "this project", "my app",
    "our tracker", "la base", "mi proyecto", "esa herramienta", "the db", "an  idea",
])
def test_a_reference_is_not_a_name(alias):
    assert alias_policy.is_reference(alias)


@pytest.mark.parametrize("alias", [
    "Mongo", "the", "The Economist", "the Alpha Project", "La Liga", "Los Angeles", "My Little Pony",
    "AlphaDataset", "alpha", "Q3 plan", "", None,
])
def test_a_name_is_kept(alias):
    assert not alias_policy.is_reference(alias)


def test_keep_filters_and_tolerates_junk():
    assert alias_policy.keep(["Mongo", "the db", "", 3, "The Economist"]) == ["Mongo", "The Economist"]
    assert alias_policy.keep("the db") == []
    assert alias_policy.keep(None) == []


def test_a_created_page_records_names_not_references(tmp_path):
    (tmp_path / "entities").mkdir()
    conflict_resolver.apply_changes([{"id": "alpha-db", "action": "create",
                                      "entity": {"name": "Alpha DB", "type": "tool",
                                                 "aliases": ["ADB", "the db", "my database"]}}], tmp_path)
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


def test_the_judge_is_never_offered_a_page_for_a_reference():
    page = {"id": "alpha-db", "frontmatter": {"name": "Alpha DB", "aliases": ["the lock", "ADB"]}}
    index = entity_resolver._alias_index({"alpha db": page})
    assert set(index) == {"adb"}
