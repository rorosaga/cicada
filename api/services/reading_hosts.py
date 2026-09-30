"""The closed host sets for reading the web (G166, spec R-RW4/R-RW5).

One module, three questions, no network and no DNS:

* :func:`is_walled` — is this a login-walled host the backend never requests?
  The backend's own fetchers (``media_ingestor.enrich``, ``link_enrichment``)
  ask it and never fetch such a page (R-RW4, which also closes the X gap: X
  was never in the fetch rail). Not covered, and not loading the walled page:
  TikTok's provider oEmbed call and the Reddit and X connectors' own API calls.
  Its job is now only that, and naming the families a site is grouped under
  (owner 2026-09-30: there is no pre-picked list of sites a person may allow;
  a site is *surfaced* when Cicada's own reader could not read a page of it,
  see ``reading_walls``).
* :func:`classify` — may this URL be handed to a person's agent at all? The
  structural denials that hold whatever the person allowed: a URL that
  carries a secret or a side effect (S, R-RW5), a local or reserved host (L), an
  AI vendor's own share host (H), a video (V, the video path), a paper (P, the
  arXiv/Crossref path) and the one host that is never offered to an agent
  (``t.co``, a redirector that says nothing about where it lands).
* :func:`agent_may_read` — the one check ask time, queue time and record time
  all use: :func:`classify`, then the person's master switch. A per-site
  permission is a *queue* rule (``reading_queue``), not a gate on an explicit
  ask: "Ask an agent" on one page is the person's one-off consent for it.

:func:`site_of` names the site a URL belongs to (a walled family such as
``linkedin``, else the registrable-ish domain) — the key a permission is
stored under.

Matching is on a dot boundary — ``host == domain`` or ``host.endswith('.' +
domain)`` — never a substring, so a lookalike host is not walled and a short
host (``lnkd.in``, ``fb.watch``) is not missed.

The rail this sits beside is unchanged: a fetch Cicada makes itself is 4 s,
≤ 512 KB, no cookies, never behind auth, and a block is never retried with
different headers. Nothing here fetches anything, holds a session or reads a
browser profile; it only decides whether Cicada may ASK the person's own agent.
"""
from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlparse

#: The login-walled families the backend never requests. The key names the
#: family (so ``lnkd.in`` and ``twitter.com`` fold into ``linkedin`` and ``x``);
#: the value is every domain it covers.
WALLED_DOMAINS: dict[str, tuple[str, ...]] = {
    "linkedin": ("linkedin.com", "lnkd.in"),
    "x": ("x.com", "twitter.com"),
    "facebook": ("facebook.com", "fb.com", "fb.watch"),
    "instagram": ("instagram.com",),
    "tiktok": ("tiktok.com",),
    "reddit": ("reddit.com", "redd.it"),
}
HOST_LABELS: dict[str, str] = {
    "linkedin": "LinkedIn", "x": "X", "facebook": "Facebook", "instagram": "Instagram", "tiktok": "TikTok",
    "reddit": "Reddit",
}
#: A sentence a site's row may carry. A TikTok VIDEO is refused as class V (the
#: video path owns it), so a permission for the site covers only the pages that
#: are not one — the row must not over-promise.
SITE_NOTES: dict[str, str] = {
    "tiktok": "Profiles and pages only. A video goes through your agent's video tools.",
}
#: The host a site's icon is looked up under (the icon service only — the
#: walled host itself is never contacted). Measured 2026-09-30: the service
#: answers 404 for the bare ``instagram.com`` and 200 for the ``www.`` form.
ICON_HOSTS: dict[str, str] = {
    "linkedin": "linkedin.com", "x": "x.com", "facebook": "facebook.com", "instagram": "www.instagram.com",
    "tiktok": "tiktok.com", "reddit": "reddit.com",
}
#: Walled and never offered: ``t.co`` is a redirector that says nothing about
#: where it lands. (Reddit used to be here; with no pre-picked site list it
#: surfaces like any site, and a page that already holds words is not listed.)
NEVER_OFFERED_DOMAINS: dict[str, tuple[str, ...]] = {
    "t.co": ("t.co",),
}

