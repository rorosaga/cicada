"""What may leave in a web search or an opened link: never the name of someone known only from the person's own record
(ruling 54, owner correction 2026-11-04).

The owner: reading the person's chats and contacts is fine, it stays between Cicada and the plan's model. "The one limit
is on what leaves in a web search": no query may contain the name of someone known only from the chats or contacts. So
this module does not decide who may be read; it decides, in code, on every query a model writes and every link it
would open, whether the words may go out. It sends nothing and writes nothing.

**A tie blocks always; a mention blocks unless the public record has it too.** One name can be both, so the guard asks
two different questions:

* **A tie** — the person has this one in their life on the record: a Contacts card (the waiting set, the contacts book,
  a page carrying a card's source or photo), a LinkedIn connection, a chat's correspondent, a group member, a speaker
  label in a chat or a meeting, a chat's title, a page the record says the person knows (``web_context.known_personally``),
  a person page or held name the public record never says, the owner's own names and projects. A friend who wrote a
  blog post the person saved is still a friend: **public content never clears a tie.** One-part names are ties too, and a
  name matches in either word order and when one holds the other ("Bea" against "Bea Example"; never two full names
  that only share a first name).
* **A mention** — the words were said somewhere private (any episode that is not public content: chats, meetings,
  notes, calendar, harness sessions, and any source this module does not know, so a new writer starts private). They
  pass only if the same words are also said in **public content the person read or saved** (:data:`PUBLIC_SOURCES`):
  a public figure the person also talked about is not blocked for that, a neighbour named only in a chat is. The
  person's own note on a saved link is theirs, not the public content's: it counts as private. Every run of one, two
  or three words is asked, so a public first name cannot carry a private full name past the guard.

A word in :data:`GENERIC` ("github", "blog", "site") says nothing about anyone and is never asked. The question's own
cleared name and handle are taken out of a query first (:func:`NameGuard.check` ``allowed``), so a contact called Simon
does not block a search for an unrelated, cleared "Simon Willison" — while "Simon" alone with anything else is.

**Fail closed, for what leaves only.** A store that exists and cannot be read raises :class:`GuardUnreadable`: nothing
is searched and nothing found by a search is opened. A store that does not exist is empty.

**Blocked means dropped.** The caller drops the query, counts it against the budget and never rewrites it; the reason is
an enum, and neither a query nor a name is logged.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlsplit

from api.services import markdown_parser, people_directory, person_leads, text_fold

#: Conversations that ARE public content the person read or saved (an episode's ``source``).
PUBLIC_SOURCES = frozenset({
    "youtube", "watch-history", "watch-history-month", "video-watch", "bookmark", "url", "link", "media", "tab-group",
    "reading-history", "page-read", "listening-history", "arxiv", "crossref", "github",
})
#: Cicada's own records of what it looked up: neither the person's life nor something the person read.
NEUTRAL_SOURCES = frozenset({"web-check", "source-check", "source-refresh"})
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
MIN_COMPACT = 5
#: The guard held between two calls in one run: rebuilt when the record changes, dropped by :func:`release`.
KEEP_S = 300.0

GENERIC = frozenset(text_fold.SUBJECT_STOPWORDS) | frozenset("""
github gitlab twitter x instagram linkedin mastodon bluesky threads youtube reddit substack medium hackernews
website site homepage home page personal blog about bio biography profile account accounts handle handles username
usernames user users official real name names who is verified talk talks interview podcast paper papers code repo
com org net dev io co ai app me www http https html htm php en es wiki wikipedia wikidata blog posts post
""".split())

_URL = re.compile(r"https?://[^\s)>\]\"']+")
_LINK = re.compile(r"^(?:\[.*?\]\s*)?user:", re.IGNORECASE)
_SPEAKER = re.compile(r"^speaker:([^:\n]{1,120}):", re.MULTILINE)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"(?<!\d)(?:\+?\d[\s().-]?){7,}(?!\d)")


class GuardUnreadable(Exception):
    """A store the guard must read could not be read: nothing leaves."""


def _words(text) -> list[str]:
    return text_fold.words(str(text or ""))


def _spaced(words: list[str]) -> str:
    return f" {' '.join(words)} " if words else ""


@dataclass
class NameGuard:
    #: Each tied name as its set of folded words.
    ties: list[frozenset[str]] = field(default_factory=list)
    tie_words: frozenset[str] = frozenset()
    #: Each tied name with its spaces out, in both orders: "b e a" or "beaexample" is still the name.
    compact: frozenset[str] = frozenset()
    private: str = ""
    public: str = ""
    built_at: float = 0.0

    def said_privately_only(self, gram: str) -> bool:
        needle = f" {gram} "
        return needle in self.private and needle not in self.public

    def in_public(self, name: str) -> bool:
        """Is this whole name said, in either word order, in public content the person read or saved?"""
        words = _words(name)
        if not words:
            return False
        orders = {" ".join(words), " ".join(reversed(words))}
        return any(f" {order} " in self.public for order in orders)

    def tied(self, name: str) -> bool:
        words = frozenset(_words(name))
        return bool(words) and any(tie <= words or words <= tie for tie in self.ties)

    def clears(self, name: str) -> str | None:
        """May this name be a query's subject? ``None``, or why not: ``tie`` (a card, a connection, a correspondent, a
        known person), ``not_public`` (no public content the person read or saved says it)."""
        if self.tied(name):
            return "tie"
        if not self.in_public(name):
            return "not_public"
        return None

    def check(self, text: str, *, allowed: tuple[str, ...] = (), url: bool = False) -> str | None:
        """``None`` when ``text`` may leave, or why not (an enum): ``shape``, ``contact_detail``, ``tie``,
        ``private_only``. ``allowed``: the names the caller already cleared with :func:`clears`."""
        raw = str(text or "")
        if _EMAIL.search(raw) or (not url and _PHONE.search(raw)):
            return "contact_detail"
        words = _words(raw)
        if not url and (len(raw) > MAX_QUERY_CHARS or len(words) > MAX_QUERY_WORDS
                        or any(len(w) > MAX_TOKEN_CHARS for w in words)):
            return "shape"
        rest = _without(words, allowed)
        kept = [w for w in rest if w is not None and w not in GENERIC and not (url and w.isdigit())]
        if any(w in self.tie_words for w in kept):
            return "tie"
        squeezed = "".join(w for w in rest if w is not None)
        if any(c in squeezed for c in self.compact):
            return "tie"
        for run in _runs(rest):
            for n in (1, 2, 3):
                for i in range(len(run) - n + 1):
                    gram = run[i:i + n]
                    if n == 1 and gram[0] in GENERIC:
                        continue
                    if self.said_privately_only(" ".join(gram)):
                        return "private_only"
        return None

    def check_url(self, url: str, *, allowed: tuple[str, ...] = ()) -> str | None:
        """A link carries words too: its host, path and query, decoded, under the same rule."""
        try:
            parts = urlsplit(str(url or ""))
        except ValueError:
            return "shape"
        return self.check(unquote(" ".join([parts.hostname or "", parts.path, parts.query])), allowed=allowed, url=True)


def _without(words: list[str], allowed: tuple[str, ...]) -> list[str | None]:
    """``words`` with each allowed name, in either order, replaced by ``None`` (a break: no run crosses it)."""
    out: list[str | None] = list(words)
    for name in allowed:
        spelled = _words(name)
        for order in (spelled, list(reversed(spelled))):
            n = len(order)
            for i in range(len(out) - n + 1):
                if n and out[i:i + n] == order:
                    out[i:i + n] = [None] * n
    return out


def _runs(words: list[str | None]) -> list[list[str]]:
    runs: list[list[str]] = [[]]
    for word in words:
        if word is None:
            runs.append([])
        else:
            runs[-1].append(word)
    return [r for r in runs if r]


def _outside_links(text: str) -> str:
    """Words said, not linked: a link to a post is the post. A link to a bare account is that account's handle said."""
    def keep(match: re.Match) -> str:
        url = match.group(0)
        found = person_leads.profile_handle(url)
        return f" {found[1]} " if found is not None and "/status/" not in url else " "
    return _URL.sub(keep, text or "")


