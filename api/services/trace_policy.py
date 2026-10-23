"""What an activity trace may hold (G218) — the ONE policy, served to the app and re-applied by the store.

The app applies these rules before anything leaves it (it reads the screen; the backend never does), and the store
applies them again on every row it is handed, so a bug on one side never writes what the other refused:

* **Never recorded, not even the app's name** (:data:`NEVER_APPS`): password managers and the system's credential
  sheets, the login window and screensaver, and Cicada itself. The person's own excluded apps join them.
* **Title-off** (:data:`TITLE_OFF_APPS`): chat and mail apps, whose window titles name other people and subjects. The
  row keeps the app and the times only, unless the person turned titles on for that app.
* **URLs** only from a browser the person allowed, and only from :data:`URL_BROWSERS` — the Chromium family, whose
  scripting says when a window is incognito. Safari waits until its private windows are proven distinguishable.
  A URL keeps scheme, host and path; the query is dropped (tokens live there) except :data:`CONTENT_KEYS`, which name
  the thing itself (YouTube's ``v``); the fragment is dropped; the path is scrubbed.
* **A private window, or a site the person excluded**, drops the whole row: nothing is recorded, not even the app.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlparse

from api.services import episode_scrub

#: Bundle ids whose moments are never recorded at all.
NEVER_APPS: frozenset[str] = frozenset({
    # Password managers and credential UIs.
    "com.1password.1password", "com.agilebits.onepassword7", "com.agilebits.onepassword-osx",
    "com.agilebits.onepassword4", "com.bitwarden.desktop", "com.apple.Passwords", "com.apple.keychainaccess",
    "com.lastpass.LastPass", "com.dashlane.Dashlane", "org.keepassxc.keepassxc", "in.sinew.Enpass-Desktop",
    "me.proton.pass.electron", "com.apple.SecurityAgent", "com.apple.LocalAuthentication.UIAgent",
    "com.apple.CoreAuthUI",
    # The locked screen and the screensaver.
    "com.apple.loginwindow", "com.apple.ScreenSaver.Engine",
})
#: Cicada's own windows (every build: a release, a developer build, a verification copy's per-run id).
SELF_PREFIX = "com.rorosaga.cicada"

#: Chat and mail: the row keeps the app and its times, never the window title, unless the person turns titles on.
TITLE_OFF_APPS: frozenset[str] = frozenset({
    "com.apple.mail", "com.apple.MobileSMS", "com.apple.FaceTime", "com.tinyspeck.slackmacgap", "com.hnc.Discord",
    "net.whatsapp.WhatsApp", "desktop.WhatsApp", "ru.keepcoder.Telegram", "org.telegram.desktop",
    "org.whispersystems.signal-desktop", "com.microsoft.teams", "com.microsoft.teams2", "com.microsoft.Outlook",
    "com.readdle.smartemail-Mac", "com.superhuman.electron", "com.facebook.archon", "us.zoom.xos",
    "com.google.Gmail", "com.apple.Contacts",
})

#: The browsers whose URL may be read, by the name the person allows them under → their bundle ids.
URL_BROWSERS: dict[str, tuple[str, ...]] = {
    "chrome": ("com.google.Chrome", "com.google.Chrome.beta", "com.google.Chrome.dev", "com.google.Chrome.canary"),
    "brave": ("com.brave.Browser",),
    "edge": ("com.microsoft.edgemac",),
    "vivaldi": ("com.vivaldi.Vivaldi",),
}

#: Query keys kept because they name the content, per host suffix.
CONTENT_KEYS: dict[str, frozenset[str]] = {"youtube.com": frozenset({"v"})}

#: Every browser Cicada knows. A browser row keeps a title only beside a URL read from an allowed Chromium browser —
#: the only case where the window is known not to be private (Safari's, Firefox's and Arc's private windows cannot be
#: told apart by scripting, so their rows keep the app and the times).
KNOWN_BROWSERS: frozenset[str] = frozenset(
    {b for ids in URL_BROWSERS.values() for b in ids} | {
        "com.apple.Safari", "com.apple.SafariTechnologyPreview", "org.mozilla.firefox",
        "org.mozilla.firefoxdeveloperedition", "company.thebrowser.Browser", "com.operasoftware.Opera",
        "com.kagi.kagimacOS", "app.zen-browser.zen", "com.duckduckgo.macos.browser", "org.torproject.torbrowser",
    })

URL_CAP = 400
TITLE_CAP = 300
APP_NAME_CAP = 80
_BUNDLE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.\-_]{0,199}$")
_HOST = re.compile(r"^[a-z0-9.-]{1,253}$")


def valid_bundle(bundle_id: str) -> bool:
    return bool(_BUNDLE.match(bundle_id or ""))


def never_recorded(bundle_id: str, excluded_apps: frozenset[str] | set[str] = frozenset()) -> bool:
    b = bundle_id or ""
    return b in NEVER_APPS or b.startswith(SELF_PREFIX) or b in excluded_apps


def title_allowed(bundle_id: str, *, titles_on: bool, title_apps: frozenset[str] | set[str] = frozenset()) -> bool:
    if not titles_on:
        return False
    return bundle_id not in TITLE_OFF_APPS or bundle_id in title_apps


def url_browser(bundle_id: str) -> str | None:
    for name, ids in URL_BROWSERS.items():
        if bundle_id in ids:
            return name
    return None


def normalize_host(text: str) -> str | None:
    """A host the person typed into the excluded-sites list (``bank.example``, ``https://www.bank.example/x``)."""
    raw = (text or "").strip().lower()
    if not raw:
        return None
    if "://" not in raw:
        raw = "https://" + raw
    try:
        host = urlparse(raw).hostname or ""
    except ValueError:
        return None
    host = host.removeprefix("www.")
    return host if _HOST.match(host) and "." in host else None


def host_excluded(host: str, excluded_sites: frozenset[str] | set[str]) -> bool:
    h = (host or "").lower().removeprefix("www.")
    return any(h == site or h.endswith("." + site) for site in excluded_sites)


def clean_url(url: str | None) -> tuple[str, str] | None:
    """``(clean url, host)`` — scheme, host and path, the content keys of the query, the path scrubbed — or ``None``
    for anything that is not a plain web page (``file:``, ``chrome:``, a data URL)."""
    raw = (url or "").strip()
    if not raw:
        return None
    try:
        parsed = urlparse(raw)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https"):
        return None
    host = (parsed.hostname or "").lower()
    if not host or not _HOST.match(host):
        return None
    keys = next((k for suffix, k in CONTENT_KEYS.items() if host == suffix or host.endswith("." + suffix)),
                frozenset())
    kept = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=False) if k in keys]
    path = episode_scrub.scrub(parsed.path or "/")[0]
    out = f"{parsed.scheme}://{host}{path}"
    if kept:
        out += "?" + urlencode(kept[:2])
    return (out if len(out) <= URL_CAP else out[:URL_CAP]), host


def clean_title(title: str | None) -> str:
    text = " ".join(str(title or "").split())
    text = episode_scrub.scrub(text)[0]
    return text if len(text) <= TITLE_CAP else text[: TITLE_CAP - 1].rstrip() + "…"


def clean_app_name(name: str | None) -> str:
    text = " ".join(str(name or "").split())
    return text[:APP_NAME_CAP]


def served() -> dict:
    """The lists the app applies before anything leaves it (``GET /sources/traces/settings``)."""
    return {"never_apps": sorted(NEVER_APPS), "self_prefix": SELF_PREFIX, "title_off_apps": sorted(TITLE_OFF_APPS),
            "url_browsers": {name: list(ids) for name, ids in URL_BROWSERS.items()},
            "known_browsers": sorted(KNOWN_BROWSERS),
            "content_keys": {host: sorted(keys) for host, keys in CONTENT_KEYS.items()}}
