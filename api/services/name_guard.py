"""What may leave in a web search or an opened link: never the name of someone known only from the person's own record
(ruling 54, owner correction 2026-11-04).

The owner: reading the person's chats and contacts is fine, it stays between Cicada and the plan's model. "The one limit
is on what leaves in a web search": no query may contain the name of someone known only from the chats or contacts. So
this module does not decide who may be read; it decides, in code, on every query a model writes and every link it
would open, whether the words may go out. It sends nothing and writes nothing.

**A tie blocks always; a mention blocks unless the public record has it too.**

* **A tie** — the person has this one in their life on the record: a Contacts card (the waiting set, the contacts book,
  a page carrying a card's source or photo), a LinkedIn connection, a chat's correspondent, a group member, a speaker
  label in a chat or a meeting, a page the record says the person knows (``web_context.known_personally``), a person page
  or held name the public record never says, the owner's own names. A friend who wrote a blog post the person saved is
  still a friend: **public content never clears a tie.** A name matches in either word order and when one holds the
  other ("<given>" against "<given> <family>"); never two full names that only share a first name. A project of the
  owner's blocks as a whole phrase.
* **A mention** — the words were said anywhere that is not public content. They pass only if the same words are also said
  in public content (:func:`public_part`): a public figure the person also talked about is not blocked for that, a
  neighbour named only in a chat is.

**Public content is a positive decision, per writer and per section; everything else is private** (a reviewer's finding,
2026-11-04: the person's note on a saved link read as public and cleared a friend's name). :data:`WRITERS` names each writer
and what of its body is the item's own words: a saved link's description and, when the page was really read, its title —
never its note, reason or folder; a page an agent read, its quotes; a watched video, its quotes; a watched, listened or
Substack day's rows. A LinkedIn or Instagram save, a tab group, a day's reading across every site, the person's own
repositories and any source this module does not know are private. A link says one thing publicly: the handle of a post
(``x.com/<h>/status/…``); a saved link to a bare profile says nothing.

**A mention is a name, not any words someone happened to use** (a reviewer's finding, 2026-11-04: ordinary words said in a
harness session blocked "who is <handle>" and most links, and stopped the question). A query's words are asked only when
they are name-shaped: written capitalised in the query, or :attr:`NameGuard.name_like` in the record (written capitalised at
least as often as not, a handle's shape, an ``@mention``, an account's bare link). A pair is also asked when it was said in a
chat, where names are often typed in lower case. A word in :data:`GENERIC` ("github", "who", "developer") is never asked,
and neither is a pair of two of them. **What is held as strictly as ever is a real name:** :func:`words` folds fully (NFKD,
marks off, case off, plus :data:`TRANSLIT` for "ø", "ł", "ß"); one-letter tokens are dropped on both sides, so a middle initial
changes nothing, and a capital initial beside a name-shaped word makes that word stricter; every pair of a query's name-shaped
words and every window of three is asked in every order; a long token is asked as each split of it; a tied name is also
compared with its spaces out. The question's own cleared name and handle are taken out first (:func:`NameGuard.check`
``allowed``), so a contact who shares a first name does not block a cleared full name, while that first name alone does.

**A link a search returned is held to ties only** (:meth:`NameGuard.check_url`): the model did not choose it, so it cannot
carry the model's words, and a page's path is full of ordinary ones. A blocked link is counted and never stops the question.

**The index.** One contentless in-memory FTS5 table per side, built once a run from ``bank_index``'s cached headers, off the
event loop (never under write admission: ``public_handle.settle`` does not rebuild it), dropped by :func:`release`. It
holds no text a reader could get back and never touches a disk.

**Fail closed, for what leaves only.** A store that exists and cannot be read, or holds an unexpected shape, raises
:class:`GuardUnreadable`: nothing is searched and nothing found by a search is opened. A store that does not exist is empty.

**Blocked means dropped.** The caller drops the query, counts it against the budget and never rewrites it; the reason is
an enum, and neither a query nor a name is logged.
"""
from __future__ import annotations

import itertools
import json
import re
import sqlite3
import threading
import time
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlsplit

