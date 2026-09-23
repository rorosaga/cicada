"""G136 — the one folding rule every server-side matcher shares (pure)."""
from __future__ import annotations

from api.services import text_fold


def test_fold_drops_case_and_diacritics_like_quickmatch():
    assert text_fold.fold("Zürich CAFÉ") == "zurich cafe"
    # A decomposed accent (u + U+0308) folds the same as the precomposed one.
    assert text_fold.fold("Zürich") == "zurich"


def test_query_tokens_split_like_unicode61_and_drop_one_letter_tokens():
    assert text_fold.query_tokens("  Zürich, a CAFÉ café x_y") == ["zurich", "cafe"]
    assert text_fold.query_tokens("a b") == []
    assert text_fold.query_tokens("") == []
    assert len(text_fold.query_tokens(" ".join(f"w{i}" for i in range(20)))) == text_fold.MAX_TOKENS


def test_words_are_the_folded_index_tokens():
    assert text_fold.words("Zürich-Office, HQ_2") == ["zurich", "office", "hq", "2"]


def test_contains_all_is_substring_and_across_words():
    assert text_fold.contains_all("Planning alpha-project", "alpha plan")
    assert not text_fold.contains_all("Planning alpha-project", "alpha beta")
    assert text_fold.contains_all("anything", "   ")


def test_match_offsets_are_word_start_prefixes_in_original_code_points():
    assert text_fold.match_offsets("Zürich café", ["zur", "caf"]) == [[0, 3], [7, 10]]
    # The decomposed accent sits inside the span: 4 code points for "Zür".
    assert text_fold.match_offsets("Zürich", ["zur"]) == [[0, 4]]
    # Word-start only: "cap" inside "escape" is not a hit.
    assert text_fold.match_offsets("capital escape cap", ["cap"]) == [[0, 3], [15, 18]]
    assert text_fold.match_offsets("alpha", []) == []


def test_match_offsets_slice_back_to_the_matched_text():
    text = "We moved the index to sqlite-vec so search is fast"
    spans = text_fold.match_offsets(text, text_fold.query_tokens("sqlite vec"))
    assert [text[s:e] for s, e in spans] == ["sqlite", "vec"]
