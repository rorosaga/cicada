"""The way back from the lean pass (ruling 62, owner 2026-11-04): when a bare save gets its one real read.

A bookmark, a tab group, a saved link with no reason is indexed and read by no model (``history_index.kind`` ``saved``).
It gets a real read, once, when the person talks about it. Three things count, each by the record, never by a guess.
**Ruling 78 (e), owner 2026-11-24:** a save from a platform's list (``kind`` ``list``) wakes the same way for the first
two things only (the person's own words, never a lit page), and the same mention leaves an ask for the person's own
agent to go deeper (:mod:`mention_asks`):

* **Their own words name it** (:func:`wake_mentioned`, after a batch of conversations is read): one of the person's own
  turns holds the save's link, or says its whole title (three content words or more). Another speaker's line, an agent's
  reply and a page's own words count for nothing.
* **A conversation lit its page** (:func:`wake_lit`, before a run freezes its ids): Sleep or an agent tied a conversation
  or the person's words to the saved page, so it is no longer quiet (``quiet_pages``).
* **They give a reason.** That door already exists: ``saved_why``'s answer, a note, a ``## Saved because`` section make
  the episode theirs (``history_index.PERSON_KEYS``) and queue it.

A retrieval hit is none of these: being found says nothing about what the person cares about, and nothing on a read path
writes. An agent's ``cicada_record_read`` is its own read, with its own episode and claim: Sleep does not read it again.

**Named (G246 Track M, ruling 81, owner 2026-11-24).** The first of those, the person's own located words, is also what
gives a saved post its page: a post he talks about stops being a row under its list. So the same mention marks the save
(``named: {why, at}``, :func:`history_index.mark_named`) **whatever state it is in** — waiting, in the older pile, already
read, holding nothing to read — and no re-stage pops it. The mark never changes whether or when the save is read; the
wake above is a separate act for the saves it can still apply to, and the ask for the person's own agent is unchanged.
It is the person's act alone: only their own turns are searched (never an agent's, never a relayed app's), a retrieval
hit never writes, and the one caller is the Sleep batch that read the conversation, committed with it.

Rails: no model, no fetch. Only ``history_index.wake`` and ``history_index.mark_named`` write, under the episode lock.
Nothing here logs a title or a word.
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
    """The bank's saves the person could talk about: bare ones and, since ruling 78 (e), those from a platform's list."""

    by_link: dict[str, str] = field(default_factory=dict)        # url hash -> episode id
    by_first_word: dict[str, list[tuple[tuple[str, ...], str]]] = field(default_factory=dict)  # word -> (title, id)
    #: Episode id -> the list save's own record (``url``, ``origin``, ``folder``), for the saves from a platform's list
    #: only: what :mod:`mention_asks` needs to leave its ask. Includes a list save woken before (it is never woken twice
    #: but an ask is still owed when the first mention could not leave one).
    lists: dict[str, dict[str, str]] = field(default_factory=dict)
    #: The episodes a mention may wake now (the rest are in ``lists`` only to be asked about).
    wakeable: set[str] = field(default_factory=set)
    #: The saves a mention can only MARK as named (Track M): a bookmark or a pasted link already read or with nothing to
    #: read, which neither wakes nor is asked about. Kept apart from the two maps above so that a save that is there to be
    #: woken is never shadowed by another save of the same link, and the cap on wakes counts what it always counted.
    marked_by_link: dict[str, str] = field(default_factory=dict)
    marked_by_first_word: dict[str, list[tuple[tuple[str, ...], str]]] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.by_link or self.by_first_word or self.marked_by_link or self.marked_by_first_word)


def _title_words(title: str) -> tuple[str, ...]:
    words = list(text_fold.words(title))
    # A tab group's stored title is "Tab group: <name>"; the person says the name.
    if " ".join(words[:2]) + " " == _TAB_GROUP_PREFIX:
        words = words[2:]
    return tuple(words)


def _saves(memory_path: Path) -> _Saves:
    from api.services import media_ingestor, mention_asks

    out = _Saves()
    for f in bank_index.files(memory_path, "episodes"):
        fm = f.frontmatter or {}
        if fm.get("source_deleted_at"):
            continue
        # A record another service keeps (a repository he owns, a joined community, an open tab) is no save he could be
        # talking about; an episode that is no save at all (a conversation, a book's record, an agent's report) neither.
        if history_index.save_shaped(fm) is None or history_index.is_record(fm):
            continue
        # Ruling 80 (G246): a save in any state — waiting for tonight, waiting its turn in the pile, already read, holding
        # nothing to read. Where a mention can do something (``wakeable``): the first two; the ask for the person's own
        # agent (ruling 78 (e)) never depends on whether anything was read.
        state = history_index.save_state(fm)
        if not history_index.SAVES_READ:
            kind = history_index.kind(fm)
            woken = kind is None and bool(fm.get(history_index.WOKEN_KEY)) and history_index.is_list_origin(fm)
            state = ("pile" if kind in ("saved", "list") else "waiting" if woken else None)
        # A save of a platform's list, whichever way its own record reads (``mention_asks.list_key``, the one table every
        # list is registered in): a bookmark filed in no folder, and a connector's save (``r/<sub>``), are saves
        # to ``history_index.save_shaped`` yet are on a list all the same, so each is owed the same ask as any other.
        from_list = mention_asks.list_key(fm.get("origin") or "", fm.get("folder") or "") is not None
        # Something a mention can still do: wake it, or leave the ask. A bookmark already read or with nothing to read has
        # neither — it is only marked (Track M), and only when it has a page of its own to earn.
        actionable = state is not None and (state in ("pile", "waiting") or from_list or history_index.is_list_origin(fm))
        by_link, by_first_word = (out.by_link, out.by_first_word) if actionable \
            else (out.marked_by_link, out.marked_by_first_word)
        episode = str(fm.get("id") or f.stem)
        if actionable:
            if history_index.save_shaped(fm) != "saved" or from_list:
                out.lists[episode] = {"url": str(fm.get("url") or "").strip(), "origin": str(fm.get("origin") or ""),
                                      "folder": str(fm.get("folder") or "")}
            if history_index.mentionable(fm):
                out.wakeable.add(episode)
        elif not (str(fm.get("url") or "").strip() and fm.get("media_entity_id")):
            continue   # nothing to wake, no ask, and no page of its own to earn: a read tab group is named by nobody
        url = str(fm.get("url") or "").strip()
        if url:
            by_link.setdefault(media_ingestor.url_hash(url), episode)
        else:
            # A tab group holds its links in its body.
            try:
                for found in _URL_RE.findall(f.body()):
                    by_link.setdefault(media_ingestor.url_hash(found), episode)
            except OSError:
                continue
        title = str(fm.get("title") or "")
        if url and media_ingestor.is_placeholder_title(url, title):
            continue
        words = _title_words(title)
        if sum(1 for w in words if w not in text_fold.SUBJECT_STOPWORDS) >= MIN_TITLE_WORDS:
            by_first_word.setdefault(words[0], []).append((words, episode))
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


def _named(words_said: list[str], by_first_word: dict) -> list[tuple[int, str]]:
    """``(where in the text, episode id)`` for each title said whole."""
    out: list[tuple[int, str]] = []
    for i, word in enumerate(words_said):
        for title, episode in by_first_word.get(word, ()):
            if tuple(words_said[i:i + len(title)]) == title:
                out.append((i, episode))
    return out


def _found(episode: dict, *indexes: tuple[dict, dict], limit: int | None = None) -> dict[str, str]:
    """``{episode id: why}``: the saves of ``indexes`` (each ``(by_link, by_first_word)``, searched in turn) one
    conversation names in the person's own words, at most ``limit`` (``None``: every one), links first, each in the
    order said."""
    from api.services import media_ingestor

    found: dict[str, str] = {}
    own = _own_words(episode)
    for words in own:
        for url in _URL_RE.findall(words):
            digest = media_ingestor.url_hash(url.rstrip(".,;:!?"))
            for by_link, _by_first_word in indexes:
                hit = by_link.get(digest)
                if hit is not None:
                    found.setdefault(hit, WHY_LINK)
                    break
    for words in own:
        said = list(text_fold.words(words))
        for _by_link, by_first_word in indexes:
            for _at, hit in _named(said, by_first_word):
                found.setdefault(hit, WHY_TITLE)
    return dict(list(found.items())[:limit])


def mentioned(episode: dict, saves: _Saves) -> dict[str, str]:
    """``{episode id: why}``: the saves one conversation names in the person's own words that a mention can still act on
    (wake, or leave the ask for), at most :data:`MAX_WAKES_PER_CONVERSATION`, links first, each in the order said."""
    return _found(episode, (saves.by_link, saves.by_first_word), limit=MAX_WAKES_PER_CONVERSATION)


def named(episode: dict, saves: _Saves) -> dict[str, str]:
    """:func:`mentioned` over every save, whatever its state: what the person's own words name, to be marked as named
    (Track M). Not capped: the cap bounds reads, and a mark is a frontmatter stamp with no model, so every save the
    person's words name is marked; the saves a wake or an ask applies to are always among the marked."""
    return _found(episode, (saves.by_link, saves.by_first_word), (saves.marked_by_link, saves.marked_by_first_word))