from api.services import bank_index, people_directory, person_leads, text_fold

#: Cicada's own records of what it looked up: neither the person's life nor something the person read.
NEUTRAL_SOURCES = frozenset({"web-check", "source-check", "source-refresh"})
#: Conversations with other people, by source: where names are typed in lower case. A record with a correspondent, members or
#: speaker labels counts too, whatever its source.
CHAT_SOURCES = frozenset({"imessage", "messages", "whatsapp", "telegram", "telegram-chats", "email", "gmail"})
#: The folder the contacts book (open PR #602, ``contacts_book``) keeps its per-device ``book.json`` in. Read by layout,
#: never by import, so the guard covers it the moment it lands.
CONTACTS_BOOK_DIR = "contacts-book"
BOOK_FILE = "book.json"
WAITING_FILE = "contacts.json"
LINKEDIN_FILE = "linkedin-connections.json"
#: Past this much text a scan is refused rather than kept in memory: the guard fails closed.
MAX_CORPUS_CHARS = 400_000_000
MAX_QUERY_CHARS = 160
MAX_QUERY_WORDS = 12
MAX_TOKEN_CHARS = 32
MAX_URL_WORDS = 64
MIN_COMPACT = 5
MIN_SPLIT = 6
#: The guard held between two calls in one run: rebuilt when the record changes, dropped by :func:`release`.
KEEP_S = 300.0

GENERIC = frozenset(text_fold.SUBJECT_STOPWORDS) | frozenset("""
github gitlab twitter x instagram linkedin mastodon bluesky threads youtube reddit substack medium hackernews
website site homepage home page personal blog about bio biography profile account accounts handle handles username
usernames user users official real name names who is verified talk talks interview podcast paper papers code repo
com org net dev io co ai app me www http https html htm php en es wiki wikipedia wikidata blog posts post
developer developers engineer engineers software founder cofounder ceo cto researcher professor author writer speaker
designer artist programmer maintainer creator work works worked job company open source contact social media news
""".split())
#: Labels a chat writer uses for someone it has no name for: nobody's name.
_NO_NAME = frozenset({"contact", "member", "unnamed", "unknown", "you", "me", "user", "assistant"})
#: Letters NFKD leaves alone. One name, one spelling, whichever way it was typed.
TRANSLIT = str.maketrans({"ø": "o", "ł": "l", "ß": "ss", "đ": "d", "ð": "d", "þ": "th", "æ": "ae", "œ": "oe", "ħ": "h",
                          "ı": "i", "ŋ": "n", "ĸ": "k", "ſ": "s", "ŧ": "t", "ƒ": "f"})
_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
_URL = re.compile(r"https?://[^\s)>\]\"']+")
_SPEAKER = re.compile(r"^speaker:([^:\n]{1,120}):", re.MULTILINE)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"(?<!\d)(?:\+?\d[\s().-]?){7,}(?!\d)")
_KEY_LINE = re.compile(r"^\*\*([A-Za-z ]+):\*\*\s*(.*)$")
_AT = re.compile(r"(?<![\w.])@([A-Za-z0-9_][\w.-]{1,38})")
#: A saved link's own record lines: nothing the person typed.
_ITEM_KEYS = frozenset({"source", "url", "site", "channel", "saved", "originally saved"})


class GuardUnreadable(Exception):
    """A store the guard must read could not be read: nothing leaves."""


def fold(text) -> str:
    text = str(text or "")
    if text.isascii():   # most of a bank, and its own NFKD: a per-character pass over all of it took 17 s at 9,478 episodes
        return text.lower()
    decomposed = unicodedata.normalize("NFKD", text)
    bare = "".join(c for c in decomposed if not unicodedata.combining(c))
    return bare.casefold().translate(TRANSLIT)


def words(text) -> list[str]:
    """The folded tokens, every one: what a query is cut into."""
    return _TOKEN.findall(fold(text))


def _indexed(text) -> str:
    """What the index holds: the tokens with one-letter ones dropped, so a middle initial changes nothing."""
    return " ".join(w for w in words(text) if len(w) > 1)


