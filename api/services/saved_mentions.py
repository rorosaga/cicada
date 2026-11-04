"""The way back from the lean pass (ruling 62, owner 2026-11-04): when a bare save gets its one real read.

A bookmark, a tab group, a saved link with no reason is indexed and read by no model (``history_index.kind`` ``saved``).
It gets a real read, once, when the person talks about it. Three things count, each by the record, never by a guess:

* **Their own words name it** (:func:`wake_mentioned`, after a batch of conversations is read): one of the person's own
  turns holds the save's link, or says its whole title (three content words or more). Another speaker's line, an agent's
  reply and a page's own words count for nothing.
* **A conversation lit its page** (:func:`wake_lit`, before a run freezes its ids): Sleep or an agent tied a conversation
  or the person's words to the saved page, so it is no longer quiet (``quiet_pages``).
* **They give a reason.** That door already exists: ``saved_why``'s answer, a note, a ``## Saved because`` section make
  the episode theirs (``history_index.PERSON_KEYS``) and queue it.

A retrieval hit is none of these: being found says nothing about what the person cares about, and nothing on a read path
writes. An agent's ``cicada_record_read`` is its own read, with its own episode and claim: Sleep does not read it again.

Rails: no model, no fetch. Only ``history_index.wake`` writes, under the episode lock. Nothing here logs a title or a word.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

from api.services import authorship, bank_index, evidence, history_index, quiet_pages, text_fold

#: Why a save woke: what the record's ``read_asked.why`` says. Enums only.
WHY_LINK = "said-the-link"
WHY_TITLE = "said-the-title"
WHY_LIT = "page-mentioned"
#: A title is a name only with this many words that mean something: "Reading", "My notes" are no mention.
MIN_TITLE_WORDS = 3
#: A paste of fifty links is not fifty things the person cares about: the first few, in the order said.
MAX_WAKES_PER_CONVERSATION = 5

_URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")
_TAB_GROUP_PREFIX = "tab group "


@dataclass
class _Saves:
    """The bank's bare saves, by what the person could say of them."""

    by_link: dict[str, str] = field(default_factory=dict)        # url hash -> episode id
    by_first_word: dict[str, list[tuple[tuple[str, ...], str]]] = field(default_factory=dict)  # word -> (title, id)

    def __bool__(self) -> bool:
        return bool(self.by_link or self.by_first_word)


def _title_words(title: str) -> tuple[str, ...]:
    words = list(text_fold.words(title))
    # A tab group's stored title is "Tab group: <name>"; the person says the name.
    if " ".join(words[:2]) + " " == _TAB_GROUP_PREFIX:
        words = words[2:]
    return tuple(words)


def _saves(memory_path: Path) -> _Saves:
    from api.services import media_ingestor

    out = _Saves()
    for f in bank_index.files(memory_path, "episodes"):
        fm = f.frontmatter or {}
        if history_index.kind(fm) != "saved" or fm.get("source_deleted_at"):
            continue
        episode = str(fm.get("id") or f.stem)
        url = str(fm.get("url") or "").strip()
        if url:
            out.by_link.setdefault(media_ingestor.url_hash(url), episode)
        else:
            # A tab group holds its links in its body.
            try:
                for found in _URL_RE.findall(f.body()):
                    out.by_link.setdefault(media_ingestor.url_hash(found), episode)
            except OSError:
                continue
        title = str(fm.get("title") or "")
        if url and media_ingestor.is_placeholder_title(url, title):
            continue
        words = _title_words(title)
        if sum(1 for w in words if w not in text_fold.SUBJECT_STOPWORDS) >= MIN_TITLE_WORDS:
            out.by_first_word.setdefault(words[0], []).append((words, episode))
    return out


def _own_words(episode: dict) -> list[str]:
    """The person's own turns of one read conversation, as ``evidence`` reads them: never a saved page's words, an
    agent's reply or another speaker's line."""
    text = str(episode.get("content") or "")
    if not text.strip():
        return []
    override = authorship.of_episode(episode)
    gaps = tuple(episode.get("gaps") or ())
    return [text[t.content_start:t.end] for t in evidence.turns(text, override=override, gaps=gaps)
            if t.role == "user"]


