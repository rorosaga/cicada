"""A merge closes the "Is A the same as B?" question it answers, on the one merge primitive (owner 2026-11-06).

Synthetic bank only (`alpha-example`, `alpha-eg`, `carol-example`)."""
import subprocess

import pytest

from api.services import bank_index, markdown_parser, merge_closes, page_join, page_redirects


def _git(memory, *args):
    return subprocess.run(["git", "-C", str(memory), *args], check=True, capture_output=True, text=True).stdout


def _card(memory, num, entity, target, **extra):
    markdown_parser.write(memory / "inbox" / f"inbox-{num:03d}.md",
                          {"kind": "merge_suggestion", "status": "pending", "entity_id": entity,
                           "merge_target_hint": target, **extra}, "Same person?")


@pytest.fixture
def bank(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    memory = tmp_path / "bank"
    for d in ("entities", "episodes", "inbox"):
        (memory / d).mkdir(parents=True)
    for eid, name in (("alpha-example", "Alpha Example"), ("alpha-eg", "Alpha Eg"), ("carol-example", "Carol Example")):
        markdown_parser.write(memory / "entities" / f"{eid}.md", {"name": name, "type": "person", "status": "active"},
                              f"## Summary\n{name}.\n")
    _card(memory, 1, "alpha-eg", "alpha-example")          # the pair, asked about the loser
    _card(memory, 2, "alpha-example", "alpha-eg")          # the pair the other way round
    _card(memory, 3, "alpha-eg", "carol-example")          # another pair: stays
    _card(memory, 4, "alpha-eg", "alpha-example", status="resolved")   # already answered: untouched
    _card(memory, 5, "alpha-eg", "alpha-example", same_title=["alpha-example", "alpha-eg"])  # "which one?": stays
    _git(memory, "init", "-q")
    _git(memory, "config", "user.email", "test@example.com")
    _git(memory, "config", "user.name", "Test")
    _git(memory, "add", "-A")
    _git(memory, "commit", "-qm", "seed")
    bank_index.invalidate()
    page_redirects.invalidate()
    return memory


def test_merge_closes_exactly_the_questions_it_answers(bank):
    result = page_join.merge(bank, "alpha-eg", "alpha-example", author="user", reason="same person")
    left = sorted(p.name for p in (bank / "inbox").glob("inbox-*.md"))
    assert left == ["inbox-003.md", "inbox-004.md", "inbox-005.md"]
    assert "inbox/inbox-001.md" in result["paths"] and "inbox/inbox-002.md" in result["paths"]
    assert _git(bank, "status", "--porcelain", "inbox").strip() == ""      # closed in the merge's own commit


def test_open_questions_reads_both_directions_and_nothing_else(bank):
    assert merge_closes.open_questions(bank, "alpha-eg", "alpha-example") == ["inbox/inbox-001.md",
                                                                              "inbox/inbox-002.md"]
    assert merge_closes.open_questions(bank, "alpha-eg", "carol-example") == ["inbox/inbox-003.md"]


def test_two_people_answer_takes_a_crossed_alias_off(bank):
    from api.services import merge_rejections

    fm = markdown_parser.parse(bank / "entities" / "alpha-eg.md").frontmatter
    markdown_parser.write(bank / "entities" / "alpha-eg.md", {**fm, "aliases": ["Alpha Example", "Algy"]}, "## Summary\nx.\n")
    assert merge_rejections.uncross_aliases(bank, "alpha-eg", "alpha-example") == ["entities/alpha-eg.md"]
    after = markdown_parser.parse(bank / "entities" / "alpha-eg.md").frontmatter
    assert after["aliases"] == ["Algy"] and after["aliases_removed"][0]["alias"] == "Alpha Example"
    assert merge_rejections.uncross_aliases(bank, "alpha-eg", "alpha-example") == []
