"""What a Substack link is (G89, owner 2026-11-04) — pure, no fetch, no model.

Substack gives a reader no API, no reader export and no Mac app (researched 2026-11-04, G89): the person's saved posts,
reading history and subscriptions come in through their own agent in their own signed-in browser
(``substack_lists``), and a publication's posts through its public feed (``feed_registry``). Both need to know what a
Substack link names, the same way every door that meets one:

* :func:`post` — one post, as ``(canonical url, other spellings)``: ``<pub>.substack.com/p/<slug>`` (the shape a
  publication's feed links to, so a post the feed already brought in is the same ``url_index`` row), the reader's
  ``open.substack.com/pub/<pub>/p/<slug>``, the app's ``substack.com/home/post/p-<id>`` and a profile's
  ``substack.com/@<handle>/p-<id>``, and a publication on its own domain (``<host>/p/<slug>``).
* :func:`publication` — the publication a link belongs to, as ``(home, feed url)``: ``https://<pub>.substack.com`` and
  its ``/feed``, or a publication on its own domain and its ``/feed`` (where Substack serves it). A profile
  (``substack.com/@<handle>``) is a person, not a publication: ``None``.
* :func:`is_paywall_stub` — a paid post's feed body: full metadata, a few words and a "Read more" link (G89, measured
  2026-09-01: ~142 bytes). It is not the post, so it never stands in for one.
"""
from __future__ import annotations

import html
import re
from urllib.parse import urlparse

ROOT = "substack.com"
#: ``*.substack.com`` hosts that are Substack's own, never a publication.
_RESERVED = frozenset({"www", "open", "mcp", "support", "api", "cdn", "email", "on-demand"})
_SUB = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62})$")
_SLUG = r"[A-Za-z0-9][A-Za-z0-9_-]{0,240}"
_POST_PATH = re.compile(rf"^/p/(?P<slug>{_SLUG})/?$")
_OPEN_POST = re.compile(rf"^/pub/(?P<sub>[a-z0-9-]{{1,63}})/p/(?P<slug>{_SLUG})/?$", re.IGNORECASE)
_OPEN_PUB = re.compile(r"^/pub/(?P<sub>[a-z0-9-]{1,63})(?:/.*)?$", re.IGNORECASE)
_APP_POST = re.compile(r"^/home/post/p-(?P<id>\d{1,20})/?$")
_PROFILE_POST = re.compile(r"^/@(?P<handle>[A-Za-z0-9_.-]{1,64})/p-(?P<id>\d{1,20})/?$")
_HOST = re.compile(r"^(?=.{4,253}$)[a-z0-9](?:[a-z0-9-]{0,62})(?:\.[a-z0-9](?:[a-z0-9-]{0,62}))+$")


def _parse(url) -> tuple[str, str] | None:
    raw = str(url or "").strip()
    if not raw:
        return None
    try:
        parsed = urlparse(raw if "://" in raw else "https://" + raw)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https"):
        return None
    host = (parsed.hostname or "").lower().rstrip(".")
    if not _HOST.match(host):
        return None
    return host, parsed.path or "/"


def _subdomain(host: str) -> str | None:
    """``<pub>`` for ``<pub>.substack.com``, else ``None`` (Substack's own hosts included)."""
    if not host.endswith("." + ROOT):
        return None
    sub = host[: -len(ROOT) - 1]
    if "." in sub or sub in _RESERVED or not _SUB.match(sub):
        return None
    return sub


def is_substack_host(host: str) -> bool:
    host = (host or "").lower()
    return host == ROOT or host.endswith("." + ROOT)


def post(url) -> tuple[str, tuple[str, ...]] | None:
    """``(canonical url, aliases)`` for one Substack post, or ``None`` when the link is not one (a publication's home,
    a profile, a Note, another site's page that is not ``/p/<slug>``)."""
    found = _parse(url)
    if found is None:
        return None
    host, path = found
    if host in (ROOT, "www." + ROOT):
        if m := _APP_POST.match(path):
            return f"https://{ROOT}/home/post/p-{m.group('id')}", ()
        if m := _PROFILE_POST.match(path):
            canonical = f"https://{ROOT}/home/post/p-{m.group('id')}"
            return canonical, (f"https://{ROOT}/@{m.group('handle')}/p-{m.group('id')}",)
        return None
    if host == "open." + ROOT:
        if m := _OPEN_POST.match(path):
            sub = m.group("sub").lower()
            if sub in _RESERVED:
                return None
            return (f"https://{sub}.{ROOT}/p/{m.group('slug')}",
                    (f"https://open.{ROOT}/pub/{sub}/p/{m.group('slug')}",))
        return None
    m = _POST_PATH.match(path)
    if m is None:
        return None
    if is_substack_host(host) and _subdomain(host) is None:
        return None
    # A publication on its own domain serves its posts at /p/<slug>, as on substack.com.
    return f"https://{host}/p/{m.group('slug')}", ()


def publication(url) -> tuple[str, str] | None:
    """``(home, feed url)`` of the publication a link belongs to, or ``None`` (a profile, Substack's own pages, a link
    that is not http(s))."""
    found = _parse(url)
    if found is None:
        return None
    host, path = found
    if host == "open." + ROOT:
        m = _OPEN_PUB.match(path)
        sub = m.group("sub").lower() if m else ""
        if not sub or sub in _RESERVED or not _SUB.match(sub):
            return None
        host = f"{sub}.{ROOT}"
    elif is_substack_host(host):
        if _subdomain(host) is None:
            return None
    home = f"https://{host}"
    return home, home + "/feed"


_TAG = re.compile(r"<[^>]+>")
_READ_MORE = re.compile(r"<a\b[^>]*>\s*(?:read more|keep reading|continue reading)\s*(?:→|&rarr;|»)?\s*</a>",
                        re.IGNORECASE)
#: A paid post's stub is a sentence or two; a free post's body runs to thousands of characters.
STUB_TEXT_MAX = 400


def is_paywall_stub(body: str | None) -> bool:
    """A feed body that is a paid post's stub: a "Read more" link and almost no words (G89 (vii))."""
    text = str(body or "")
    if not text or not _READ_MORE.search(text):
        return False
    words = " ".join(html.unescape(_TAG.sub(" ", text)).split())
    return len(words) <= STUB_TEXT_MAX
