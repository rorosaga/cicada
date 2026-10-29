"""An alias that names a different thing (session-1 follow-up of #545, 2026-10-29; G21, G209, G198).

The owner's "same as?" leads kept coming back because a page listed a RELATED thing's name among the names it goes by
(a tool page listing its maker's product line, a fork listing the original). An alias lead (``person_leads``) brings the
two pages to the judge every time either is matched; once the record says they are two things — a relation claim
(``entity_relations.known``), the person's "different" (``merge_rejections``), or a judge's ``related``/``different``
verdict on the lead — the alias is the cause, not the pair. Two halves, one class:

* :func:`propose` / :func:`for_pair` — the cure. One ``page_edit`` proposal (G198's own inbox kind: the person applies
  or leaves it, nothing is removed silently) to remove that alias from the page that lists it, the reason in words.
  Idempotent: never while the alias is gone, already removed by an edit (``aliases_removed``), kept by the person
  (:data:`KEPT`, written when they leave such a proposal), or already proposed. Applying it goes through the ordinary
  apply path, so the removal is remembered and no automatic writer adds it back.
* :func:`names_other_thing` — the prevention. Sleep's alias writer (``conflict_resolver``) never adds, as a NEW alias,
  the name of a page the record already holds as a different or related thing. Engine-free: one ``is_file`` and, only
  when a page of that name exists, the two pages' claims and the rejection list.

A trusted harness may remove such an alias itself with ``cicada_edit_page(remove_aliases=…)`` (its own G198 trust);
the proposal is the person's, as every proposed edit is.
"""
from __future__ import annotations

from pathlib import Path

from loguru import logger

from api.services import markdown_parser

#: ``origin`` of the proposal (the dismiss path reads it to remember the person's keep).
ORIGIN = "wrong_alias"
#: Aliases the person chose to keep when Cicada proposed removing them (casefolded): never proposed again.
KEPT = "aliases_kept"
#: Who proposes: Sleep, and the check that settled a pair — Cicada itself, never an agent's name.
AUTHOR = "cicada"


def _fold(text) -> str:
    return " ".join(str(text or "").split()).casefold()


def _key(text) -> str:
    from api.services import person_leads

    return person_leads.handle_key(str(text or ""))


def kept(frontmatter: dict) -> set[str]:
    raw = (frontmatter or {}).get(KEPT)
    return {_fold(a) for a in raw if isinstance(a, str) and a.strip()} if isinstance(raw, list) else set()


def _page(memory_path: Path, page_id: str):
    path = Path(memory_path) / "entities" / f"{page_id}.md"
    if not page_id or not path.is_file():
        return None
    try:
        return markdown_parser.parse(path)
    except Exception:  # noqa: BLE001 — an unreadable page proposes nothing
        return None


def listed(frontmatter: dict, name: str) -> str | None:
    """The alias on this page that IS ``name`` (the same handle key), as the page spells it, else ``None``."""
    want = _key(name)
    if not want:
        return None
    for alias in frontmatter.get("aliases") or [] if isinstance(frontmatter.get("aliases"), list) else []:
        if isinstance(alias, str) and _key(alias) == want:
            return alias
    return None


def _open(memory_path: Path, page_id: str, alias: str) -> bool:
    """An open ``page_edit`` proposal on ``page_id`` already removes ``alias`` (anyone's)."""
    inbox = Path(memory_path) / "inbox"
    if not inbox.is_dir():
        return False
    for path in inbox.glob("inbox-*.md"):
        try:
            # Only a page edit about this page is parsed: the text test keeps a 500-question inbox at a few ms.
            text = path.read_text(encoding="utf-8")
            if "page_edit" not in text or page_id not in text:
                continue
            fm = markdown_parser.parse(path).frontmatter
        except Exception:  # noqa: BLE001
            continue
        if fm.get("kind") != "page_edit" or str(fm.get("entity_id") or "") != page_id:
            continue
        edit = fm.get("edit") if isinstance(fm.get("edit"), dict) else {}
        if any(_fold(a) == _fold(alias) for a in edit.get("remove_aliases") or []):
            return True
    return False


def propose(memory_path: Path, holder_id: str, other_name: str, why: str, *, day: str | None = None) -> str | None:
    """A ``page_edit`` proposal removing, from ``holder_id``, the alias that is ``other_name`` — because ``why`` (a
    sentence: the two are different or related things). Returns the item's bank-relative path, or ``None`` when there
    is nothing to propose (the alias is gone, removed, kept by the person, or already proposed)."""
    from api.services import page_edits

    parsed = _page(memory_path, holder_id)
    if parsed is None:
        return None
    fm = parsed.frontmatter
    alias = listed(fm, other_name)
    if alias is None or _fold(alias) in page_edits.removed_aliases(fm) or _fold(alias) in kept(fm):
        return None
    if _open(memory_path, holder_id, alias):
        return None
    name = str(fm.get("name") or holder_id)
    reason = page_edits.clean_reason(f"“{alias}” is the name of another thing, not of {name}: {why}")
    request = page_edits.Request(remove_aliases=[alias])
    try:
        rel = page_edits.write_proposal(memory_path, entity_id=holder_id, name=name, request=request, reason=reason,
                                        author=AUTHOR, session=None, day=day, origin=ORIGIN)
    except page_edits.EditError as exc:
        logger.debug(f"Wrong alias not proposed: {type(exc).__name__}")
        return None
    return rel


def for_pair(memory_path: Path, a_id: str, a_name: str, b_id: str, b_name: str, why: str, *,
             day: str | None = None) -> list[str]:
    """Both directions of a pair the record holds as two things: A listing B's name, and B listing A's."""
    out = []
    for holder, other in ((a_id, b_name), (b_id, a_name)):
        if holder and other:
            rel = propose(memory_path, holder, other, why, day=day)
            if rel:
                out.append(rel)
    return out


def names_other_thing(memory_path: Path | None, page_id: str, alias: str) -> bool:
    """Is ``alias`` the name of ANOTHER page the record holds as a different or related thing to ``page_id``? Then
    it is not a name ``page_id`` goes by, and Sleep never adds it as one."""
    from api.services import entity_relations, merge_rejections
    from api.services.id_utils import sanitize_id

    if memory_path is None or not page_id or not str(alias or "").strip():
        return False
    other = sanitize_id(str(alias))
    if not other or other == page_id or not (Path(memory_path) / "entities" / f"{other}.md").is_file():
        return False
    try:
        return (entity_relations.known(Path(memory_path), page_id, other)
                or merge_rejections.is_rejected(Path(memory_path), other, page_id))
    except Exception:  # noqa: BLE001 — unreadable record: the alias goes on by the usual rule
        return False


def remember_kept(page_path: Path, aliases) -> bool:
    """The person left a proposal to remove these aliases: keep them, and never propose it again. True if written."""
    try:
        parsed = markdown_parser.parse(page_path)
    except Exception:  # noqa: BLE001
        return False
    fm = dict(parsed.frontmatter)
    have = [a for a in fm.get(KEPT) or [] if isinstance(a, str)] if isinstance(fm.get(KEPT), list) else []
    seen = {_fold(a) for a in have}
    added = [a for a in aliases or [] if isinstance(a, str) and a.strip() and _fold(a) not in seen]
    if not added:
        return False
    fm[KEPT] = have + added
    markdown_parser.write(page_path, fm, parsed.body)
    return True
