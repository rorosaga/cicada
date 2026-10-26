"""Report a problem (tester readiness, 2026-10-26): the text a person reads, then copies, saves or sends.

``GET /diagnostics/report`` builds it; the app puts its own version, build and macOS version on top and shows the
whole thing in a sheet before anything leaves the Mac. Nothing here sends anything, and nothing is persisted.

What it holds: the backend's version, the platform, the engine mode (an enum — never an account or an email, G148),
which sources are connected (channel ids only), the bank count (never a name), recent warnings and errors, and the
tail of the backend's and the app's own logs. What it never holds: bank content, page names, episode text, URLs, or a
path under the person's home. Logs are free text, so every line goes through :func:`redact` — secrets
(``episode_scrub``), the home path, emails, URLs, bank names, quoted text, wikilinks, bank-relative paths and the ids
in request paths — and the person still reads it before sending; the sheet says so.
"""
from __future__ import annotations

import os
import platform
import re
from collections import deque
from collections.abc import Iterable
from pathlib import Path

from api.services import episode_scrub

#: Lines of each log the report carries by default, and the most a caller may ask for.
DEFAULT_LINES = 200
MAX_LINES = 1000
#: Warnings and errors listed on their own, newest last.
RECENT_ERRORS = 20
#: A log line longer than this is cut: a stack frame or a request is still legible, a dumped payload is not.
MAX_LINE = 300

BACKEND_LOGS = ("backend.log", "backend.err.log", "backend.out.log")
APP_LOGS = ("update.log",)

HOME = "~"
URL = "[url]"
EMAIL = "[email]"
BANK = "[bank]"
TEXT = "[…]"

_URL = re.compile(r"\b[a-zA-Z][a-zA-Z0-9+.-]*://[^\s\"'<>)\]]+")
_WWW = re.compile(r"\bwww\.[^\s\"'<>)\]]+", re.IGNORECASE)
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_OTHER_HOME = re.compile(r"/(?:Users|home)/[^/\s\"']+")
_WIKILINK = re.compile(r"\[\[[^\]]*\]\]")
# A bank's own folders: what follows names a page, a conversation or an item.
_BANK_PATH = re.compile(r"\b(entities|episodes|hubs|inbox|backlog|captures|skills|design|_sites)/[^\s\"',;:)\]]+")
# uvicorn's access line: `"GET /entities/<id>/card HTTP/1.1" 200` — the route's first segment says what was asked;
# the rest is an id (a page, a conversation), so it goes.
_REQUEST = re.compile(r"\"(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS) (/[^/\s?\"]*)([^\s\"]*)( HTTP/[0-9.]+)?\"")
_QUOTED = re.compile(r"(?P<q>['\"“‘])(?P<body>[^'\"“”‘’\n]{1,400})(?:['\"”’])")
_LEVEL = re.compile(r"\|\s*(WARNING|ERROR|CRITICAL)\s*\||^(?:WARNING|ERROR|CRITICAL):|Traceback \(most recent call last\)")


def _home_forms(home: str | os.PathLike | None) -> list[str]:
    if not home:
        return []
    raw = str(home).rstrip("/")
    forms = {raw}
    try:
        forms.add(str(Path(raw).resolve()).rstrip("/"))
    except OSError:
        pass
    # macOS answers /var/... and /private/var/... for the same scratch home.
    forms |= {f.removeprefix("/private") for f in list(forms) if f.startswith("/private/")}
    return sorted((f for f in forms if len(f) > 1), key=len, reverse=True)


