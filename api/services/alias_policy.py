"""What Sleep may record as another name for a page (``aliases:``) — one predicate, no I/O.

An alias is a NAME the thing also goes by ("Mongo" for MongoDB). A phrase that only points at something inside one
conversation — "the lock", "this project", "la base" — is a reference, not a name: it is true of a hundred things in a
hundred other conversations, and since #249 every recorded alias brings its page to the Stage 2 judge.

**The rule is deliberately narrow (fix round 1, 2026-10-08).** A reference is two or more words, ALL lowercase, no
digit, the first an article or demonstrative (English or Spanish). Why each condition:

* *All lowercase, the first word too.* Titles and names are capitalised at least at the start — Spanish titles of works
  only there ("La casa de papel", "El señor de los anillos", "Un mundo feliz"), so "no capital after the article" threw
  real names away. The throwaway aliases Stage 1 emitted are lowercase from the first letter ("the session model").
* *No digit.* "The 100", "El 47", "the 1975": a number makes a name, not a pointer.
* *No possessive.* "my mom", "mi mamá", "our house" are how the person refers to one thing, consistently, across
  conversations — on a person page that IS the useful alias (owner hypothesis, 2026-10-08). "my app" is noisier, but a
  wrong lead costs one judge call and the judge decides; a dropped real name costs a duplicate page.

What still slips through as a false positive is a real name the person typed all lowercase and article-led ("the xx",
"la casa de papel" typed in a chat). That loss is acceptable because the rule is used in ONE place only — Sleep's
NEW aliases (``conflict_resolver.apply_changes``) — never on what a page already lists, never in the judge's alias
index, and a lowercase spelling of a page's own name is already matched by name, case-insensitively.
"""
from __future__ import annotations

#: Words that open a reference rather than a name (articles and demonstratives), lowercased.
LEADS = frozenset({
    "the", "a", "an", "this", "that", "these", "those",
    "el", "la", "los", "las", "lo", "un", "una", "unos", "unas",
    "este", "esta", "estos", "estas", "ese", "esa", "esos", "esas", "aquel", "aquella", "aquellos", "aquellas",
})


def is_reference(alias) -> bool:
    """True when ``alias`` is an all-lowercase, digit-free phrase led by an article or demonstrative."""
    text = str(alias or "")
    words = text.split()
    if len(words) < 2 or words[0] not in LEADS:
        return False
    return not any(ch.isupper() or ch.isdigit() for ch in text)


def keep(aliases) -> list[str]:
    """``aliases`` without the references, order kept. A non-list is treated as no aliases."""
    if isinstance(aliases, str):
        aliases = [aliases]
    if not isinstance(aliases, (list, tuple)):
        return []
    return [a for a in aliases if isinstance(a, str) and a.strip() and not is_reference(a)]