def _mixed_script(text: str) -> bool:
    """A token mixing Latin with another alphabet is a respelling (a look-alike letter), never a real word."""
    for token in words(text):
        kinds = {unicodedata.name(c, "?").split(" ")[0] for c in token if c.isalpha()}
        if "LATIN" in kinds and len(kinds) > 1:
            return True
    return False


# ------------------------------------------------------------------------------------------------ public content


def _post_handles(text: str) -> str:
    """The one thing a link says in public: the handle of a post. A saved bare profile says nothing about anyone."""
    out = []
    for url in _URL.findall(text or ""):
        found = person_leads.profile_handle(url)
        if found is not None and "/status/" in url:
            out.append(found[1])
    return " ".join(out)


def _no_links(text: str) -> str:
    return _URL.sub(" ", text or "")


def _saved_link(fm: dict, body: str, _pages: dict) -> tuple[str, str]:
    """``media_ingestor._episode_body``: the title, ``**Channel:**`` and the first ``## Description`` are the item's. Its
    note, ``## Saved because``, ``## User note``, ``## Note`` and ``**Folder:**`` are the person's. A title with no
    description may be the person's own bookmark name (the page was never read): it stays private. An episode of a note
    alone (``Note on …``) has no item's words at all."""
    lines = (body or "").splitlines()
    public: list[str] = []
    private: list[str] = []
    title = ""
    channel = ""
    url = ""
    description: list[str] = []
    section = ""
    seen_other = False
    for i, line in enumerate(lines):
        if line.startswith("## "):
            heading = line[3:].strip()
            section = heading if heading == "Description" and not seen_other and not description else "other"
            seen_other = seen_other or section == "other"
            continue
        if section == "Description":
            description.append(line)
            continue
        if section == "other":
            private.append(line)
            continue
        if i == 0 and line.startswith("# "):
            title = line[2:]
            continue
        match = _KEY_LINE.match(line)
        key = match.group(1).strip().lower() if match else ""
        if key == "channel":
            channel = match.group(2)
        elif key == "url":
            url = match.group(2)
        elif key not in _ITEM_KEYS and line.strip():
            private.append(line)   # a line this writer does not name (a folder, anything new): not the item's
    if str(fm.get("folder") or "").strip():
        private.append(str(fm["folder"]))
    has_words = bool(" ".join(description).strip())
    if has_words or str(fm.get("source") or "").lower() == "youtube":
        public += [title, channel]
    elif title and not title.startswith("Note on "):
        private.append(title)
    public += description
    public.append(_post_handles(url))
    return "\n".join(p for p in public if p), "\n".join(private)


def _quotes(prefix: str):
    """An agent's record of what it read: only the lines it quoted are the item's; its summary is its own."""
    def read(fm: dict, body: str, _pages: dict) -> tuple[str, str]:
        public: list[str] = []
        private: list[str] = []
        for line in (body or "").splitlines():
            if line.startswith(prefix):
                public.append(line.split(":", 1)[-1] if prefix == "video [" else line[len(prefix):])
            elif not line.startswith("attachment ["):
                private.append(line)
        return "\n".join(public), "\n".join(private)
    return read


def _page_read(fm: dict, body: str, pages: dict) -> tuple[str, str]:
    """A page an agent read: its quotes, unless the page was behind a sign-in on a site of people's own posts."""
    if re.search(r"^attachment \[(?:[^\]]*\.)?(?:linkedin|instagram|facebook)\.com\]", body or "", re.MULTILINE):
        return "", body or ""
    return _quotes("> ")(fm, body, pages)


def _day_of_rows(fm: dict, body: str, _pages: dict) -> tuple[str, str]:
    """A watched or listened day: titles and channels the platform gave, and nobody's note."""
    return _no_links(body), ""


def _substack_day(fm: dict, body: str, _pages: dict) -> tuple[str, str]:
    """A reading-history day is public only from Substack's list; one from this Mac's trace holds any page on any site."""
    if str(fm.get("origin") or "") != "substack-history":
        return "", body or ""
    return _no_links(body), ""


