"""The closed host sets for reading the web (G166, spec §5 R-RW4/R-RW5, §7.2).

One module, three questions, no network and no DNS:

* :func:`is_walled` — is this a login-walled host? The backend's own fetchers
  (``media_ingestor.enrich``, ``link_enrichment``) ask it and never fetch such
  a page (R-RW4, which also closes the X gap: X was never in the fetch rail).
  Not covered, and not loading the walled page: TikTok's provider oEmbed call
  and the Reddit and X connectors' own API calls.
* :func:`classify` — may this URL be handed to a person's agent at all? The
  structural denials that hold whatever the person switched on: a URL that
  carries a secret or a side effect (S, R-RW5), a local or reserved host (L), an
  AI vendor's own share host (H), a video (V, the video path), a paper (P, the
  arXiv/Crossref path) and the two hosts that are never offered to an agent
  (Reddit, which has its own connector, and ``t.co``, a redirector).
* :func:`agent_may_read` — the one check ask time, queue time and record time
  all use: :func:`classify`, then, for a walled host, the person's per-site
  switch (``reading.agent_hosts``).

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

#: The five hosts the person can switch on for an agent, in the order the
#: first-use sheet lists them. The value is every domain that key covers.
WALLED_DOMAINS: dict[str, tuple[str, ...]] = {
    "linkedin": ("linkedin.com", "lnkd.in"),
    "x": ("x.com", "twitter.com"),
    "facebook": ("facebook.com", "fb.com", "fb.watch"),
    "instagram": ("instagram.com",),
    "tiktok": ("tiktok.com",),
}
AGENT_HOST_KEYS: tuple[str, ...] = tuple(WALLED_DOMAINS)
HOST_LABELS: dict[str, str] = {
    "linkedin": "LinkedIn", "x": "X", "facebook": "Facebook", "instagram": "Instagram", "tiktok": "TikTok",
}
#: The app's sentence under a switch, when the key needs one. A TikTok VIDEO is
#: refused as class V (the video path owns it), so the switch covers only the
#: pages that are not one — the sheet must not over-promise.
HOST_NOTES: dict[str, str] = {
    "tiktok": "Profiles and pages only. A TikTok video goes through your agent's video tools instead.",
}
#: Walled and never offered: Reddit has its own connector and archive path, and
#: ``t.co`` is a redirector that says nothing about where it lands.
NEVER_OFFERED_DOMAINS: dict[str, tuple[str, ...]] = {
    "reddit": ("reddit.com", "redd.it"),
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

_LOCAL_SUFFIXES = (".local", ".localhost", ".internal", ".lan", ".home.arpa", ".invalid", ".test", ".localdomain")

_REFUSAL = {
    CLASS_BAD: "That is not a web address an agent can open (it must start with http:// or https://).",
    CLASS_SIDE_EFFECT: ("That link carries a secret or an action (a token, a sign-in or unsubscribe step), so "
                        "it is never offered to an agent."),
    CLASS_LOCAL: "That address is on this Mac or a private network, so it is never offered to an agent.",
    CLASS_VENDOR: "That is an AI app's own page, not a source of yours, so it is never offered to an agent.",
    CLASS_VIDEO: "That is a video. Videos go through your agent's video tools (cicada_record_watch), not here.",
    CLASS_PAPER: "That is a paper. Cicada builds paper pages from arXiv and Crossref, so it is not read here.",
    CLASS_NEVER: "Cicada never offers this site to an agent. Use its own connector or your account's data export.",
}


@dataclass(frozen=True)
class Verdict:
    """The answer for one URL. ``ok`` false carries a plain ``reason``; ``cls`` is
    the deny class (``""`` when allowed, ``"off"`` when only the person's switch
    stands in the way); ``host_key`` is set for a walled host the person can
    switch on; ``walled`` is true for any walled host (the ledger's
    ``host_class``: ``walled`` or ``public``)."""

    ok: bool
    cls: str
    host: str
    host_key: str | None
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
    """The switchable walled key (``linkedin``, ``x``, …) for a URL or a bare host."""
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


def _refuse(cls: str, host: str, walled: bool = False, host_key: str | None = None) -> Verdict:
    return Verdict(False, cls, host, host_key, walled, _REFUSAL[cls])


def classify(url: str) -> Verdict:
    """The structural verdict for ``url``: pure string work, no DNS, no fetch.

    Order matters and is fixed: a bad URL, then side effects (a secret must
    never reach any later branch, and a video or a paper that carries one is
    still refused for it), local hosts, vendor hosts, the never-offered pair,
    a video, a paper. An allowed URL says whether its host is walled and which
    switch covers it."""
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
        return _refuse(CLASS_VIDEO, host, walled=key is not None, host_key=key)
    if papers.never_scraped(raw):
        return _refuse(CLASS_PAPER, host)
    return Verdict(True, "", host, key, key is not None)


def switch_off_reason(verdict: Verdict) -> str:
    label = HOST_LABELS.get(verdict.host_key or "", verdict.host)
    return (f"{label} is not turned on for your agent. Turn it on in Settings, Agents, "
            "Reading pages, then ask again.")


def agent_may_read(url: str, *, enabled: bool, allowed_hosts) -> Verdict:
    """The one gate for handing ``url`` to an agent: structural denials first,
    then the person's master switch, then — only for a walled host — the
    per-site switch. ``allowed_hosts`` is ``reading_settings.allowed_hosts()``."""
    verdict = classify(url)
    if not verdict.ok:
        return verdict
    if not enabled:
        return Verdict(False, "off", verdict.host, verdict.host_key, verdict.walled,
                       "Agent reading is off. Turn it on in Settings, Agents, Reading pages.")
    if verdict.host_key is not None and verdict.host_key not in set(allowed_hosts or ()):
        return Verdict(False, "off", verdict.host, verdict.host_key, True, switch_off_reason(verdict))
    return verdict


_HOST_SAFE = re.compile(r"[^a-z0-9.-]")


def display_host(host: str) -> str:
    """A host as a sentence may name it: lower-case letters, digits, dots and
    hyphens only, so a crafted host can never carry markup into a reply."""
    h = _HOST_SAFE.sub("", (host or "").lower())
    return h[4:] if h.startswith("www.") else h
