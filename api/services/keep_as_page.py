"""\"Keep as a page\": the person gives a saved post a page of its own, for good (G246, ruling 81; plan Track K).

A saved post nobody referred to is a row under its list, not a page (``saved_posts``). Two things were missing from
that: a way for the person to say "this one matters" without writing a note, and a way back for a work the link rule
drew as a row by mistake (a long thread that is really an article). This module is both. The click stamps one key on the
post's own save, ``kept_as_page: {at}`` (``saved_posts.KEPT_KEY``), which the one predicate reads as an earned sign
(``saved_posts.episode_signs``): the page is drawn like any page from the next graph on, and it keeps that for good —
Sleep's reading, a retracted claim or a folder losing its reason never take it away.

Same shape as every other change to a save the person makes (``saved_why``, ``history_index.wake``):

* **under the episode lock**, frontmatter only — the body, its hash, ``processed`` and every evidence span are untouched,
  so a click never re-queues a save for Sleep and never costs a model read (a page is not a reason to read: only the
  person's words are, ruling 62);
* the caller admits it (``write_admission``) and commits it **alone, as the person** (``Cicada-Author: user``);
* nothing is rewritten on the page: it is the save's stamp, so git history shows the click and ``Back to a row`` is one
  more commit.

**Back to a row is allowed only while nothing else has earned the page.** A post the person also wrote a note on, named
in a conversation or edited keeps its page whatever this key says; taking the stamp away would change nothing they could
see and would read as a lie. The refusal names what else holds it (``because_of``, sign ids from ``saved_posts.SIGNS``,
never a title).

Everything here answers whatever ``saved_posts.HIDE_POSTS`` says, so the route and its stamp are testable while the
flip is off; only :func:`offer` — what the app is shown — is dark until the flip.
"""
from __future__ import annotations

from pathlib import Path

from api.services import bank_index, episode_ids, markdown_parser, quiet_pages, saved_posts

#: The commit trigger.
TRIGGER = "user/keep_as_page"

#: What the app is told about a save: ``none`` (no control: not a post, not saved, or the flip is off), ``row`` (drawn
#: under its list: "Keep as a page"), ``kept`` (the person's own click holds its page: "Back to a row" when
#: ``can_undo``), ``page`` (something else earned it a page: no control).
STATES = ("none", "row", "kept", "page")