def _starred(fm: dict, body: str, pages: dict) -> tuple[str, str]:
    """A repository the person starred, when its page says it is public: another's words. One they own is theirs."""
    page = pages.get(str(fm.get("media_entity_id") or "")) or {}
    block = page.get("github") if isinstance(page.get("github"), dict) else {}
    if str(fm.get("origin") or "") != "github-starred" or block.get("private") is not False:
        return "", body or ""
    return _saved_link(fm, body, pages)


#: Each writer whose episodes hold public content, and which of its words those are. A new writer starts private.
WRITERS = {
    "url": _saved_link, "bookmark": _saved_link, "youtube": _saved_link, "video": _saved_link,   # media_ingestor
    "repository": _starred,                                                                      # github_repos
    "page-read": _page_read,                                                                     # page_read
    "video-watch": _quotes("video ["),                                                           # watch_record
    "watch-history": _day_of_rows, "watch-history-month": _day_of_rows,                          # watch_history
    "listening-history": _day_of_rows,                                                           # listening_history
    "reading-history": _substack_day,                                                            # substack_reads
}


def public_part(fm: dict, body: str, pages: dict | None = None) -> tuple[str, str]:
    """``(the item's own words, everything else)`` of one episode. Unknown source: all of it private."""
    source = str((fm or {}).get("source") or "").strip().lower()
    reader = WRITERS.get(source)
    if reader is None:
        return "", body or ""
    return reader(fm or {}, body or "", pages or {})


# ------------------------------------------------------------------------------------------------ the guard


