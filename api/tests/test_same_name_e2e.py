"""`benchmarks/consolidation/same_name_e2e.py`: the engine-free half (the fixture and the reading of a bank)."""
import json

from benchmarks.consolidation import same_name_e2e as e2e


def _page(bank, page_id, name, kind="person"):
    (bank / "entities").mkdir(exist_ok=True)
    (bank / "entities" / f"{page_id}.md").write_text(f"---\nname: {name}\ntype: {kind}\n---\n\n## Summary\n", encoding="utf-8")


def test_the_join_story_is_a_benchmark_fixture_with_phases_and_an_expectation():
    story = json.loads(e2e.JOIN.read_text(encoding="utf-8"))
    assert {c["phase"] for c in story["conversations"]} == {1, 2, 3}, "three nights: a person, a doubt, the link"
    assert story["expect"]["one"] and story["expect"]["two"]
    assert set(story["gold"]) >= {"points", "updates", "forbid", "people", "pages", "dated"}, "run_leg scores it"


def test_a_bank_is_read_by_first_name_and_only_person_pages_count(tmp_path):
    for page_id, name, kind in (("ilse", "Ilse", "person"), ("sara", "Sara", "person"), ("sara-2", "Sara", "person"),
                                ("olek", "Olek", "person"), ("olek-bakery", "Olek", "company")):
        _page(tmp_path, page_id, name, kind)
    (tmp_path / "_same_name_doubts.yaml").write_text(
        "pairs:\n- a: sara\n  b: sara-2\njoined:\n- a: ilse\n  b: ilse-2\n  commit: abc\n", encoding="utf-8")
    result = e2e.check(tmp_path, {"one": ["ilse", "olek"], "two": ["sara"]})
    assert result["ok"] and result["names"]["sara"]["pages"] == ["sara", "sara-2"]
    assert result["in_doubt"] == [["sara", "sara-2"]] and result["joined_by_sleep"] == [["ilse", "ilse-2"]]


def test_a_doubt_left_standing_where_one_person_was_expected_fails(tmp_path):
    _page(tmp_path, "ilse", "Ilse")
    _page(tmp_path, "ilse-2", "Ilse")
    result = e2e.check(tmp_path, {"one": ["ilse"]})
    assert not result["ok"] and result["names"]["ilse"]["pages"] == ["ilse", "ilse-2"]
