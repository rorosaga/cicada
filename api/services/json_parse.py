"""The one lenient JSON-object parser for every LLM response in Cicada.

Promoted out of ``entity_extractor`` (where it was ``_parse_json_lenient``)
because six other call sites needed it and did not have it: three called bare
``json.loads`` and three carved a ``{...}`` substring by hand. A reasoning
model that emits a preamble, a ```json fence, or trailing commentary is the
normal case, not the exception — and each of those sites failed differently
and silently.

Raises ``ValueError`` (``json.JSONDecodeError`` is a subclass) on empty or
unparseable content so the caller can count the work failed and requeue.
"""
from __future__ import annotations

import json
import re


class EmptyResponse(ValueError):
    """The answer was empty (a ``ValueError``, so every existing catch still holds) —
    told apart from an unparseable one so a drain can say which."""


def parse_json_object(raw: str | None) -> dict:
    """Parse a JSON object from a possibly-noisy LLM response.

    Tolerates ```json fences, leading prose/thinking before the object, and
    trailing commentary after it.
    """
    if not raw or not raw.strip():
        raise EmptyResponse("empty LLM response")
    text = raw.strip()

    # Strip a leading ```json / ``` fence and its closing ``` if present.
    if text.startswith("```"):
        text = re.sub(r"^```[A-Za-z0-9]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()

    # Fast path: the whole thing is JSON.
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Otherwise carve out the first balanced {...} object (skips reasoning
    # prose before it and any trailing text after it).
    start = text.find("{")
    if start == -1:
        raise ValueError("no JSON object found in response")
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : i + 1])  # JSONDecodeError -> ValueError
    raise ValueError("unbalanced JSON object in response")


def parse_json_object_or(raw: str | None, default: dict) -> dict:
    """:func:`parse_json_object`, degrading to ``default`` instead of raising.

    For the two sweep call sites whose contract is "an unparseable answer is
    an *unsure* verdict", not "the sweep failed".
    """
    try:
        return parse_json_object(raw)
    except ValueError:
        return dict(default)


def numbered_rows(rows, count: int, key: str) -> list[dict] | None:
    """A batch answer's rows in input order, or ``None`` when they cannot be trusted to line up (2026-10-20).

    Sleep asks one call about ``count`` numbered items (``entry`` for the judge, ``entity`` for the contradiction
    check). A row is read against an item only when the numbers are exactly the distinct set 1..count, one row each;
    by position only when no row carries a number and there are exactly ``count`` rows. Anything else — 0-based
    numbers, a duplicate, a gap, a number out of range, numbered and unnumbered rows mixed, too few or too many rows,
    a row that is not an object — is ``None``: the caller reads every item as an unreadable answer, never a shifted one.
    """
    if not isinstance(rows, list) or len(rows) != count or not all(isinstance(row, dict) for row in rows):
        return None
    numbers = [row.get(key) for row in rows]
    if all(n is None for n in numbers):
        return list(rows)
    parsed: list[int] = []
    for n in numbers:
        if isinstance(n, bool):
            return None
        if isinstance(n, int):
            parsed.append(n)
        elif isinstance(n, str) and n.strip().isdigit():
            parsed.append(int(n.strip()))
        else:
            return None   # missing beside numbered rows, or not a whole number
    if sorted(parsed) != list(range(1, count + 1)):
        return None
    ordered: list[dict] = [{}] * count
    for n, row in zip(parsed, rows):
        ordered[n - 1] = row
    return ordered
