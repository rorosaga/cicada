"""ROR-136: the same-person pairs a person spots at a glance, found from the record alone.

Synthetic names only (`texim`/`tikzim` stand for a misspelling and its right spelling). No word lists: letter classes."""
from datetime import date

import pytest

from api.services import bank_index, inbox_catchup, markdown_parser, person_duplicates as pd, pair_evidence


def test_sound_key_joins_a_mishearing_to_the_right_spelling():
    assert pd.sound_key("Texim") == pd.sound_key("Tikzim") == "tksm"
    assert pd.word_match("texim", "tikzim") == "sound"
    assert pd.word_match("daniel", "daniela") == "ending"       # a vowel ending is two names, only a lead
    assert pd.word_match("john", "mary") is None


def test_name_signals():
    assert pd.name_signals("Texim", "Tikzim") == ["sound"]
    assert "short_in_full" in pd.name_signals("Dana", "Dana Example")
    assert pd.name_signals("Sam", "Samantha") == ["short_in_full"]
    assert pd.name_signals("Anna Smith", "Anna Smyth") in (["spelling"], ["sound"])
    assert pd.name_signals("Chris Alpha", "Chris Beta") == []
    assert pd.name_signals("Zed", "Maria") == []


def _page(memory, eid, name, **fm):
    markdown_parser.write(memory / "entities" / f"{eid}.md",
                          {"name": name, "type": "person", "status": "active", **fm}, f"## Summary\n{name}.\n")


@pytest.fixture
def bank(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    memory = tmp_path / "bank"
    for d in ("entities", "episodes", "inbox"):
        (memory / d).mkdir(parents=True)
    _page(memory, "texim", "Texim", source_episodes=["ep_2026-01-01_001"])
    _page(memory, "tikzim", "Tikzim", source_episodes=["ep_2026-01-02_001", "ep_2026-01-03_001"])
    _page(memory, "dana", "Dana", aliases=["he", "Dana's brother"])          # pronoun / relation aliases: not names
    _page(memory, "dana-example", "Dana Example")
    _page(memory, "chris-alpha", "Chris Alpha", aliases=["Chris"])
    _page(memory, "chris-beta", "Chris Beta")
    _page(memory, "partner", "Partner", owner_roles=["partner"])
    _page(memory, "former-partner", "Former partner", owner_roles=["former-partner"])
    bank_index.invalidate()
    return memory


def test_candidates_finds_the_pairs_and_leaves_the_rest(bank):
    pairs = {tuple(sorted((p.a, p.b))): p for p in pd.candidates(bank)}
    assert ("texim", "tikzim") in pairs and "sound" in pairs[("texim", "tikzim")].signals
    assert ("dana", "dana-example") in pairs
    assert not any({"chris-alpha", "chris-beta"} == {p.a, p.b} for p in pairs.values())   # two fuller names that differ
    assert not any({"partner", "former-partner"} == {p.a, p.b} for p in pairs.values())   # role_people's, not ours
    assert all(p.score <= 0.95 for p in pairs.values())


def test_a_pair_the_person_called_two_people_is_never_listed(bank):
    from api.services import merge_rejections

    merge_rejections.add_rejected(bank, "texim", "tikzim")
    assert not any({"texim", "tikzim"} == {p.a, p.b} for p in pd.candidates(bank))


def test_propose_writes_one_ordinary_merge_question(bank, monkeypatch):
    monkeypatch.setattr(pair_evidence, "judge", lambda *a, **k: pair_evidence.Verdict(True, "", None, 0.4))
    report = pd.propose(bank, date(2026, 11, 6), budget=inbox_catchup.Budget(1))
    assert len(report.written) == 1 and report.skipped.get("drain_budget") is None or report.written
    card = markdown_parser.parse(bank / report.written[0]).frontmatter
    assert card["kind"] == "merge_suggestion" and card["detected"] == "person_duplicate"
    assert card["merge_target_hint"] and card["entity_id"] and card["suggested_confidence"] <= 0.4
    again = pd.propose(bank, date(2026, 11, 6), budget=inbox_catchup.Budget(5))
    assert all(w != report.written[0] for w in again.written)           # the pair with a question is not asked twice


# --------------------------------------------------------------------------- ruling 74: two independent signals join


def test_names_that_sound_alike_are_one_signal_never_two():
    assert pd.kinds_of(["sound", "short_in_full", "spelling"]) == ["name"]
    assert pd.kinds_of(["sound", "alias"]) == ["name", "alias"]


def test_sounding_alike_alone_never_joins_but_a_listed_name_does(bank):
    _page(bank, "tomas", "Tomás", source_episodes=["ep_2026-01-01_001", "ep_2026-01-02_001"])
    _page(bank, "tom", "Tom", aliases=["Tomás"], source_episodes=["ep_2026-01-03_001"])
    bank_index.invalidate()
    pairs = {tuple(sorted((p.a, p.b))): p for p in pd.candidates(bank)}
    assert pairs[("texim", "tikzim")].joinable is False                    # the name is all they share
    assert pairs[("tom", "tomas")].joinable is True                        # the name and one page's own list
    assert pd.join_reason(bank, "tomas", "tom").startswith("2 independent signals")
    assert pd.join_reason(bank, "texim", "tikzim") == ""


def test_named_together_a_relation_titled_page_or_a_second_candidate_never_joins(bank):
    _page(bank, "tomas", "Tomás", source_episodes=["ep_2026-01-01_001"])
    _page(bank, "tom", "Tom", aliases=["Tomás"], source_episodes=["ep_2026-01-01_001"])      # one conversation names both
    _page(bank, "mia", "Mia", aliases=["Mía"], source_episodes=["ep_2026-02-01_001"])
    _page(bank, "mía", "Mía", source_episodes=["ep_2026-02-02_001"])
    _page(bank, "mi-a", "Mía Example", source_episodes=["ep_2026-02-03_001"])               # a second page "Mía" could be
    _page(bank, "partner", "Partner", owner_roles=["partner"], aliases=["Zed"])
    _page(bank, "zed", "Zed", source_episodes=["ep_2026-03-01_001"])
    bank_index.invalidate()
    assert pd.join_reason(bank, "tom", "tomas") == ""
    assert pd.join_reason(bank, "mia", "mía") == ""
    assert pd.join_reason(bank, "partner", "zed") == ""


def test_a_pair_the_person_called_two_people_never_joins(bank):
    from api.services import merge_rejections

    _page(bank, "tomas", "Tomás", source_episodes=["ep_2026-01-01_001"])
    _page(bank, "tom", "Tom", aliases=["Tomás"], source_episodes=["ep_2026-01-03_001"])
    bank_index.invalidate()
    assert pd.join_reason(bank, "tom", "tomas")
    merge_rejections.add_rejected(bank, "tom", "tomas")
    assert pd.join_reason(bank, "tom", "tomas") == ""