def redact(text: str, *, home: str | os.PathLike | None = None, bank_names: Iterable[str] = ()) -> str:
    """One log text as the report may carry it. Order matters: secrets first (a token inside a URL is still a token),
    then the home path (before URLs and quotes, so a path in quotes still reads ``~/…``), then everything that could
    name a person, a page or a place."""
    text, _ = episode_scrub.scrub(text or "")
    for form in _home_forms(home):
        text = text.replace(form, HOME)
    # Another account's home (a path copied from elsewhere, a different HOME under launchd) names a person too.
    text = _OTHER_HOME.sub(lambda m: "/" + m.group(0).split("/")[1] + "/[user]", text)
    text = _URL.sub(URL, text)
    text = _WWW.sub(URL, text)
    text = _EMAIL.sub(EMAIL, text)
    text = _REQUEST.sub(lambda m: f"\"{m.group(1)} {m.group(2)}{'/…' if m.group(3) else ''}{m.group(4) or ''}\"",
                        text)
    text = _WIKILINK.sub("[[…]]", text)
    text = _BANK_PATH.sub(lambda m: f"{m.group(1)}/…", text)
    for name in sorted({str(n).strip() for n in bank_names if len(str(n).strip()) >= 2}, key=len, reverse=True):
        text = re.sub(rf"(?<![\w-]){re.escape(name)}(?![\w-])", BANK, text)

    def quoted(m: re.Match) -> str:
        body = m.group("body")
        if _REQUEST.fullmatch(m.group(0)) or body in (TEXT, URL, EMAIL, BANK):
            return m.group(0)
        return f"{m.group('q')}{TEXT}{m.group('q')}"

    return _QUOTED.sub(quoted, text)


def _cut(line: str) -> str:
    return line if len(line) <= MAX_LINE else line[: MAX_LINE - 1] + "…"


def tail(path: Path, lines: int) -> list[str]:
    """The last ``lines`` lines of a log file, decoded leniently; none when it is missing or unreadable."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            return [line.rstrip("\n") for line in deque(fh, maxlen=max(0, lines))]
    except OSError:
        return []


def log_dirs(cicada_home: Path, repo: Path | None = None) -> list[Path]:
    """Where a backend's output lands: ``$CICADA_LOG_DIR`` (launchd and the server unit), ``$CICADA_HOME/logs`` (the
    app's own spawn, a release's agent), and a developer checkout's ``logs/``. Fixed places only — never a path a
    request names."""
    dirs: list[Path] = []
    if os.environ.get("CICADA_LOG_DIR"):
        dirs.append(Path(os.environ["CICADA_LOG_DIR"]).expanduser())
    dirs.append(Path(cicada_home) / "logs")
    if repo is not None:
        dirs.append(Path(repo) / "logs")
    seen: list[Path] = []
    for d in dirs:
        if d not in seen:
            seen.append(d)
    return seen


def newest(dirs: Iterable[Path], names: Iterable[str]) -> Path | None:
    """The most recently written of ``names`` across ``dirs``."""
    found = []
    for d in dirs:
        for name in names:
            p = d / name
            try:
                found.append((p.stat().st_mtime, str(p), p))
            except OSError:
                continue
    return max(found)[2] if found else None


def recent_errors(lines: list[str], limit: int = RECENT_ERRORS) -> list[str]:
    return [line for line in lines if _LEVEL.search(line)][-limit:]


def build(*, version: str, engine_mode: str, sources_on: Iterable[str], bank_count: int, bank_names: Iterable[str],
          home: str | os.PathLike | None, dirs: Iterable[Path], lines: int = DEFAULT_LINES) -> str:
    """The backend half of the report, as plain text (the app adds its own lines on top)."""
    lines = max(1, min(int(lines), MAX_LINES))
    dirs = list(dirs)
    banks = list(bank_names)

    def clean(raw: list[str]) -> list[str]:
        return [_cut(redact(line, home=home, bank_names=banks)) for line in raw]

    backend_path = newest(dirs, BACKEND_LOGS)
    app_path = newest(dirs, APP_LOGS)
    backend = clean(tail(backend_path, lines)) if backend_path else []
    app = clean(tail(app_path, lines)) if app_path else []
    errors = recent_errors(backend)
    mac = platform.mac_ver()[0]
    system = f"macOS {mac}" if mac else f"{platform.system()} {platform.release()}"
    on = sorted({str(s) for s in sources_on if s})
    out = [
        f"Backend: {version}",
        f"Platform: {system} ({platform.machine()}), Python {platform.python_version()}",
        f"Engine mode: {engine_mode or 'unknown'}",
        f"Sources on: {', '.join(on) if on else 'none'}",
        f"Memories (banks): {bank_count}",
        "",
        f"Recent warnings and errors ({len(errors)}):",
        *(errors or ["(none)"]),
        "",
        f"Backend log, last {len(backend)} lines ({backend_path.name if backend_path else 'not found'}):",
        *(backend or ["(empty)"]),
        "",
        f"App log, last {len(app)} lines ({app_path.name if app_path else 'not found'}):",
        *(app or ["(empty)"]),
    ]
    return "\n".join(out) + "\n"
