"""Speed 2026-10-29: ``entity_body._shown_whole`` finds whole-token anchors with ``str.find`` instead of one regex scan
of the whole growing text per anchor. It must answer exactly as the regex did, on every input."""
from __future__ import annotations

import random
import re

import pytest

from api.services import entity_body


def _regex(anchor: str, folded: str) -> bool:
    return re.search(r"(?<![\w.,:/-])" + re.escape(anchor) + r"(?![\w]|[.,:/-]\w)", folded) is not None


@pytest.mark.parametrize(("anchor", "folded"), [
    ("40", "it took 400 days"), ("40", "it took 40 days"), ("5", "since 2025"), ("5", "since 2025, 5 times"),
    ("2025", "on 2025-10-03"), ("2025", "on 2025."), ("2025", "on 2025.5"), ("v1", "v1.2"), ("v1", "v1."),
    ("alpha", "_alpha"), ("alpha", "alpha_"), ("alpha", "x.alpha"), ("alpha", "x/alpha"), ("alpha", "x alpha"),
    ("[[alpha project]]", "see [[alpha project]] here"), ("example.com", "at www.example.com"),
    ("café", "un café, deux"), ("é", "ée é"), ("1", ""), ("", "abc"), ("", ""), ("a", "a"),
])
def test_known_cases_match_the_regex(anchor, folded):
    assert entity_body._shown_whole(anchor, folded) == _regex(anchor, folded)


def test_random_text_matches_the_regex():
    rng = random.Random(29)
    alphabet = "ab1 2._,:/-éß_[]x"
    for _ in range(20000):
        folded = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 24)))
        anchor = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 3)))
        assert entity_body._shown_whole(anchor, folded) == _regex(anchor, folded), (anchor, folded)
