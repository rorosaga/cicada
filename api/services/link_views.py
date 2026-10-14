"""How a link on a page is drawn: the view word in a standard markdown link title (owner rulings, 2026-10-14).

The grammar is research-hub's, extended. A view is the **CommonMark link title**, so the line stays a working link in
git, GitHub, Obsidian and every other markdown reader::

    [label](URL)                          link        (Sleep's default; an agent's too)
    <URL>   or a bare URL                 raw
    [label](URL "raw")                    raw
    [label](URL "mention")                mention     (site · title, inline)
    [label](URL "bookmark")               bookmark    (a card: alone on its line)
    [label](URL "screenshot")             screenshot  the newest capture of the page
    [label](URL "screenshot 2026-10-14")  screenshot  the capture from that day (else the nearest earlier, in words)
    [label](URL "captures")               captures    every capture, oldest to newest
    [label](URL "look")                   look        the newest saved look (G196) of this URL
    [label](URL "look 2026-10-14")        look        the one saved that day
    [label](URL "embed")                  embed       research-hub's word: a screenshot of a website

The rules (one table, two sides — ``Views/Common/LinkView.swift`` is this module's twin, and both read
``api/tests/fixtures/link_views.json``, the way ``video_urls.json`` pins ``VideoRef``):

* The title is ``<view>`` or ``<view> <yyyy-mm-dd>``, lower case, exact. A date only goes with ``screenshot`` and
  ``look`` (it pins a moment: "how it looked when we decided this"). Any other title is a real tooltip and means
  **link**. Nothing guesses.
* A block view (bookmark, screenshot, captures, look, embed) is a block only when the link stands alone on its line —
  after an optional list marker, and optionally followed by a `` — note`` (a ``## Links`` bullet). Anywhere else, in
  a sentence, it draws as a **mention** (research-hub's fallback, ``link-ref.ts``).
* The label is the title. A label equal to the URL means the page has no title of its own; the renderer shows the one
  Cicada knows and never writes it back.
* Sleep writes plain links; context decides how a plain link is drawn (inside a sentence: link; a ``## Links``
  bullet: mention; a bare URL: raw). An agent writes a view word only when it means one, and the person's switch is a
  pinned page edit under their name (G198).

Every text exit (recall, an excerpt, an export) passes prose through :func:`plain` so a quote never shows
``"bookmark"``. Pure: no I/O, no network.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

#: Inline views: they sit inside a sentence.
INLINE_VIEWS = ("link", "raw", "mention")
#: Block views: each needs a line to itself.
BLOCK_VIEWS = ("bookmark", "screenshot", "captures", "look", "embed")
VIEWS = INLINE_VIEWS + BLOCK_VIEWS
#: The views a date may pin.
DATED_VIEWS = ("screenshot", "look")
#: What the person's switcher offers, in order (``embed`` and ``raw`` are accepted, never offered).
SWITCHER_VIEWS = ("link", "mention", "bookmark", "screenshot", "captures", "look")

_TITLE = re.compile(r"^(?P<view>[a-z]+)(?: (?P<day>\d{4}-\d{2}-\d{2}))?$")
#: A markdown link that is not an image: ``[label](url)`` or ``[label](url "title")`` / ``'title'``. The label may
#: hold backslash escapes; the URL is http(s), optionally in angle brackets.
#: A link's URL: no space or angle bracket, and parentheses only balanced, one level deep — CommonMark's rule, so
#: ``https://en.wikipedia.org/wiki/Foo_(bar)`` is one URL and the link's own ``)`` still closes it.
URL = r"https?://(?:[^\s()<>]|\([^\s()<>]*\))+"
LINK = re.compile(
    r"(?<!!)\[(?P<label>(?:\\.|[^\[\]\\])*)\]"
    r"\(\s*(?:<(?P<aurl>https?://[^\s<>]+)>|(?P<url>" + URL + r"))"
    r"(?:\s+(?:\"(?P<dq>[^\"]*)\"|'(?P<sq>[^']*)'))?\s*\)"
)
#: The ``(url)`` / ``(url "title")`` half of a link, the URL as group 1 — for a parser that keeps its own groups
#: (``entity_body``'s ``## Links`` dedup, ``page_sources``, ``site_sources``), so a titled link is never dropped.
LINK_TAIL = r"\(\s*<?(" + URL + r")>?(?:\s+(?:\"[^\"]*\"|'[^']*'))?\s*\)"
#: ``<https://…>`` — CommonMark's autolink.
AUTOLINK = re.compile(r"<(?P<url>https?://[^\s<>]+)>")
#: A bare URL in prose (not inside a link, an image, an autolink or code — :func:`links_in` masks those first), so a
#: URL in parentheses is still one: ``(https://example.com/x)``.
BARE = re.compile(r"(?<![\w<\"'=/])(?P<url>https?://[^\s<>\"'`\]]+)")
#: ``![alt](url …)`` — masked before bare URLs are read: an image is not a link.
IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_BARE_TRAIL = ".,;:!?)'\""
_ITEM = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+")
_NOTE = re.compile(r"^\s+[—–-]\s+")
_CODE = re.compile(r"`+[^`]*`+")


@dataclass(frozen=True)
class Title:
    view: str
    day: str | None = None


@dataclass(frozen=True)
class LinkRef:
    """One link in a line: where it is, what it says, and how it asks to be drawn."""
    label: str
    url: str
    view: str            # the view as drawn here (a block view out of place is "mention")
    asked: str           # the view the markdown names ("link" for no title or a plain tooltip)
    day: str | None
    block: bool          # alone on its line, so a block view draws as a block
    start: int
    end: int
    markdown: str        # the exact token, for an edit's ``old``

    def to_dict(self) -> dict:
        return asdict(self)


def parse_title(title: str | None) -> Title | None:
    """The view a link title names, or None when the title is a plain tooltip (or there is none)."""
    if title is None:
        return None
    m = _TITLE.match(title)
    if m is None or m.group("view") not in VIEWS:
        return None
    day = m.group("day")
    if day is not None and m.group("view") not in DATED_VIEWS:
        return None
    if day is not None and not _valid_day(day):
        return None
    return Title(m.group("view"), day)


def _valid_day(day: str) -> bool:
    from datetime import date

    try:
        date.fromisoformat(day)
    except ValueError:
        return False
    return True


def title_for(view: str, day: str | None = None) -> str | None:
    """The link title that asks for ``view`` (None for a plain link). Raises ValueError for a view that is not one."""
    if view not in VIEWS:
        raise ValueError(f"'{view}' is not a link view; the views are: {', '.join(VIEWS)}.")
    if view == "link":
        return None
    if day is not None:
        if view not in DATED_VIEWS or not _valid_day(day):
            raise ValueError(f"a date goes only with {' or '.join(DATED_VIEWS)}, as yyyy-mm-dd.")
        return f"{view} {day}"
    return view


def escape_label(label: str) -> str:
    """research-hub's escaping: ``[``, ``]`` and ``\\`` in a label are backslash-escaped."""
    return re.sub(r"([\[\]\\])", r"\\\1", label or "")