def _named(words_said: list[str], saves: _Saves) -> list[tuple[int, str]]:
    """``(where in the text, episode id)`` for each title said whole."""
    out: list[tuple[int, str]] = []
    for i, word in enumerate(words_said):
        for title, episode in saves.by_first_word.get(word, ()):
            if tuple(words_said[i:i + len(title)]) == title:
                out.append((i, episode))
    return out


def mentioned(episode: dict, saves: _Saves) -> dict[str, str]:
    """``{episode id: why}``: the saves one conversation names in the person's own words, at most
    :data:`MAX_WAKES_PER_CONVERSATION`, links first, each in the order said."""
    from api.services import media_ingestor

    found: dict[str, str] = {}
    for words in _own_words(episode):
        for url in _URL_RE.findall(words):
            hit = saves.by_link.get(media_ingestor.url_hash(url.rstrip(".,;:!?")))
            if hit is not None:
                found.setdefault(hit, WHY_LINK)
    for words in _own_words(episode):
        for _at, hit in _named(list(text_fold.words(words)), saves):
            found.setdefault(hit, WHY_TITLE)
    return dict(list(found.items())[:MAX_WAKES_PER_CONVERSATION])


def wake_mentioned(memory_path: Path, episodes: list[dict], *, at: str) -> list[str]:
    """After a batch: wake each bare save its conversations named. The paths written, to commit with the batch. Never
    raises: a save not woken tonight is still found, and a later mention wakes it."""
    memory_path = Path(memory_path)
    paths: list[str] = []
    try:
        saves = _saves(memory_path)
        if not saves:
            return paths
        woken: dict[str, str] = {}
        for episode in episodes:
            for hit, why in mentioned(episode, saves).items():
                woken.setdefault(hit, why)
        for hit, why in woken.items():
            path = history_index.wake(memory_path, hit, why, at)
            if path:
                paths.append(path)
    except Exception as exc:  # noqa: BLE001 — never the reason a batch fails
        logger.warning(f"Saved mentions skipped: {type(exc).__name__}")
    return paths


def page_lit(memory_path: Path, fm: dict) -> bool:
    """Has a conversation or the person's words reached this save's page? The quiet rule's own answer, derived."""
    page = str((fm or {}).get("media_entity_id") or "").strip()
    return bool(page) and bank_index.file(memory_path, "entities", f"{page}.md") is not None \
        and not quiet_pages.page_is_quiet(memory_path, page)


def wake_lit(memory_path: Path, *, at: str, skip: frozenset[str] = frozenset()) -> list[str]:
    """Before a run freezes: wake each indexed save whose page a conversation lit since. A page unchanged since its save
    was indexed cannot have been lit, so most of a large bank costs one comparison of two cached stamps. A save whose
    page is written for some other reason (a picture) answers the quiet rule and stays asleep. ``skip``: files dirty
    before this ran keep their own author until their writer commits them; the next run takes them."""
    memory_path = Path(memory_path)
    paths: list[str] = []
    for f in bank_index.files(memory_path, "episodes"):
        fm = f.frontmatter or {}
        if history_index.kind(fm) != "saved" or fm.get("processed_by") != history_index.INDEXED_BY:
            continue
        page = str(fm.get("media_entity_id") or "").strip()
        entry = bank_index.file(memory_path, "entities", f"{page}.md") if page else None
        if entry is None or entry.mtime_ns <= f.mtime_ns or f"episodes/{f.path.name}" in skip:
            continue
        if not quiet_pages.page_is_quiet(memory_path, page):
            path = history_index.wake(memory_path, str(fm.get("id") or f.stem), WHY_LIT, at)
            if path:
                paths.append(path)
    return paths


__all__ = ["MAX_WAKES_PER_CONVERSATION", "MIN_TITLE_WORDS", "WHY_LINK", "WHY_LIT", "WHY_TITLE", "mentioned",
           "page_lit", "wake_lit", "wake_mentioned"]
