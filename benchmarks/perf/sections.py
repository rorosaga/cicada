"""Pure helpers of the perf probes: how a recall reply and an Ask prompt split into their parts (characters each).

Importable without the probes' scratch isolation, so the suite can test them."""
from __future__ import annotations

import re

_RECALL_SECTIONS = (
    ("hints", "```cicada-hints"),
    ("inbox", "**Open question"),
    ("hub", "**Relevant hub"),
    ("changed", "**Changed recently"),
    ("provisional", "**Not yet read by Sleep"),
    ("related_hop", "**Related (one hop out)"),
    ("excerpts", "**Related conversation excerpts"),
)


def recall_sections(text: str) -> dict[str, int]:
    """Characters of a recall reply by part (its parts are joined by blank lines; entity blocks start ``### ``)."""
    sizes: dict[str, int] = {}
    current = "other"
    for part in re.split(r"\n\n(?=```cicada-hints|\*\*|### |_\d+ lower-ranked)", text):
        label = "entities" if part.startswith("### ") else current
        for name, prefix in _RECALL_SECTIONS:
            if part.startswith(prefix):
                label = name
                break
        if part.startswith("Reference data from Cicada") or part.startswith("<<<"):
            label = "frame"
        sizes[label] = sizes.get(label, 0) + len(part)
        current = label if label != "entities" else "entities"
    return sizes


_ASK_SECTIONS = (
    ("linked_people", "\n\nLINKED PEOPLE"),
    ("what_was_said", "\n\nWHAT WAS SAID"),
    ("other_conversations", "\n\nOTHER CONVERSATIONS"),
    ("time_between", "\n\nTIME BETWEEN"),
    ("watch_history", "\n\nWATCH HISTORY"),
)


def ask_sections(prompt: str) -> dict[str, int]:
    """Characters of an Ask prompt by block: the entities (claims vs background prose) and each later block."""
    cuts = sorted((prompt.find(marker), name) for name, marker in _ASK_SECTIONS if marker in prompt)
    head_end = cuts[0][0] if cuts else len(prompt)
    entities = prompt[:head_end]
    out = {"claims": sum(len(line) + 1 for line in entities.splitlines() if line.startswith("claim: "))}
    out["entities_other"] = len(entities) - out["claims"]
    for i, (at, name) in enumerate(cuts):
        end = cuts[i + 1][0] if i + 1 < len(cuts) else len(prompt)
        out[name] = end - at
    return out