#: Deny classes, as the one-letter code the spec uses (§6.1) plus ``N`` for the
#: never-offered pair and ``B`` for a URL that is not http(s) at all.
CLASS_SIDE_EFFECT = "S"
CLASS_LOCAL = "L"
CLASS_VENDOR = "H"
CLASS_VIDEO = "V"
CLASS_PAPER = "P"
CLASS_NEVER = "N"
CLASS_BAD = "B"

# --- R-RW5: side-effect and secret-bearing URLs -----------------------------

_S_QUERY_KEYS = frozenset({
    "token", "key", "sig", "signature", "auth", "code", "session", "otp", "magic", "reset", "verify",
    "confirm", "invite", "unsubscribe",
})
_S_QUERY_SUFFIXES = ("token", "_key", "-key", "secret", "password", "passwd", "signature")
_S_PATH_SEGMENTS = frozenset({
    "unsubscribe", "verify", "confirm", "reset", "invite", "logout", "oauth", "callback", "delete",
})
#: Private-workspace hosts: a share link is a capability, and a page behind one
#: is not a public page the person chose to bring into memory.
_PRIVATE_WORKSPACE = (
    "docs.google.com", "drive.google.com", "notion.so", "notion.site", "figma.com", "slack.com",
    "dropbox.com", "onedrive.live.com", "1drv.ms", "airtable.com", "sharepoint.com",
)

# --- H: AI vendors' own hosts ------------------------------------------------

_VENDOR_HOSTS = (
    "chatgpt.com", "chat.openai.com", "claude.ai", "gemini.google.com", "grok.com", "copilot.microsoft.com",
    "chat.mistral.ai", "poe.com",
)

_LOCAL_SUFFIXES = (".local", ".localhost", ".internal", ".lan", ".home.arpa", ".invalid", ".test", ".localdomain",
                   ".ts.net", ".corp", ".intranet", ".home", ".private")

_REFUSAL = {
    CLASS_BAD: "That is not a web address an agent can open (it must start with http:// or https://).",
    CLASS_SIDE_EFFECT: ("That link carries a secret or an action (a token, a sign-in or unsubscribe step), so "
                        "it is never offered to an agent."),
    CLASS_LOCAL: "That address is on this Mac or a private network, so it is never offered to an agent.",
    CLASS_VENDOR: "That is an AI app's own page, not a source of yours, so it is never offered to an agent.",
    CLASS_VIDEO: "That is a video. Videos go through your agent's video tools (cicada_record_watch), not here.",
    CLASS_PAPER: "That is a paper. Cicada builds paper pages from arXiv and Crossref, so it is not read here.",
    CLASS_NEVER: "Cicada never offers this link to an agent: it is a redirector that says nothing about where it lands.",
}


@dataclass(frozen=True)
class Verdict:
    """The answer for one URL. ``ok`` false carries a plain ``reason``; ``cls`` is
    the deny class (``""`` when allowed, ``"off"`` when only the person's master
    switch stands in the way); ``site`` is the site key the URL belongs to
    (:func:`site_of`, ``""`` when there is no usable host); ``walled`` is true for
    any walled host (the ledger's ``host_class``: ``walled`` or ``public``)."""

    ok: bool
    cls: str
    host: str
    site: str
    walled: bool
    reason: str = ""

    @property
    def host_class(self) -> str:
        return "walled" if self.walled else "public"