@dataclass
class NameGuard:
    #: Each tied name as its set of folded words.
    ties: list[frozenset[str]] = field(default_factory=list)
    tie_words: frozenset[str] = frozenset()
    #: Each tied name with its spaces out, in both orders: "b e a" or "beaexample" is still the name.
    compact: frozenset[str] = frozenset()
    #: Owner's projects: only the whole phrase blocks, since a project's words are often ordinary ones.
    phrases: frozenset[str] = frozenset()
    #: Words the record writes as names: capitalised at least as often as not, a handle's shape, an @mention, a bare link.
    name_like: frozenset[str] = frozenset()
    #: The ties a link is asked about: whole names and one-part cards, never one word of a two-part name.
    url_ties: list[frozenset[str]] = field(default_factory=list)
    url_compact: frozenset[str] = frozenset()
    built_at: float = 0.0
    _db: sqlite3.Connection | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _said(self, table: str, gram: str) -> bool:
        """Is this phrase in that table? A query the index cannot answer counts as said: err toward blocking."""
        if self._db is None:
            return table == "private"
        try:
            with self._lock:
                return self._db.execute(f"SELECT 1 FROM {table} WHERE {table} MATCH ? LIMIT 1",  # noqa: S608 — two literals
                                        (f'"{gram}"',)).fetchone() is not None
        except sqlite3.Error:
            return table == "private"

    def _private_only(self, tokens: list[str]) -> bool:
        """Said privately in some order of these words, and publicly in none."""
        orders = {" ".join(p) for p in itertools.permutations(tokens)}
        return any(self._said("private", g) for g in orders) and not any(self._said("public", g) for g in orders)

    def in_public(self, name: str) -> bool:
        """Is this whole name said, in either word order, in public content?"""
        tokens = _indexed(name).split()
        if not tokens:
            return False
        return any(self._said("public", g) for g in {" ".join(tokens), " ".join(reversed(tokens))})

    def tied(self, name: str) -> bool:
        tokens = frozenset(_indexed(name).split())
        return bool(tokens) and any(tie <= tokens or tokens <= tie for tie in self.ties)

    def clears(self, name: str) -> str | None:
        """May this name be a query's subject? ``None``, or why not: ``tie`` (a card, a connection, a correspondent, a
        known person), ``not_public`` (no public content says it)."""
        if self.tied(name):
            return "tie"
        if not self.in_public(name):
            return "not_public"
        return None

    def _name_shaped(self, word: str, capitalised: bool) -> bool:
        return capitalised or word in self.name_like or _handle_shaped(word)

    def _private_name(self, tokens: list[str], capitals: list[bool]) -> bool:
        """Said privately and never publicly, and shaped like a name: some word is, or all were written so, or it was said
        in a chat, where people type each other's names in lower case. Ordinary words someone used are not."""
        if not self._private_only(tokens):
            return False
        if any(self._name_shaped(w, False) for w in tokens) or all(capitals):
            return True
        return len(tokens) > 1 and any(self._said("chats", " ".join(p)) for p in itertools.permutations(tokens))

    def check(self, text: str, *, allowed: tuple[str, ...] = ()) -> str | None:
        """``None`` when this query may leave, or why not (an enum): ``shape``, ``contact_detail``, ``tie``,
        ``private_only``. ``allowed``: the names the caller already cleared with :func:`clears`."""
        raw = str(text or "")
        if _EMAIL.search(raw) or _PHONE.search(raw):
            return "contact_detail"
        tokens, caps = _cased(raw)
        if (len(raw) > MAX_QUERY_CHARS or len(tokens) > MAX_QUERY_WORDS or any(len(w) > MAX_TOKEN_CHARS for w in tokens)
                or _mixed_script(raw)):
            return "shape"
        rest = _without(tokens, allowed)
        said = [(w, c) for w, c in zip(rest, caps) if w is not None and not w.isdigit()]
        squeezed = "".join(w for w, _c in said)
        if any(c in squeezed for c in self.compact):
            return "tie"
        full = [(w, c) for w, c in said if len(w) > 1]
        if any(w in self.tie_words and w not in GENERIC for w, _c in full):
            return "tie"
        spaced = f" {' '.join(w for w, _c in full)} "
        if any(f" {p} " in spaced for p in self.phrases):
            return "tie"
        # A generic word counts only when the query itself writes it as part of a name ("Will <surname>").
        asked = [(w, c) for w, c in full if w not in GENERIC or c]
        for w, c in asked:
            if w not in GENERIC and self._name_shaped(w, c) and self._private_only([w]):
                return "private_only"
        for (a, ca), (b, cb) in itertools.combinations(asked, 2):
            if (a not in GENERIC or b not in GENERIC) and self._private_name([a, b], [ca, cb]):
                return "private_only"
        for i in range(len(asked) - 2):
            window = asked[i:i + 3]
            if any(w not in GENERIC for w, _c in window) and self._private_name([w for w, _c in window],
                                                                                 [c for _w, c in window]):
                return "private_only"
        for w, _c in asked:
            if len(w) >= MIN_SPLIT and w not in GENERIC and not self._said("public", w) and self._split_is_private(w):
                return "private_only"
        for i, (w, c) in enumerate(said):
            if len(w) == 1 and c and w.isalpha():   # "M. <surname>": a capital initial makes the name beside it stricter
                beside = [n for n, nc in said[max(0, i - 1):i + 2] if len(n) > 1 and n not in GENERIC
                          and self._name_shaped(n, nc)]
                if any(self._said("private", n) for n in beside):
                    return "private_only"
        return None

    def _split_is_private(self, token: str) -> bool:
        return any(self._private_name([token[:i], token[i:]], [False, False]) for i in range(2, len(token) - 1))

    def check_url(self, url: str, *, allowed: tuple[str, ...] = ()) -> str | None:
        """A link a search returned, or ``None`` when it may be opened: its host, path and query, decoded, held to ties
        only. The model did not choose it, so it carries none of the model's words. ``shape``, ``contact_detail``, ``tie``."""
        try:
            parts = urlsplit(str(url or ""))
        except ValueError:
            return "shape"
        text = unquote(" ".join([parts.hostname or "", parts.path, parts.query]))
        if _EMAIL.search(text):
            return "contact_detail"
        tokens = words(text)
        if len(tokens) > MAX_URL_WORDS:
            return "shape"
        rest = {w for w in _without(tokens, allowed) if w is not None and not w.isdigit() and len(w) > 1}
        if any(tie <= rest for tie in self.url_ties):
            return "tie"
        if any(c in w for w in rest for c in self.url_compact):
            return "tie"
        return None


