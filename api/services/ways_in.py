"""The ways into Cicada for what the person consumes on Spotify, Reddit, Pinterest, TikTok and Instagram (G232).

Owner, 2026-11-04: "why can't we sync Spotify another way? Is there no way to do similar to GitHub, … or maybe default
to also a website and maybe offer the website connection through browser harness, just like a toggle switch, and then
also the file export. Same for TikTok, same for Pinterest, same for Reddit, same for Instagram."

A source page's connect area offers up to three ways in, and this module says, per source, which exist, which is
recommended, and — for a way that is not offered — why, in words. It reads state and writes nothing; every action is an
existing route:

* **account** — an official API connection (ruling 47 tier 2): ``/sources/connectors/<id>`` (status), ``POST
  …/authorize`` (Connect, Cicada's own app), ``PUT …/credentials`` (the person's own app), ``DELETE …/credentials``
  (Disconnect, which also revokes where the service allows it), ``POST …/sync`` (Refresh).
* **browser** — the person's own agent reads the list in their own signed-in browser (G206, tier 1):
  ``PUT /reading/settings`` with ``savedLists: {<key>: true|false}`` is the toggle; ``GET /reading/settings``'s
  ``saved.lists.<key>`` the last read, its outcome and any pause.
* **file** — the service's own data download: ``POST /sources/upload`` (``saved_exports`` reads the archive member by
  member).

Which ways exist was decided on 2026-11-04 against each service's own terms and developer documentation (the table in
``docs/architecture/network.md``, "Ways in, per source"). In short: Spotify's Developer Terms and its User Guidelines
both bar automated access and putting its content into an AI model, so Spotify is a file only; Reddit's API serves a
desktop app with no secret (an installed app) but new access needs Reddit's approval, so Connect shows only once the
build carries an approved client id; Pinterest's token exchange needs a client secret and apps registered since
2026-09-14 cannot read a personal account's boards, so only the person's own older app connects; TikTok's and
Instagram's APIs return no likes, favourites or saves for a personal account.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FileWay:
    #: The ``saved_exports`` platform id the archive is read as.
    platform: str
    #: Where the person asks for their data, as a link they open in their own browser.
    request_url: str
    #: How to get the file, in the service's own words.
    how: str
    #: What Cicada reads from it.
    reads: str


@dataclass(frozen=True)
class Source:
    id: str
    label: str
    #: The connector in ``connectors.ADAPTERS`` an account connection uses, if any.
    connector: str | None
    #: The ``saved_lists.PLATFORMS`` key the browser toggle turns on, if any.
    browser: str | None
    file: FileWay | None
    #: Why a way is not offered, by kind — said under the connect area, never hidden.
    not_offered: dict[str, str]


SPOTIFY_TERMS = ("Spotify's Developer Terms bar an app from putting its content into an AI model, so Cicada has no "
                 "Spotify connector. Your own agent can read your library in your browser, and your own data download "
                 "is yours to bring in.")
TIKTOK_NO_ACCOUNT = ("TikTok's API gives an app your profile and your own public videos only — never your likes, "
                     "favorites or watch history.")
INSTAGRAM_NO_ACCOUNT = ("Instagram's API serves business and creator accounts only, and returns no saved or liked "
                        "posts for any account.")
PINTEREST_OWN_APP = ("Pinterest has no sign-in an app can use without a server: its sign-in needs an app secret, and "
                     "apps registered since 14 September 2026 can't read a personal account's boards.")
PINTEREST_FILE = ("Pinterest's data download (Settings → Privacy and data → Request your data) isn't read yet: "
                  "Pinterest doesn't document what it holds, so Cicada can't read it until one has been looked at.")

SOURCES: dict[str, Source] = {
    "spotify": Source(
        "spotify", "Spotify", None, "spotify",
        FileWay("spotify", "https://www.spotify.com/account/privacy/",
                "On spotify.com, open Account → Privacy settings → Download your data, and ask for Extended "
                "streaming history (every play) or Account data (the last year, your library and playlists). "
                "Spotify emails a .zip, which can take up to 30 days; drop it here.",
                "Every play, one entry per day; your liked songs, albums, podcasts and playlists as saved items."),
        {"account": SPOTIFY_TERMS}),
    "reddit": Source(
        "reddit", "Reddit", "reddit", "reddit",
        FileWay("reddit", "https://www.reddit.com/settings/data-request",
                "On reddit.com, open Settings → Privacy → Request your data (or reddit.com/settings/data-request). "
                "Reddit emails a link to a .zip; drop it here as it is.",
                "Your saved posts and comments, your upvotes and the communities you joined."),
        {}),
    "pinterest": Source(
        "pinterest", "Pinterest", "pinterest", "pinterest", None,
        {"account": PINTEREST_OWN_APP, "file": PINTEREST_FILE}),
    "tiktok": Source(
        "tiktok", "TikTok", None, "tiktok",
        FileWay("tiktok", "https://www.tiktok.com/setting/download-your-data",
                "In TikTok: Profile → menu → Settings and privacy → Account → Download your data, file format JSON. "
                "When it's ready (a few days), drop the .zip or user_data_tiktok.json here.",
                "Your favorites and likes as saved items; your watch history only if you include it."),
        {"account": TIKTOK_NO_ACCOUNT}),
    "instagram": Source(
        "instagram", "Instagram", None, "instagram",
        FileWay("instagram", "https://accountscenter.instagram.com/info_and_permissions/dyi/",
                "In Instagram: Accounts Center → Your information and permissions → Export your information → "
                "Saved and Likes, format JSON. Drop the .zip here.",
                "Your saved posts, their collections and your liked posts as saved items."),
        {"account": INSTAGRAM_NO_ACCOUNT}),
}


#: The one short line the connect area shows when the official account is not offered (its full reason on hover).
SHORT: dict[str, str] = {
    "spotify": "Spotify has no account connection; your agent can read it in your browser.",
    "pinterest": "Pinterest connects only through your own app.",
    "tiktok": "TikTok's API doesn't share likes or favorites.",
    "instagram": "Instagram's API doesn't share saved posts.",
}
REDDIT_NOT_SET_UP_SHORT = "Connecting a Reddit account isn't set up in this build yet."


def _account(src: Source) -> dict | None:
    """The official connection's state (``None`` when the source has no connector)."""
    from api.services.connectors import ADAPTERS

    if src.connector is None:
        return None
    adapter = ADAPTERS[src.connector]
    connected = bool(adapter.is_connected())
    app = bool(getattr(adapter, "app_available", lambda: False)())
    return {"connector": src.connector, "connected": connected,
            # ``app``: one click, a browser sign-in with Cicada's own app. ``own-app``: the person's own app's fields.
            "connect": "app" if app else "own-app",
            "how": getattr(adapter, "how", lambda: None)() if connected else None,
            "reconnect": bool(getattr(adapter, "needs_reconnect", lambda: False)()),
            "reads": getattr(adapter, "READS", None)}


