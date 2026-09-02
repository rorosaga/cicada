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


def parse_json_object(raw: str | None) -> dict:
    """Parse a JSON object from a possibly-noisy LLM response.

    Tolerates ```json fences, leading prose/thinking before the object, and
    trailing commentary after it.
    """
    if not raw or not raw.strip():
        raise ValueError("empty LLM response")
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
