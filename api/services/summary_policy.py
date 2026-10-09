"""Deterministic structure budget for machine prose; no semantic inference."""
from __future__ import annotations

import re

MAX_CHARS = 600


def usable(text: str) -> bool:
    """A nonempty, bounded paragraph. Readability/grounding still need review."""
    text = (text or '').strip()
    return bool(text) and len(text) <= MAX_CHARS and not re.search(r'\r?\n[ \t]*\r?\n', text)


def fallback(*, name: str = '', entity_type: str = '') -> str:
    """The identity line a machine Summary falls back to when nothing written fits.

    It says only what the page knows for certain — its name and kind. It used to
    add "Its present role for the owner is not established.", which read as a
    claim against the page's own Key Facts (a project the person built, said not
    to be established); a one-sentence lead now keeps the orientation in almost
    every case (`entity_body.lead`)."""
    kinds = {'person': 'person', 'project': 'project', 'company': 'company', 'concept': 'concept',
             'tool': 'tool', 'skill': 'skill', 'location': 'place', 'directory': 'folder', 'media': 'saved item'}
    kind = kinds.get(entity_type, 'entity')
    name = ' '.join((name or '').split())
    if not name or len(name) > 400:
        return "This entity's present role for the owner is not established."
    article = 'an' if kind == 'entity' else 'a'
    return f'{name} is {article} {kind}.'
