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


def test_the_full_name_stories_are_benchmark_fixtures_with_an_expectation():
    from pathlib import Path

    here = Path(e2e.__file__).parent
    for name, key in (("true", "joined"), ("father", "not_joined"), ("colleagues", "not_joined")):
        story = json.loads((here / f"full_name_e2e_{name}.json").read_text(encoding="utf-8"))
        assert {c["phase"] for c in story["conversations"]} == {1, 2} and story["expect"]["one"] == ["teo"]
        assert story["expect"][key][0] == {"alias": "Teodor Brandt", "page": "teo"}
        assert set(story["gold"]) >= {"points", "updates", "forbid", "people", "pages", "dated"}, "run_leg scores it"


def _bank_with_join(tmp_path, *, alias_on_page=True, settled=True, held=False):
    (tmp_path / "entities").mkdir(exist_ok=True)
    aliases = "aliases:\n- Teodor Brandt\n" if alias_on_page else ""
    (tmp_path / "entities" / "teo.md").write_text(f"---\nname: Teo\ntype: person\n{aliases}---\n\n## Summary\n", encoding="utf-8")
    (tmp_path / "inbox" / "settled").mkdir(parents=True, exist_ok=True)
    if settled:
        (tmp_path / "inbox" / "settled" / "inbox-001.md").write_text(
            "---\nentity_name: Teodor Brandt\nsettled:\n  rule: full_name_one\n---\n\nbody\n", encoding="utf-8")
    if held:
        (tmp_path / "pending_entities.jsonl").write_text(json.dumps({"name": "Teodor Brandt", "type": "person"}) + "\n", encoding="utf-8")
    return tmp_path


def test_a_joined_alias_is_read_as_joined_and_a_held_or_unsettled_one_is_not(tmp_path):
    want = {"alias": "Teodor Brandt", "page": "teo"}
    assert e2e.joined_row(_bank_with_join(tmp_path), want, joined=True)["ok"]
    assert not e2e.joined_row(tmp_path, want, joined=False)["ok"]


def test_no_join_is_read_as_not_joined(tmp_path):
    bank = _bank_with_join(tmp_path, alias_on_page=False, settled=False, held=True)
    want = {"alias": "Teodor Brandt", "page": "teo"}
    assert e2e.joined_row(bank, want, joined=False)["ok"] and not e2e.joined_row(bank, want, joined=True)["ok"]
    assert e2e.check(bank, {"one": ["teo"], "not_joined": [want]})["ok"]
