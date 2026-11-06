"""ROR-136: the same-person pairs a person spots at a glance, found from the record alone.

Synthetic names only (`rexim`/`rikzim` stand for a misspelling and its right spelling). No word lists: letter classes."""
from datetime import date

import pytest

from api.services import bank_index, inbox_catchup, markdown_parser, person_duplicates as pd, pair_evidence


def test_sound_key_joins_a_mishearing_to_the_right_spelling():
    assert pd.sound_key("Rexim") == pd.sound_key("Rikzim") == "rksm"
    assert pd.word_match("rexim", "rikzim") == "sound"
    assert pd.word_match("daniel", "daniela") == "ending"       # a vowel ending is two names, only a lead
    assert pd.word_match("john", "mary") is None


def test_name_signals():
    assert pd.name_signals("Rexim", "Rikzim") == ["sound"]
    assert "short_in_full" in pd.name_signals("Eduardo", "Eduardo Example")
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
    _page(memory, "rexim", "Rexim", source_episodes=["ep_2026-01-01_001"])
    _page(memory, "rikzim", "Rikzim", source_episodes=["ep_2026-01-02_001", "ep_2026-01-03_001"])
    _page(memory, "eduardo", "Eduardo", aliases=["he", "Eduardo's brother"])          # pronoun / relation aliases: not names
    _page(memory, "eduardo-example", "Eduardo Example")
    _page(memory, "chris-alpha", "Chris Alpha", aliases=["Chris"])
    _page(memory, "chris-beta", "Chris Beta")
    _page(memory, "partner", "Partner", owner_roles=["partner"])
    _page(memory, "former-partner", "Former partner", owner_roles=["former-partner"])
    bank_index.invalidate()
    return memory


def test_candidates_finds_the_pairs_and_leaves_the_rest(bank):
    pairs = {tuple(sorted((p.a, p.b))): p for p in pd.candidates(bank)}
    assert ("rexim", "rikzim") in pairs and "sound" in pairs[("rexim", "rikzim")].signals
    assert ("eduardo", "eduardo-example") in pairs
    assert not any({"chris-alpha", "chris-beta"} == {p.a, p.b} for p in pairs.values())   # two fuller names that differ
    assert not any({"partner", "former-partner"} == {p.a, p.b} for p in pairs.values())   # role_people's, not ours
    assert all(p.score <= 0.95 for p in pairs.values())


def test_a_pair_the_person_called_two_people_is_never_listed(bank):
    from api.services import merge_rejections

    merge_rejections.add_rejected(bank, "rexim", "rikzim")
    assert not any({"rexim", "rikzim"} == {p.a, p.b} for p in pd.candidates(bank))


def test_propose_writes_one_ordinary_merge_question(bank, monkeypatch):
    monkeypatch.setattr(pair_evidence, "judge", lambda *a, **k: pair_evidence.Verdict(True, "", None, 0.4))
    report = pd.propose(bank, date(2026, 11, 6), budget=inbox_catchup.Budget(1))
    assert len(report.written) == 1 and report.skipped.get("drain_budget") is None or report.written
    card = markdown_parser.parse(bank / report.written[0]).frontmatter
    assert card["kind"] == "merge_suggestion" and card["detected"] == "person_duplicate"
    assert card["merge_target_hint"] and card["entity_id"] and card["suggested_confidence"] <= 0.4
    again = pd.propose(bank, date(2026, 11, 6), budget=inbox_catchup.Budget(5))
    assert all(w != report.written[0] for w in again.written)           # the pair with a question is not asked twice