def host_of(url: str) -> str:
    try:
        return (urlparse(url or "").hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def _on(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def _any_on(host: str, domains) -> bool:
    return any(_on(host, d) for d in domains)


def walled_key(url_or_host: str) -> str | None:
    """The walled family key (``linkedin``, ``x``, …) for a URL or a bare host."""
    host = host_of(url_or_host) if "://" in (url_or_host or "") else (url_or_host or "").lower()
    for key, domains in WALLED_DOMAINS.items():
        if _any_on(host, domains):
            return key
    return None


def is_walled(url: str) -> bool:
    """True for every login-walled host, the never-offered pair included. The
    backend's fetchers use this alone (R-RW4)."""
    host = host_of(url)
    if not host:
        return False
    if walled_key(host) is not None:
        return True
    return any(_any_on(host, domains) for domains in NEVER_OFFERED_DOMAINS.values())


def _is_local(host: str) -> bool:
    if not host or "." not in host:
        return True  # a single-label host is a machine name, never the public web
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True  # a literal address, private or not, is never a page the person shared
    except ValueError:
        pass
    if host.endswith(_LOCAL_SUFFIXES) or host == "localhost":
        return True
    return "example" in host.split(".")  # RFC 2606's example.com/org/net and example.<tld>


def _secret_query(query: str) -> bool:
    for key, _value in parse_qsl(query or "", keep_blank_values=True):
        k = key.strip().lower()
        if k in _S_QUERY_KEYS or k.startswith("x-amz-") or k.endswith(_S_QUERY_SUFFIXES):
            return True
    return False


def _side_effect(parsed, host: str) -> bool:
    if parsed.username or parsed.password:
        return True
    try:
        port = parsed.port
    except ValueError:
        return True
    if port not in (None, 80, 443):
        return True
    if _secret_query(parsed.query):
        return True
    segments = {s.lower() for s in (parsed.path or "").split("/") if s}
    if segments & _S_PATH_SEGMENTS:
        return True
    return _any_on(host, _PRIVATE_WORKSPACE)


def _vendor(parsed, host: str) -> bool:
    if _any_on(host, _VENDOR_HOSTS):
        return True
    path = (parsed.path or "").lower()
    if host == "g.co" or host.endswith(".g.co"):
        return path.startswith("/gemini")
    if _on(host, "perplexity.ai"):
        return path.startswith(("/search", "/page", "/collections"))
    return False


def _refuse(cls: str, host: str, walled: bool = False) -> Verdict:
    return Verdict(False, cls, host, site_of(host) if host else "", walled, _REFUSAL[cls])


def classify(url: str) -> Verdict:
    """The structural verdict for ``url``: pure string work, no DNS, no fetch.

    Order matters and is fixed: a bad URL, then side effects (a secret must
    never reach any later branch, and a video or a paper that carries one is
    still refused for it), local hosts, vendor hosts, the never-offered host,
    a video, a paper. An allowed URL says whether its host is walled and which
    site it belongs to."""
    raw = (url or "").strip()
    try:
        parsed = urlparse(raw)
    except ValueError:
        return _refuse(CLASS_BAD, "")
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme.lower() not in ("http", "https") or not host:
        return _refuse(CLASS_BAD, host)
    if _side_effect(parsed, host):
        return _refuse(CLASS_SIDE_EFFECT, host)
    if _is_local(host):
        return _refuse(CLASS_LOCAL, host)
    if _vendor(parsed, host):
        return _refuse(CLASS_VENDOR, host)
    if any(_any_on(host, domains) for domains in NEVER_OFFERED_DOMAINS.values()):
        return _refuse(CLASS_NEVER, host, walled=True)
    from api.services import papers, video_urls  # lazy: both import the media writer's neighbours

    key = walled_key(host)
    if video_urls.resolve(raw) is not None:
        return _refuse(CLASS_VIDEO, host, walled=key is not None)
    if papers.never_scraped(raw):
        return _refuse(CLASS_PAPER, host)
    return Verdict(True, "", host, site_of(host), key is not None)


def agent_may_read(url: str, *, enabled: bool) -> Verdict:
    """The one gate for handing ``url`` to an agent: structural denials first,
    then the person's master switch. Nothing here asks about a site: a walled
    host is askable page by page whenever the switch is on, and the per-site
    permission is a queue rule (``reading_queue``)."""
    verdict = classify(url)
    if not verdict.ok:
        return verdict
    if not enabled:
        return Verdict(False, "off", verdict.host, verdict.site, verdict.walled,
                       "Agent reading is off. Turn it on in Settings, Reading the web.")
    return verdict


# --- sites ---------------------------------------------------------------------------

#: Hosts where each subdomain is somebody else's site: never folded to the parent.
SHARED_HOST_SUFFIXES = (
    "github.io", "gitlab.io", "blogspot.com", "pages.dev", "vercel.app", "netlify.app", "wordpress.com",
    "herokuapp.com", "web.app", "firebaseapp.com", "substack.com", "medium.com", "tumblr.com", "ghost.io",
    "fly.dev", "onrender.com", "azurewebsites.net", "workers.dev",
)
_SECOND_LEVEL = frozenset({"co", "com", "org", "net", "gov", "edu", "ac"})
_SITE_KEY = re.compile(r"^[a-z0-9][a-z0-9.-]{0,79}$")


def site_of(url_or_host: str) -> str:
    """The site a URL or bare host belongs to — the key a permission is stored
    under. A walled family folds to its name (``lnkd.in`` -> ``linkedin``);
    anything else is its registrable-ish domain: ``www.`` stripped, the last two
    labels (three under a ``co.uk``-style suffix), and never folded into the
    parent under a shared host (``user.github.io`` stays its own site). No
    public-suffix list: a closed helper with a table test."""
    raw = url_or_host or ""
    host = host_of(raw) if "://" in raw else raw.strip().lower().rstrip(".")
    host = host.split("/")[0].split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return ""
    family = walled_key(host)
    if family is not None:
        return family
    try:
        ipaddress.ip_address(host.strip("[]"))
        return host  # a literal address is its own site (and is never offered anyway)
    except ValueError:
        pass
    labels = host.split(".")
    for shared in SHARED_HOST_SUFFIXES:
        if host == shared:
            return host
        if host.endswith("." + shared):
            depth = shared.count(".") + 2
            return ".".join(labels[-depth:])
    if len(labels) <= 2:
        return host
    keep = 3 if len(labels[-1]) == 2 and labels[-2] in _SECOND_LEVEL else 2
    return ".".join(labels[-keep:])


def site_label(site: str) -> str:
    return HOST_LABELS.get(site, site)


def valid_site_key(key: str) -> bool:
    """A site key a permission may be stored under: a plain lower-case host-like
    name, and never the never-offered host."""
    k = (key or "")
    if not _SITE_KEY.match(k):
        return False
    return not any(_any_on(k, domains) for domains in NEVER_OFFERED_DOMAINS.values())


def is_public_name(host: str) -> bool:
    """True for a host that looks like a public site name — not single-label, not
    a literal address, not a local, tailnet, corporate or private suffix. The
    icon lookup asks it before it names a host to a third party."""
    return not _is_local(host_of(host) if "://" in (host or "") else (host or "").lower().rstrip("."))


def icon_host(site: str, *, saved_hosts=()) -> str | None:
    """The one host a site's icon is looked up under: a family's fixed host, else
    the site key itself when it is a public-looking domain (never a saved
    subdomain — the service is told the site's name and no more). ``saved_hosts``
    is accepted for signature symmetry and ignored (M10)."""
    fixed = ICON_HOSTS.get(site)
    if fixed:
        return fixed
    if valid_site_key(site) and "." in site and is_public_name(site):
        return site
    return None


_HOST_SAFE = re.compile(r"[^a-z0-9.-]")


def display_host(host: str) -> str:
    """A host as a sentence may name it: lower-case letters, digits, dots and
    hyphens only, so a crafted host can never carry markup into a reply."""
    h = _HOST_SAFE.sub("", (host or "").lower())
    return h[4:] if h.startswith("www.") else h