def _public_words(text: str) -> tuple[str, str]:
    """``(public, private)``: of a saved item's text, what the item says and what the person wrote on it. Their own
    ``user:`` line counts as private; the links in it are the item's."""
    public, private = [], []
    for line in (text or "").splitlines():
        if _LINK.match(line):
            private.append(_outside_links(line))
            public.extend(_URL.findall(line))
        else:
            public.append(line)
    return "\n".join(public), "\n".join(private)


def _strict_json(path: Path) -> dict:
    """A store's JSON: empty when the file is not there, :class:`GuardUnreadable` when it is and cannot be read."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise GuardUnreadable(type(exc).__name__) from exc
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise GuardUnreadable(type(exc).__name__) from exc
    if not isinstance(data, dict):
        raise GuardUnreadable("shape")
    return data


def _rows(data: dict, key: str) -> list[dict]:
    rows = data.get(key)
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise GuardUnreadable("shape")
    return [r for r in rows if isinstance(r, dict)]


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
            for key in ("cards", "contacts"):
                for card in _rows(_strict_json(scope / BOOK_FILE), key):
                    names.append(" ".join(str(card.get(k) or "") for k in ("given", "family")))
    for row in _rows(_strict_json(people_directory.path(bank, LINKEDIN_FILE)), "connections"):
        names.append(" ".join(str(row.get(k) or "") for k in ("first", "last")))
        found = person_leads.profile_handle(str(row.get("url") or ""))
        if found is not None:
            names.append(found[1])
    return names


def _episode_labels(fm: dict, body: str) -> list[str]:
    """Who a conversation was with, by its own record: its correspondent, its members, each speaker's label, and the
    title of a conversation that has any of those."""
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
    if names and fm.get("title"):
        names.append(str(fm["title"]))
    return names


_CHAT_WORDS = frozenset("""
telegram whatsapp messages imessage message chat chats with group meeting call transcript and the contact member speaker
""".split())


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


def build(memory_path: Path, facts) -> NameGuard:
    """Read the whole record, once: every episode by its source, the people directory, the person pages. Raises
    :class:`GuardUnreadable`."""
    from api.services import web_context

    memory_path = Path(memory_path)
    names = store_names(memory_path.name)
    private: list[str] = []
    public: list[str] = []
    size = 0
    try:
        files = list((memory_path / "episodes").glob("*.md")) if (memory_path / "episodes").is_dir() else []
    except OSError as exc:
        raise GuardUnreadable(type(exc).__name__) from exc
    for path in files:
        try:
            parsed = markdown_parser.parse(path)
        except Exception as exc:  # noqa: BLE001 — an episode the guard cannot read could hold any name
            raise GuardUnreadable(type(exc).__name__) from exc
        fm, body = parsed.frontmatter, parsed.body or ""
        source = str(fm.get("source") or "").strip().lower()
        if source in NEUTRAL_SOURCES:
            continue
        size += len(body)
        if size > MAX_CORPUS_CHARS:
            raise GuardUnreadable("too_large")
        if source in PUBLIC_SOURCES:
            said, own = _public_words(body)
            public.append(_spaced(_words(f"{fm.get('title') or ''}\n{said}")))
            if own.strip():
                private.append(_spaced(_words(own)))
        else:
            names += _episode_labels(fm, body)
            private.append(_spaced(_words(f"{fm.get('title') or ''}\n{_outside_links(body)}")))
    guard = NameGuard(private="\x00".join(private), public="\x00".join(public), built_at=time.monotonic())
    for page_id, fm in facts.pages.items():
        if not isinstance(fm, dict) or str(fm.get("type") or "").strip().lower() != "person":
            continue
        labels = [str(fm.get("name") or page_id), *[str(a) for a in fm.get("aliases") or [] if isinstance(a, str)]]
        if _is_page_tie(fm):
            names += labels
            continue
        if fm.get("owner") is True or fm.get("unnamed") or fm.get("owner_roles"):
            names += labels
            continue
        kept = [label for label in labels if not guard.in_public(label)]
        names += kept
        if len(kept) < len(labels):
            page = web_context.load_page(memory_path, page_id)
            if page is None or web_context.known_personally(memory_path, page, facts):
                names += labels
    names += [str(n) for n in facts.pending_person_names]
    names += [str(n) for n in facts.owner_names]
    names += [str(n) for n in facts.project_titles]
    ties = {frozenset(w for w in _words(n) if w not in _CHAT_WORDS) for n in names}
    ties.discard(frozenset())
    guard.ties = sorted(ties, key=sorted)
    guard.tie_words = frozenset(w for tie in ties for w in tie if w not in GENERIC)
    guard.compact = frozenset(c for n in names for c in _compact_forms(n) if len(c) >= MIN_COMPACT)
    return guard


def _compact_forms(name: str) -> tuple[str, ...]:
    words = [w for w in _words(name) if w not in _CHAT_WORDS]
    return ("".join(words), "".join(reversed(words)))


_HELD: dict[str, tuple[tuple, NameGuard]] = {}


def _stamp(memory_path: Path) -> tuple:
    out: list[int] = []
    folder = people_directory.folder(Path(memory_path).name)
    paths = [Path(memory_path) / "episodes", Path(memory_path) / "entities", folder]
    if folder.is_dir():
        paths += sorted(folder.iterdir())
    for path in paths:
        try:
            out.append(path.stat().st_mtime_ns)
        except OSError:
            out.append(0)
    return tuple(out)


def guard_for(memory_path: Path, facts) -> NameGuard:
    """The bank's guard, reused while the record has not changed. Raises :class:`GuardUnreadable`."""
    key = str(Path(memory_path))
    stamp = _stamp(memory_path)
    held = _HELD.get(key)
    if held is not None and held[0] == stamp and time.monotonic() - held[1].built_at < KEEP_S:
        return held[1]
    _HELD.clear()   # one bank's text in memory at most
    guard = build(memory_path, facts)
    _HELD[key] = (stamp, guard)
    return guard


def release() -> None:
    """Drop what the guard holds: a scan of the record is not kept past the step that needed it."""
    _HELD.clear()