class KeepError(ValueError):
    """A request the route answers with 4xx: ``status``, a plain sentence and, for a refusal that names what else holds
    the page, ``because_of``."""

    def __init__(self, status: int, message: str, because_of: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.status = status
        self.because_of = because_of


def _find(memory_path: Path, url: str) -> tuple[str, str, Path]:
    """``(episode id, page id, episode path)`` of the saved link, or :class:`KeepError`: 422 for a link that is not
    http(s), 404 for one not saved or whose save has no page of its own to keep."""
    from api.services import saved_why

    try:
        episode_id, page_id, path = saved_why.find_episode(memory_path, url)
    except saved_why.SavedWhyError as e:
        raise KeepError(e.status, str(e)) from e
    if not page_id or not (Path(memory_path) / "entities" / f"{page_id}.md").is_file():
        raise KeepError(404, "That save has no page to keep.")
    return episode_id, page_id, path


def facts(memory_path: Path, page_id: str) -> tuple[str, tuple[str, ...]]:
    """``(state, other signs)`` of one page by the one predicate, whatever the flip says: ``none`` for a page that is no
    post (a work keeps its page, there is nothing to keep), else ``row``/``kept``/``page`` by its signs, and the signs
    other than the person's own click."""
    v = saved_posts.verdict(memory_path)
    if page_id not in v.state.posts:
        return "none", ()
    signs = v.signs.get(page_id, frozenset())
    others = tuple(s for s in saved_posts.SIGNS if s in signs and s != "kept")
    if "kept" in signs:
        return "kept", others
    return ("page" if signs else "row"), others


def _view(memory_path: Path, episode_id: str, page_id: str) -> dict:
    state, others = facts(memory_path, page_id)
    return {"state": state, "can_undo": state == "kept" and not others, "because_of": list(others),
            "episode_id": episode_id, "media_entity_id": page_id}


def offer(memory_path: Path, url: str) -> dict:
    """What the app may draw for this link (``GET``): the real state while ``HIDE_POSTS`` is on, ``none`` otherwise —
    until the flip every post is a page and there is nothing to keep. A link that is not saved, or has no page, is
    ``none`` too: a read never fails a card."""
    empty = {"state": "none", "can_undo": False, "because_of": [], "episode_id": "", "media_entity_id": ""}
    if not saved_posts.HIDE_POSTS:
        return empty
    try:
        episode_id, page_id, _ = _find(memory_path, url)
    except KeepError:
        return empty
    return _view(memory_path, episode_id, page_id)


def _stamp_episode(path: Path, kept: bool, at: str) -> bool:
    """Set (or remove) the stamp on one episode under the episode lock, re-read inside it. ``True`` when the file
    changed. Frontmatter only."""
    with episode_ids.episode_lock(path.parent):
        try:
            parsed = markdown_parser.parse(path)
        except Exception:  # noqa: BLE001 - a save that vanished meanwhile has nothing to stamp
            return False
        fm = dict(parsed.frontmatter)
        if kept:
            if fm.get(saved_posts.KEPT_KEY):
                return False
            fm[saved_posts.KEPT_KEY] = {"at": at}
        else:
            if saved_posts.KEPT_KEY not in fm:
                return False
            fm.pop(saved_posts.KEPT_KEY, None)
        markdown_parser.write(path, fm, parsed.body)
    return True


def _stamped_saves(memory_path: Path, page_id: str) -> list[Path]:
    """Every save of this page that carries the stamp (the click's own, and any a repeat save of the link inherited)."""
    return [Path(f.path) for f in bank_index.files(memory_path, "episodes")
            if isinstance(f.frontmatter, dict) and f.frontmatter.get(saved_posts.KEPT_KEY)
            and str(f.frontmatter.get(quiet_pages.SAVE_KEY) or "") == page_id]


def keep(memory_path: Path, *, url: str, kept: bool = True, at: str | None = None) -> dict:
    """Keep the saved post as a page (``kept``) or send it back to a row. Returns the wire dict (``status`` is
    ``kept``, ``undone`` or ``unchanged``, plus the state after) and the memory-relative ``paths`` the caller commits.
    The caller admits it and commits (inside its write admission). :class:`KeepError` for a link not saved (404), a
    save with no page (404) and a way back refused because something else earned the page (409)."""
    memory_path = Path(memory_path)
    episode_id, page_id, path = _find(memory_path, url)
    state, others = facts(memory_path, page_id)
    if state == "none":
        # A work keeps its page already; there is nothing to keep and nothing to undo.
        return {**_view(memory_path, episode_id, page_id), "status": "unchanged", "paths": []}
    changed: list[Path] = []
    if kept:
        if _stamp_episode(path, True, at or episode_ids.utc_now_seconds()):
            changed.append(path)
    elif state == "kept":
        if others:
            raise KeepError(409, "It has a page for another reason too, so it stays one.", others)
        for stamped in {path, *_stamped_saves(memory_path, page_id)}:
            if _stamp_episode(stamped, False, ""):
                changed.append(stamped)
    paths = sorted({f"episodes/{p.name}" for p in changed})
    status = ("kept" if kept else "undone") if changed else "unchanged"
    return {**_view(memory_path, episode_id, page_id), "status": status, "paths": paths}


def commit_message(paths: list[str], kept: bool) -> str:
    """The commit that carries the click, authored by the person alone."""
    from api.services import git_service

    return git_service.build_commit_message(
        "Kept a saved post as a page" if kept else "Sent a saved post back to a row",
        [f"{p}: updated (trigger: {TRIGGER})" for p in paths], authors=[git_service.USER_AUTHOR])