def wake_mentioned(memory_path: Path, episodes: list[dict], *, at: str) -> list[str]:
    """After a batch: mark each save its conversations named, whatever its state (Track M: ``history_index.mark_named``,
    no model, no effect on the read), wake each that can still be read first, and (ruling 78 (e)) leave the person's own
    agent an ask for each one from a platform's list. The paths written, to commit with the batch. Never raises: a save
    not woken tonight is still found, and a later mention wakes it."""
    memory_path = Path(memory_path)
    paths: list[str] = []
    try:
        saves = _saves(memory_path)
        if not saves:
            return paths
        woken: dict[str, str] = {}
        marked: dict[str, str] = {}
        for episode in episodes:
            for hit, why in mentioned(episode, saves).items():
                woken.setdefault(hit, why)
            for hit, why in named(episode, saves).items():
                marked.setdefault(hit, why)
        for hit, why in {**marked, **woken}.items():
            # The mark first, the wake after: one file may carry both, and is one path of the batch's commit.
            written = [history_index.mark_named(memory_path, hit, why, at)]
            if hit in woken and hit in saves.wakeable:
                written.append(history_index.wake(memory_path, hit, why, at))
            paths.extend(p for p in written if p and p not in paths)
        asked = {hit: saves.lists[hit] for hit in woken if hit in saves.lists}
        if asked:
            from api.services import mention_asks

            mention_asks.offer(memory_path, asked)
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


__all__ = ["MAX_WAKES_PER_CONVERSATION", "MIN_TITLE_WORDS", "WHY_LINK", "WHY_LIT", "WHY_TITLE", "mentioned", "named",
           "page_lit", "wake_lit", "wake_mentioned"]
