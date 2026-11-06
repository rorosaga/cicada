"""Words in any script, and a question in a language no word list here was written for (2026-11-06, G148). Synthetic bank;
the word index alone, no network. Measured on a public conversation held and asked in each language, nothing slept:
Ask's questions with an answer turn of 38, Japanese 0 → 15, Chinese 0 → 20, Arabic 10 → 14, German 18 → 21, English 25 → 25."""
from __future__ import annotations

import pytest

from api.services import ask_sources, bank_index, evidence, markdown_parser, search_index, text_fold


def test_an_unspaced_run_is_read_as_overlapping_pairs_with_no_dictionary():
    assert text_fold.unspaced_pairs(text_fold.fold("東京タワー")) == ["東京", "京タ", "タワ", "ワー"]
    assert text_fold.unspaced_pairs(text_fold.fold("hello world")) == []


def test_a_latin_name_inside_an_unspaced_run_stays_a_word():
    terms = text_fold.subject_terms("Carolineの猫")
    assert "caroline" in terms or any(t.startswith("carolin") for t in terms)
    assert "の猫" in terms


def test_a_pair_matches_inside_a_run_and_a_word_only_at_its_start():
    pattern = text_fold.term_pattern({"東京", "cat"})
    assert pattern.findall(text_fold.fold("私は東京にいる")) == ["東京"]
    assert pattern.findall("my cat, a bobcat") == ["cat"]


@pytest.mark.parametrize("question,lang", [
    ("How many books did I read?", "en"), ("¿Cuántos libros leí?", "es"), ("キャロラインはいつ来ましたか", "other"),
    ("卡罗琳什么时候来的", "other"), ("متى جاءت كارولين", "other"), ("Wann ist Caroline gekommen?", "other"),
])
def test_a_question_says_when_the_lists_do_not_know_its_language(question, lang):
    assert ask_sources.question_language(question) == lang


def test_a_short_english_line_is_not_taken_for_another_language():
    assert ask_sources.text_language("Lisbon 2024") == "en"
    assert ask_sources.text_language("東京") == ask_sources.LANGUAGE_OTHER


@pytest.fixture
def bank(tmp_path):
    memory = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (memory / sub).mkdir(parents=True)
    said = {f"ep_2023-{i:02d}-01_001": f"user: 今週の買い物リスト{i}を手伝ってください。\nassistant: はい、リスト{i}です。\n"
            for i in range(1, 13)}
    said["ep_2024-02-03_001"] = "user: 昨日、東京タワーで古い時計を買いました。\nassistant: いいですね。\n"
    for ep, body in said.items():
        markdown_parser.write(memory / "episodes" / f"{ep}.md",
                              {"id": ep, "timestamp": f"{ep[3:13]}T10:00:00+00:00", "processed": False,
                               "source": "import", "content_hash": evidence.body_hash(body)}, body)
    assert search_index.ensure_fresh(memory, wait=True, max_age_s=0) == "ready"
    bank_index.invalidate()
    yield memory
    bank_index.invalidate()


def test_a_word_inside_a_japanese_turn_finds_it_and_the_turn_is_quoted(bank):
    question = "古い時計はどこで買いましたか"
    found = ask_sources.search(bank, question)
    assert "ep_2024-02-03_001" in found.episodes
    shown = ask_sources.gather_search(bank, question, found)
    assert any("東京タワー" in e.text for e in shown)
