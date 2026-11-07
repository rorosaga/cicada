"""Whether two offered values say the same thing, with no model (question audit A8; G98).

Exact on what it folds: case, spacing, punctuation, an approximator ("about 1,118"), a version's leading "v", and "per
month" written two ways. A value that starts with another and goes on is a fuller wording of it, unless the next word
changes what it means ("3" and "3 million", "5" and "5 or 6", "done" and "done but not sent").
"""

from __future__ import annotations

import re

_APPROXIMATE = re.compile(r"^(?:about|approximately|approx\.?|roughly|around|circa|~)\s*")
_VERSION_V = re.compile(r"^v(?=\d)")
_PER_MONTH = re.compile(r"\s*(?:per\s+month|/\s*month|/\s*mo)\b")
_NOISE = re.compile(r"[^\w%$€.]+")
_VERSION = re.compile(r"^\d+(?:\.\d+)+$")
_CHANGES_THE_MEANING = frozenset("""thousand k m mn million bn billion trillion x times or to vs versus but not no never
except minus before after""".split())
_GOES_ON = " ,(;:+-/"


def _plain(value) -> str:
    text = str(value or "").casefold().strip()
    previous = None
    while text != previous:
        previous = text
        text = _APPROXIMATE.sub("", text)
    return _VERSION_V.sub("", text)


def fold(value) -> str:
    return _NOISE.sub("", _PER_MONTH.sub("permo", _plain(value))).rstrip(".")


def refines(short, long) -> bool:
    """``long`` says what ``short`` says and more."""
    a, b = _plain(short), _plain(long)
    if not a or len(b) <= len(a) or not b.startswith(a):
        return False
    rest = b[len(a):]
    if rest[0] == "." and _VERSION.match(a):
        return True
    if rest[0] not in _GOES_ON:
        return False
    next_word = re.sub(r"^[\s,(;:+/-]+", "", rest).split(" ", 1)[0].strip(",;:)")
    return next_word not in _CHANGES_THE_MEANING


def same_value(labels: list[str]) -> bool:
    """Every label says the shortest one, in the same words or more of them."""
    if len(labels) < 2:
        return False
    base = min(labels, key=lambda label: len(fold(label)))
    return bool(fold(base)) and all(fold(label) == fold(base) or refines(base, label) for label in labels)