def _browser(src: Source, memory_path: Path) -> dict | None:
    from api.services import reading_settings, saved_lists

    if src.browser is None:
        return None
    p = saved_lists.PLATFORMS[src.browser]
    entry = saved_lists.last(memory_path, src.browser)
    until = saved_lists.paused_until(src.browser)
    return {"kind": "browser", "list": src.browser, "label": p.label,
            "on": src.browser in reading_settings.saved_lists(),
            # Off whenever agent reading is off (its first-use sheet), whatever the toggle says.
            "agentReading": reading_settings.agent_enabled(),
            "lastReadAt": entry.get("read_at"), "lastOutcome": entry.get("outcome"),
            "pausedUntil": until.isoformat() if until else None}


def _file(src: Source) -> dict | None:
    if src.file is None:
        return None
    f = src.file
    return {"kind": "file", "platform": f.platform, "requestUrl": f.request_url, "how": f.how, "reads": f.reads}


def _primary(src: Source, account: dict | None) -> tuple[dict | None, str, str | None, bool]:
    """``(primary, state, line, line_is_attention)`` for the connect area (``SourceConnectArea``, app.md "The standard
    source page"): the official connection is the one primary action when it can be offered; otherwise there is
    none, and the line says why in a few words (the whole reason is ``notOffered``'s, on hover)."""
    if account is None:
        return None, "notConnected", SHORT.get(src.id), False
    if account["reconnect"]:
        return ({"action": "reconnect", "connector": src.connector}, "needsAttention",
                "Reddit signed Cicada out." if src.id == "reddit" else None, True)
    if account["connected"]:
        return ({"action": "connected", "connector": src.connector}, "connected", account["reads"], False)
    if account["connect"] == "app":
        return {"action": "connect", "connector": src.connector}, "notConnected", account["reads"], False
    # Only the person's own app connects: offered behind "Use your own app", never as the page's primary.
    short = REDDIT_NOT_SET_UP_SHORT if src.id == "reddit" else SHORT.get(src.id)
    return None, "notConnected", short, False


def recommended(primary: dict | None, ways: list[dict]) -> str:
    """The way the connect area leads with: a working account connection (complete and kept current), else the
    browser (current, no waiting), else the file."""
    if primary is not None:
        return "account"
    kinds = {w["kind"] for w in ways}
    return "browser" if "browser" in kinds else "file"


def describe(source_id: str, memory_path: Path) -> dict | None:
    """One source's connect area: ``state``, the ``primary`` action (``connect`` · ``reconnect`` · ``connected``, or
    null), one ``line``, the ``ways`` (``browser`` and ``file`` rows), the ``account`` details (null without a
    connector), ``ownApp`` (always false: no app asks for an app key or secret, owner 2026-11-05) and ``notOffered`` (a way
    that does not exist, with the reason in words)."""
    src = SOURCES.get(source_id)
    if src is None:
        return None
    account = _account(src)
    primary, state, line, attention = _primary(src, account)
    ways = [w for w in (_browser(src, memory_path), _file(src)) if w is not None]
    offered = {w["kind"] for w in ways} | ({"account"} if primary is not None else set())
    return {"source": src.id, "label": src.label, "state": state, "primary": primary, "line": line,
            "lineIsAttention": attention, "ways": ways, "account": account,
            "ownApp": False,
            "recommended": recommended(primary, ways),
            "notOffered": [{"kind": k, "words": v} for k, v in src.not_offered.items() if k not in offered]
            + ([{"kind": "account", "words": getattr(_adapter(src), "NOT_SET_UP", "")}]
               if account is not None and primary is None and "account" not in src.not_offered else [])}


def _adapter(src: Source):
    from api.services.connectors import ADAPTERS

    return ADAPTERS[src.connector]


def describe_all(memory_path: Path) -> list[dict]:
    return [d for d in (describe(sid, memory_path) for sid in SOURCES) if d is not None]
