"""What may be kept as another name for a page (``aliases:``) — one predicate, no I/O.

An alias is a NAME the thing also goes by ("Mongo" for MongoDB). A phrase that only points at something inside one
conversation — "the lock", "this project", "my app", "la base" — is a reference, not a name: it is true of a hundred
things in a hundred other conversations. Since #249 every recorded alias brings its page to the Stage 2 judge as a
candidate, so a reference recorded as an alias costs a judge call each time those common words recur, and offers the
wrong page.

The rule: a phrase of two or more words whose first word is an article, a demonstrative or a possessive (English or
Spanish) and whose remaining words carry no capital letter. "The Economist", "La Liga", "Los Angeles" and "My Little
Pony" are names and stay; "the session model" and "my app" are references and go. A single word is never judged here.
"""
from __future__ import annotations

#: Words that open a reference rather than a name, lowercased.
LEADS = frozenset({
    # English articles, demonstratives, possessives
    "the", "a", "an", "this", "that", "these", "those",
    "my", "our", "your", "his", "her", "their", "its",
    # Spanish
    "el", "la", "los", "las", "lo", "un", "una", "unos", "unas",
    "este", "esta", "estos", "estas", "ese", "esa", "esos", "esas", "aquel", "aquella",
    "mi", "mis", "tu", "tus", "su", "sus", "nuestro", "nuestra", "nuestros", "nuestras",
})


def is_reference(alias) -> bool:
    """True when ``alias`` is a determiner-led, all-lowercase-after phrase — a reference, not a name."""
    words = str(alias or "").split()
    if len(words) < 2 or words[0].lower() not in LEADS:
        return False
    return not any(ch.isupper() for word in words[1:] for ch in word)


def keep(aliases) -> list[str]:
    """``aliases`` without the references, order kept. A non-list is treated as no aliases."""
    if isinstance(aliases, str):
        aliases = [aliases]
    if not isinstance(aliases, (list, tuple)):
        return []
    return [a for a in aliases if isinstance(a, str) and a.strip() and not is_reference(a)]