def _handle_shaped(word: str) -> bool:
    """A word with letters and digits together: how an account is named, never an ordinary word."""
    return any(c.isdigit() for c in word) and any(c.isalpha() for c in word) and len(word) >= 4


def _cased(text: str) -> tuple[list[str], list[bool]]:
    """A query's folded tokens, and whether each was written with a capital."""
    tokens: list[str] = []
    caps: list[bool] = []
    for raw in _TOKEN.findall(str(text or "")):
        capital = raw[0].isupper()
        for word in words(raw):
            tokens.append(word)
            caps.append(capital)
    return tokens, caps


def _without(tokens: list[str], allowed: tuple[str, ...]) -> list[str | None]:
    """``tokens`` with each allowed name, in either order, replaced by ``None``: its words are not asked."""
    out: list[str | None] = list(tokens)
    for name in allowed:
        spelled = words(name)
        bare = [w for w in spelled if len(w) > 1]
        for order in (spelled, list(reversed(spelled)), bare, list(reversed(bare))):
            n = len(order)
            for i in range(len(out) - n + 1):
                if n and out[i:i + n] == order:
                    out[i:i + n] = [None] * n
    return out


def _outside_links(text: str) -> str:
    """Words said, not linked: a link to a post is the post. A link to a bare account is that account's handle said."""
    def keep(match: re.Match) -> str:
        url = match.group(0)
        found = person_leads.profile_handle(url)
        return f" {found[1]} " if found is not None and "/status/" not in url else " "
    return _URL.sub(keep, text or "")


def _strict_json(path: Path) -> dict | None:
    """A store's JSON: ``None`` when the file is not there, :class:`GuardUnreadable` when it is and cannot be read."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as exc:
        raise GuardUnreadable(type(exc).__name__) from exc
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise GuardUnreadable(type(exc).__name__) from exc
    if not isinstance(data, dict):
        raise GuardUnreadable("shape")
    return data


def _rows(data: dict | None, key: str) -> list[dict]:
    """A store's rows. A file that is there and holds anything else fails closed: "nothing to block" is never a guess."""
    if data is None:
        return []
    rows = data.get(key)
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        raise GuardUnreadable("shape")
    return rows


def store_names(bank: str) -> list[str]:
    """Every name the people directory holds outside the bank: the waiting cards, the contacts book (one-part names
    included) and the LinkedIn connections with the handle in each profile link."""
    names: list[str] = []
    for card in _rows(_strict_json(people_directory.path(bank, WAITING_FILE)), "cards"):
        names.append(" ".join(str(card.get(k) or "") for k in ("given_name", "family_name")))
    book = people_directory.path(bank, CONTACTS_BOOK_DIR)
    if book.exists():
        try:
            scopes = sorted(book.iterdir())
        except OSError as exc:
            raise GuardUnreadable(type(exc).__name__) from exc
        for scope in scopes:
            for card in _rows(_strict_json(scope / BOOK_FILE), "cards"):
                names.append(" ".join(str(card.get(k) or "") for k in ("given", "family")))
    for row in _rows(_strict_json(people_directory.path(bank, LINKEDIN_FILE)), "connections"):
        names.append(" ".join(str(row.get(k) or "") for k in ("first", "last")))
        found = person_leads.profile_handle(str(row.get("url") or ""))
        if found is not None:
            names.append(found[1])
    return names


def _episode_labels(fm: dict, body: str) -> list[str]:
    """Who a conversation was with, by its own record: its correspondent, its members, each speaker's label. A title is
    not one: a group's or a day's title is ordinary words, and it is read as a mention."""
    names: list[str] = []
    record = fm.get("correspondent")
    if isinstance(record, dict) and record.get("name"):
        names.append(str(record["name"]))
    for member in fm.get("participants") or []:
        if isinstance(member, dict) and member.get("name"):
            names.append(str(member["name"]))
        elif isinstance(member, str):
            names.append(member)
    names += [label.strip() for label in _SPEAKER.findall(body or "")]
    return [n for n in names if fold(n).strip() not in _NO_NAME]