def unescape_label(label: str) -> str:
    return re.sub(r"\\([\[\]\\])", r"\1", label or "")


def escape_url(url: str) -> str:
    """A space, ``"``, ``<`` or ``>`` in a URL is percent-encoded."""
    return (url or "").replace(" ", "%20").replace('"', "%22").replace("<", "%3C").replace(">", "%3E")


def markdown(label: str, url: str, view: str = "link", day: str | None = None) -> str:
    """The token for ``label``/``url`` drawn as ``view``: ``[label](url)`` or ``[label](url "view")``."""
    title = title_for(view, day)
    head = f"[{escape_label(label)}]({escape_url(url)}"
    return f'{head} "{title}")' if title else f"{head})"


def _is_block(line: str, start: int, end: int) -> bool:
    before = line[:start]
    if before.strip() and not (_ITEM.match(before) and _ITEM.match(before).end() == len(before)):
        return False
    after = line[end:]
    return not after.strip() or bool(_NOTE.match(after))


def _masked(line: str) -> str:
    """``line`` with inline code spans blanked (same length), so nothing inside code reads as a link."""
    return _CODE.sub(lambda m: " " * len(m.group(0)), line)


def links_in(line: str) -> list[LinkRef]:
    """Every link in ONE line, in order: titled and plain markdown links, autolinks and bare URLs (``raw``)."""
    text = _masked(line or "")
    found: list[LinkRef] = []
    taken: list[tuple[int, int]] = []
    for m in LINK.finditer(text):
        title = m.group("dq") if m.group("dq") is not None else m.group("sq")
        parsed = parse_title(title)
        asked = parsed.view if parsed else "link"
        block = _is_block(text, m.start(), m.end())
        view = asked if asked in INLINE_VIEWS or block else "mention"
        found.append(LinkRef(unescape_label(m.group("label")), m.group("aurl") or m.group("url"), view, asked,
                             parsed.day if parsed else None, block, m.start(), m.end(), line[m.start():m.end()]))
        taken.append(m.span())
    rest = IMAGE.sub(lambda m: " " * len(m.group(0)), text)
    for start, end in taken:
        rest = rest[:start] + " " * (end - start) + rest[end:]
    for m in AUTOLINK.finditer(rest):
        found.append(LinkRef(m.group("url"), m.group("url"), "raw", "raw", None, _is_block(rest, *m.span()),
                             m.start(), m.end(), line[m.start():m.end()]))
        rest = rest[:m.start()] + " " * (m.end() - m.start()) + rest[m.end():]
    for m in BARE.finditer(rest):
        url = trim_bare(m.group("url"))
        if "://" not in url or len(url) <= len("https://"):
            continue
        end = m.start() + len(url)
        found.append(LinkRef(url, url, "raw", "raw", None, _is_block(rest, m.start(), end), m.start(), end, url))
    return sorted(found, key=lambda r: r.start)


def trim_bare(url: str) -> str:
    """A bare URL without the sentence's trailing punctuation — a closing ``)`` only when it closes nothing in the URL
    (``(see https://example.com/x)`` vs ``https://en.wikipedia.org/wiki/Foo_(bar)``)."""
    while url and url[-1] in _BARE_TRAIL:
        if url[-1] == ")" and url.count("(") >= url.count(")"):
            break
        url = url[:-1]
    return url


def plain(text: str) -> str:
    """``text`` with every view word dropped: ``[T](u "bookmark")`` → ``[T](u)``. A real tooltip is kept. What every
    text exit serves, so a quote or a recall never shows a view word."""
    if not text or "](" not in text:
        return text

    def keep(m: re.Match) -> str:
        title = m.group("dq") if m.group("dq") is not None else m.group("sq")
        if parse_title(title) is None:
            return m.group(0)
        url = m.group("aurl") or m.group("url")
        return f"[{m.group('label')}]({url})"

    return LINK.sub(keep, text)


def display(url: str) -> str:
    """The raw view's words: the URL with its scheme and ``www.`` gone and no trailing slash."""
    out = re.sub(r"^https?://", "", url or "")
    out = out[4:] if out.startswith("www.") else out
    return out.rstrip("/")
