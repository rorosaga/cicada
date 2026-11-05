"""A rename at the source renames the thing in Cicada (ROR-122, ruling 69, owner 2026-11-05).

The owner: "I think these two-way updates should be in all sources. So if a voice memo changes the name and stuff, like I
think this stuff should be synced and they should change names, don't you think?"

**The rule, in one place** (the sources that own a page call :func:`apply` inside the write they already make, under
their own admission, page lock and commit; the module touches no file):

1. The newest name a source reports wins; the old name stays as an alias, so old mentions and searches still find it.
2. A name the person set in Cicada wins and stays until they change it. The marks: ``name_by`` (the app's and the
   agent door's rename, ``project_ownership.apply_header``), or a ``name`` that is no longer the one a source wrote
   (``name_source``: a hand edit of the page).
3. Source into Cicada only; nothing is written back to any app.
4. Two doors for one thing: a door's report counts only when it CHANGES against what that door reported last
   (``names_seen``), so the door that last changed its name wins and a door repeating itself never flips the page back.
   A door seen for the first time on a page only sets its baseline: that is not a rename.

A rename is not a mention: no claim, no promotion, no decay reset, dates unchanged. The page's file name never changes
(ids are permanent); only ``name`` and the aliases do. An alias the person removed (``aliases_removed``) is never
re-added. A page with no mark is the source's.
"""
from __future__ import annotations

NAME_BY = "name_by"
NAME_SOURCE = "name_source"
NAMES_SEEN = "names_seen"
MAX_NAME = 300

BASELINE, SAME, RENAME, KEPT = "baseline", "same", "rename", "kept"


def clean(name) -> str:
    return " ".join(str(name or "").split())[:MAX_NAME]


def _fold(name) -> str:
    return clean(name).casefold()


def _seen(fm: dict) -> dict:
    seen = fm.get(NAMES_SEEN)
    return seen if isinstance(seen, dict) else {}


def person_named(fm: dict, *, was: str | None = None) -> bool:
    """The person (or an agent on their ask) named this page, or edited its name by hand. ``was``: the name the source
    wrote when the page carries no ``name_source`` yet (a page made before this rule)."""
    if isinstance(fm.get(NAME_BY), dict) and fm[NAME_BY]:
        return True
    source = fm.get(NAME_SOURCE)
    wrote = clean(source.get("name")) if isinstance(source, dict) else clean(was)
    return bool(wrote) and clean(fm.get("name")) != wrote


def decide(fm: dict, door: str, name, *, was: str | None = None, door_was: str | None = None) -> str:
    """What reporting ``name`` from ``door`` would do, without changing anything. ``door_was``: what this door gave
    for the page before this rule existed (a page whose only door is this one: its first real title)."""
    name = clean(name)
    if not name:
        return SAME
    last = _seen(fm).get(door)
    last = clean(last if last is not None else door_was)
    if not last:
        return BASELINE
    if last == name:
        return SAME
    return KEPT if person_named(fm, was=was) else RENAME


def note(fm: dict, door: str, name) -> bool:
    """Record what ``door`` called the page, setting no name: a baseline. ``True`` when the page changed."""
    name = clean(name)
    seen = dict(_seen(fm))
    if not name or seen.get(door) == name:
        return False
    seen[door] = name
    fm[NAMES_SEEN] = seen
    return True


def wrote(fm: dict, door: str, name, day: str) -> None:
    """A source just wrote ``name`` as the page's name (a new page, a placeholder given its title)."""
    name = clean(name)
    fm[NAME_SOURCE] = {"door": door, "name": name, "day": day}
    note(fm, door, name)


def _add_alias(fm: dict, alias: str) -> None:
    from api.services import page_edits

    if not alias or _fold(alias) == _fold(fm.get("name")):
        return
    have = [a for a in (fm.get("aliases") or []) if isinstance(a, str)]
    if _fold(alias) in {_fold(a) for a in have}:
        return
    fm["aliases"] = have + page_edits.keep_aliases(fm, [alias])


def apply(fm: dict, door: str, name, *, day: str, was: str | None = None, door_was: str | None = None) -> str:
    """Apply ``door``'s report of ``name`` to the frontmatter dict, in place. Returns what happened: ``baseline``,
    ``same``, ``rename`` (the name changed, the old one an alias) or ``kept`` (the person's name stands; the source's
    new one is an alias). The caller writes the page when anything but ``same`` came back."""
    verdict = decide(fm, door, name, was=was, door_was=door_was)
    name = clean(name)
    if verdict == SAME:
        return verdict
    if verdict == BASELINE:
        note(fm, door, name)
        return verdict
    if verdict == RENAME:
        old = clean(fm.get("name"))
        fm["name"] = name
        if _fold(old) != _fold(name):
            _add_alias(fm, old)
        fm[NAME_SOURCE] = {"door": door, "name": name, "day": day}
    else:
        _add_alias(fm, name)
    seen = dict(_seen(fm))
    seen[door] = name
    fm[NAMES_SEEN] = seen
    if fm.get("aliases"):
        fm["aliases"] = [a for a in fm["aliases"] if _fold(a) != _fold(fm.get("name"))]
        if not fm["aliases"]:
            fm.pop("aliases")
    return verdict