def _is_page_tie(fm: dict) -> bool:
    from api.services import contacts_local, linkedin_people

    if fm.get(contacts_local.FRONTMATTER_KEY):
        return True
    for source in fm.get("sources") or []:
        if not isinstance(source, dict):
            continue
        ref = str(source.get("ref") or "")
        if ref.startswith(contacts_local.REF_SCHEME) or str(source.get("predicate") or "") == \
                linkedin_people.SOURCE_PREDICATE:
            return True
    return False


def _scan(memory_path: Path, facts) -> tuple[sqlite3.Connection, list[str], frozenset[str]]:
    """The record into an in-memory index, off the event loop: every episode, through ``bank_index``'s cached headers. An
    episode that cannot be parsed is read as private text: one bad file neither stops the feature nor lifts the limit."""
    db = sqlite3.connect(":memory:", check_same_thread=False)
    for table in ("private", "public", "chats"):
        db.execute(f"CREATE VIRTUAL TABLE {table} USING fts5(text, content='', "   # noqa: S608 — two literals
                   "tokenize='unicode61 remove_diacritics 0')")
    names: list[str] = []
    size = 0
    pages = facts.pages if isinstance(getattr(facts, "pages", None), dict) else {}
    counts: Counter = Counter()
    marked: set[str] = set()
    row = 0

    def add(said: str, own: str, labels: list[str], *, chat: bool, title: str = "") -> None:
        nonlocal row, size
        row += 1
        size += len(said) + len(own)
        if size > MAX_CORPUS_CHARS:
            raise GuardUnreadable("too_large")
        names.extend(labels)
        if said.strip():
            db.execute("INSERT INTO public(rowid, text) VALUES (?, ?)", (row, _indexed(said)))
        own = f"{title}\n{own}".strip()
        if not own:
            return
        counts.update(_TOKEN.findall(own))
        marked.update(_AT.findall(own))
        for url in _URL.findall(own):
            found = person_leads.profile_handle(url)
            if found is not None and "/status/" not in url:
                marked.add(found[1])
        text = _indexed(_outside_links(own))
        db.execute("INSERT INTO private(rowid, text) VALUES (?, ?)", (row, text))
        if chat:
            db.execute("INSERT INTO chats(rowid, text) VALUES (?, ?)", (row, text))

    episodes = memory_path / "episodes"
    try:
        on_disk = {p.name: p for p in episodes.iterdir() if p.suffix == ".md"} if episodes.is_dir() else {}
        files = bank_index.files(memory_path, "episodes") if on_disk else []
    except OSError as exc:
        raise GuardUnreadable(type(exc).__name__) from exc
    for entry in files:
        on_disk.pop(entry.path.name, None)
        fm = entry.frontmatter or {}
        source = str(fm.get("source") or "").strip().lower()
        if source in NEUTRAL_SOURCES:
            continue
        try:
            body = entry.body() or ""
        except Exception:  # noqa: BLE001 — one the index could not read: its bytes, as private text, below
            on_disk[entry.path.name] = entry.path
            continue
        said, own = public_part(fm, body, pages)
        known = source in WRITERS
        labels = [] if known else _episode_labels(fm, body)
        add(said, own, labels, chat=bool(labels) or source in CHAT_SOURCES, title="" if known else str(fm.get("title") or ""))
    for path in on_disk.values():   # could not be parsed: whatever it says, it is private
        try:
            add("", path.read_bytes().decode("utf-8", errors="replace"), [], chat=True)
        except OSError:
            continue
    db.commit()
    cased: Counter = Counter()
    lower: Counter = Counter()
    for token, n in counts.items():
        if token[0].isupper() and not token.isupper():
            for w in words(token):
                cased[w] += n
        elif token[0].islower():
            for w in words(token):
                lower[w] += n
    like = {w for w, n in cased.items() if n >= lower.get(w, 0) and len(w) > 1}
    for handle in marked:
        like.update(words(handle))
    return db, names, frozenset(like - GENERIC)


def build(memory_path: Path, facts) -> NameGuard:
    """Read the whole record, once: every episode by its writer, the people directory, the person pages. Raises
    :class:`GuardUnreadable`. A blocking scan: a caller on the event loop runs it in a thread."""
    from api.services import web_context

    memory_path = Path(memory_path)
    names = store_names(memory_path.name)
    try:
        db, labels, name_like = _scan(memory_path, facts)
    except sqlite3.Error as exc:
        raise GuardUnreadable(type(exc).__name__) from exc
    names += labels
    guard = NameGuard(built_at=time.monotonic(), _db=db, name_like=name_like)
    for page_id, fm in facts.pages.items():
        if not isinstance(fm, dict) or str(fm.get("type") or "").strip().lower() != "person":
            continue
        page_labels = [str(fm.get("name") or page_id),
                       *[str(a) for a in fm.get("aliases") or [] if isinstance(a, str)]]
        if _is_page_tie(fm) or fm.get("owner") is True or fm.get("unnamed") or fm.get("owner_roles"):
            names += page_labels
            continue
        kept = [label for label in page_labels if not guard.in_public(label)]
        names += kept
        if len(kept) < len(page_labels):
            page = web_context.load_page(memory_path, page_id)
            if page is None or web_context.known_personally(memory_path, page, facts):
                names += page_labels
    names += [str(n) for n in facts.pending_person_names]
    url_ties = {frozenset(_ties_of(n)) for n in names} - {frozenset()}
    guard.url_ties = sorted(url_ties, key=sorted)
    guard.url_compact = frozenset(c for n in names for c in _compact_forms(n) if len(c) >= MIN_COMPACT)
    names += [str(n) for n in facts.owner_names]   # each part of the owner's name: never in a query, but ordinary in a path
    ties = {frozenset(_ties_of(n)) for n in names} - {frozenset()}
    guard.ties = sorted(ties, key=sorted)
    guard.tie_words = frozenset(w for tie in ties for w in tie if w not in GENERIC)
    guard.compact = frozenset(c for n in names for c in _compact_forms(n) if len(c) >= MIN_COMPACT)
    guard.phrases = frozenset(_indexed(p) for p in facts.project_titles if _indexed(p))
    return guard


def _ties_of(name: str) -> list[str]:
    """A name's words. Never a year or a number: those are nobody's name."""
    return [w for w in words(name) if len(w) > 1 and not w.isdigit()]


def _compact_forms(name: str) -> tuple[str, ...]:
    tokens = _ties_of(name)
    return ("".join(tokens), "".join(reversed(tokens)))


_HELD: dict[str, tuple[tuple, NameGuard]] = {}


def _stamp(memory_path: Path) -> tuple:
    out: list[int] = []
    folder = people_directory.folder(Path(memory_path).name)
    paths = [Path(memory_path) / "episodes", Path(memory_path) / "entities", folder]
    try:
        if folder.is_dir():
            paths += sorted(folder.iterdir())
            book = folder / CONTACTS_BOOK_DIR
            if book.is_dir():
                paths += sorted(book.iterdir())
    except OSError as exc:
        raise GuardUnreadable(type(exc).__name__) from exc
    for path in paths:
        try:
            out.append(path.stat().st_mtime_ns)
        except OSError:
            out.append(0)
    return tuple(out)


def guard_for(memory_path: Path, facts) -> NameGuard:
    """The bank's guard, reused while the record has not changed. Raises :class:`GuardUnreadable`. Blocking: run it off
    the event loop, and never under write admission."""
    key = str(Path(memory_path))
    stamp = _stamp(memory_path)
    held = _HELD.get(key)
    if held is not None and held[0] == stamp and time.monotonic() - held[1].built_at < KEEP_S:
        return held[1]
    _HELD.clear()   # one bank's index in memory at most
    guard = build(memory_path, facts)
    _HELD[key] = (stamp, guard)
    return guard


def release() -> None:
    """Drop what the guard holds: a scan of the record is not kept past the step that needed it."""
    _HELD.clear()
