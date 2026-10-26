"""Report a problem (tester readiness, 2026-10-26): the text a person reads, then copies, saves or sends.

``GET /diagnostics/report`` builds it; the app puts its own version, build and macOS version on top and shows the
whole thing in a sheet before anything leaves the Mac. Nothing here sends anything, and nothing is persisted.

What it holds: the backend's version, the platform, the engine mode (an enum — never an account or an email, G148),
which sources are connected (channel ids only), the bank count (never a name), recent warnings and errors, and the
tail of the backend's and the app's own logs. What it must never hold: bank content, page names, episode text, URLs,
emails, or a path under anyone's home.

Logs are free text, so redaction is layered rather than pattern-by-pattern (review of #482):

1. **Known names first.** :class:`Redactor` is built once per report from what the backend knows: every page id, name
   and alias in the active bank, every name waiting in ``pending_store``, and the banks' names. Every one of them is
   replaced wherever it appears as a token, and anything in parentheses after one goes too.
2. **Shapes that name something.** URLs (stopped only at whitespace or a quote), ``www.`` hosts, emails (after
   %-decoding), file names (``*.md``, ``*.claims.jsonl``, ``*.jsonl``, ``*.yaml``), the home path and any other
   account's (POSIX with spaces, and Windows ``C:\\Users\\…``), bank-relative paths, wikilinks, quoted text, a
   capitalised phrase in parentheses, ids in request paths, and any hyphenated slug (the shape of a page id) not on the
   keep list (channel and agent ids).
3. **Withhold what still looks risky.** Every line is checked after redaction: if a known name, a URL, an email or a
   ``@`` survives, the line keeps only its structure — time, level, logger, exception class, file:line — and its
   message becomes ``[message withheld]``.

The person still reads the report before sending; the sheet says so.
"""
from __future__ import annotations

import os
import platform
import re
from collections import deque
from collections.abc import Iterable
from pathlib import Path
from urllib.parse import unquote

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
NAME = "[name]"
FILE = "[file]"
SLUG = "[id]"
TEXT = "[…]"
WITHHELD = "[message withheld]"

#: Cicada's own files, named the same in every bank: never personal, kept so a report can say which one failed.
OWN_FILES = frozenset({
    "settings.yaml", "banks.yaml", "_state.md", "_index.md", "_bank.yaml", "predicates.yaml", "owner.json",
    "pending_entities.jsonl", "telemetry.jsonl",
})

_URL = re.compile(r"\b[a-zA-Z][a-zA-Z0-9+.-]*://[^\s\"'<>]+")
_WWW = re.compile(r"\bwww\.[^\s\"'<>]+", re.IGNORECASE)
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Another account's home: up to the next slash (a name with a space included), else up to whitespace.
_OTHER_HOME = re.compile(r"/(Users|home)/(?:[^/\n\"']+(?=/)|[^/\s\"']+)")
_WINDOWS_HOME = re.compile(r"\b([A-Za-z]:[\\/](?:Users|Documents and Settings)[\\/])(?:[^\\/\n\"']+(?=[\\/])|[^\\/\s\"']+)",
                           re.IGNORECASE)
_FILE = re.compile(r"(?<![\w.@+-])[\w@+.-]+\.(claims\.jsonl|jsonl|md|ya?ml)\b")
_WIKILINK = re.compile(r"\[\[[^\]]*\]\]")
# A bank's own folders: what follows names a page, a conversation or an item.
_BANK_PATH = re.compile(r"\b(entities|episodes|hubs|inbox|backlog|captures|skills|design|_sites)/[^\s\"',;:)\]]+")
# uvicorn's access line: `"GET /entities/<id>/card HTTP/1.1" 200` — the route's first segment says what was asked;
# the rest is an id (a page, a conversation), so it goes.
_REQUEST = re.compile(r"\"(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS) (/[^/\s?\"]*)([^\s\"]*)( HTTP/[0-9.]+)?\"")
_QUOTED = re.compile(r"(?P<q>['\"“‘])(?P<body>[^'\"“”‘’\n]{1,400})(?:['\"”’])")
_CAPS_PARENS = re.compile(r"\((?:[A-Z][\w'’.-]*)(?:\s+[A-Z][\w'’.-]*){0,5}\)")
_AFTER_NAME = re.compile(re.escape(NAME) + r"\s*\([^)\n]*\)")
# A page id's shape: lower-case words joined by hyphens, at least one letter (never a date or a version).
_SLUG = re.compile(r"(?<![\w./@-])(?=[a-z0-9-]*[a-z])[a-z0-9]+(?:-[a-z0-9]+)+(?![\w/@-])")
_LEVEL = re.compile(r"\|\s*(WARNING|ERROR|CRITICAL)\s*\||^(?:WARNING|ERROR|CRITICAL):|Traceback \(most recent call last\)")
# The structure a withheld line keeps.
_LOGURU = re.compile(r"^(\S+\s*\|\s*\w+\s*\|\s*[\w.]+\s*(?:—|-)\s*)")
_UVICORN = re.compile(r"^((?:INFO|WARNING|ERROR|CRITICAL|DEBUG):\s+)")
_EXCEPTION = re.compile(r"^(\s*[A-Za-z_][\w.]*(?:Error|Exception|Warning|Exit|Interrupt)\b:?\s*)")
_FRAME = re.compile(r'^(\s*File "[^"]*", line \d+(?:, in \w+)?)')


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


def _alternation(words: Iterable[str]) -> re.Pattern | None:
    clean = sorted({w.strip() for w in words if w and len(w.strip()) >= 3}, key=len, reverse=True)
    if not clean:
        return None
    body = "|".join(re.escape(w) for w in clean)
    return re.compile(rf"(?<![\w-])(?:{body})(?![\w-])", re.IGNORECASE)


class Redactor:
    """Built once per report: the known names compiled into one pattern, then :meth:`line` per log line."""

    def __init__(self, *, home: str | os.PathLike | None = None, names: Iterable[str] = (),
                 bank_names: Iterable[str] = (), keep: Iterable[str] = ()):
        self.homes = _home_forms(home)
        self.names = {n.strip().lower() for n in names if n and len(n.strip()) >= 3}
        self.banks = {b.strip() for b in bank_names if b and len(b.strip()) >= 2}
        self.keep = {k.strip().lower() for k in keep if k}
        self._names = _alternation(self.names)
        self._distinctive = {n for n in self.names if len(n) >= 5 and ("-" in n or " " in n)}
        banks = sorted(self.banks, key=len, reverse=True)
        self._banks = re.compile(rf"(?<![\w-])(?:{'|'.join(re.escape(b) for b in banks)})(?![\w-])") if banks else None

    def redact(self, text: str) -> str:
        text = unquote(text or "")                     # %-encoded emails, names and paths read as themselves
        # URLs before the secret scrub: a `[redacted]` inside a query must not cut the URL short.
        text = _URL.sub(URL, text)
        text = _WWW.sub(URL, text)
        text, _ = episode_scrub.scrub(text)
        for form in self.homes:
            text = text.replace(form, HOME)
        text = _OTHER_HOME.sub(lambda m: f"/{m.group(1)}/[user]", text)
        text = _WINDOWS_HOME.sub(lambda m: f"{m.group(1)}[user]", text)
        text = _EMAIL.sub(EMAIL, text)
        text = _REQUEST.sub(lambda m: f"\"{m.group(1)} {m.group(2)}{'/…' if m.group(3) else ''}{m.group(4) or ''}\"",
                            text)
        text = _WIKILINK.sub("[[…]]", text)
        text = _BANK_PATH.sub(lambda m: f"{m.group(1)}/…", text)
        text = _FILE.sub(lambda m: m.group(0) if m.group(0) in OWN_FILES else f"{FILE}.{m.group(1)}", text)
        if self._banks:
            text = self._banks.sub(BANK, text)
        if self._names:
            text = self._names.sub(NAME, text)
        text = _AFTER_NAME.sub(f"{NAME} ({TEXT})", text)
        text = _CAPS_PARENS.sub(f"({TEXT})", text)
        text = _SLUG.sub(lambda m: m.group(0) if m.group(0) in self.keep else SLUG, text)

        def quoted(m: re.Match) -> str:
            body = m.group("body")
            # A traceback's code location (`File ".../api/services/x.py"`) is kept: file:line is what a report needs,
            # and a home in it is already `~`.
            if _REQUEST.fullmatch(m.group(0)) or body in (TEXT, URL, EMAIL, BANK, NAME, SLUG) or \
                    re.fullmatch(r"[^\s\"']+\.py", body):
                return m.group(0)
            return f"{m.group('q')}{TEXT}{m.group('q')}"

        return _QUOTED.sub(quoted, text)

    def leaks(self, text: str) -> bool:
        """Whether a redacted line still carries something that names a person, a page or a place."""
        low = text.lower()
        if "@" in text or "://" in text or "www." in low or _EMAIL.search(text):
            return True
        if (self._names and self._names.search(text)) or (self._banks and self._banks.search(text)):
            return True
        # A distinctive name (a page id or a full name) inside a longer token: `alice-smiths`, `xalice-smith`.
        return any(name in low for name in self._distinctive)

    def line(self, raw: str) -> str:
        """One log line for the report: redacted, or — if anything risky survives — its structure alone."""
        text = self.redact(raw)
        if not self.leaks(text):
            return text
        for shape in (_FRAME, _LOGURU, _UVICORN, _EXCEPTION):
            if m := shape.match(text):
                kept = m.group(1)
                return kept if shape is _FRAME else f"{kept.rstrip()} {WITHHELD}"
        return WITHHELD


def redact(text: str, *, home: str | os.PathLike | None = None, bank_names: Iterable[str] = (),
           names: Iterable[str] = (), keep: Iterable[str] = ()) -> str:
    """One text, redacted (a one-off :class:`Redactor`); :func:`build` keeps one for the whole report."""
    return Redactor(home=home, names=names, bank_names=bank_names, keep=keep).redact(text)


def bank_names_known(memory_path: Path) -> set[str]:
    """Every page id, name and alias in the bank and every name waiting to become a page — what redaction removes."""
    from api.services import bank_index, pending_store

    known: set[str] = set()
    for f in bank_index.files(memory_path, "entities"):
        fm = f.frontmatter or {}
        known.add(f.stem)
        for key in ("id", "name", "title"):
            if isinstance(fm.get(key), str):
                known.add(fm[key])
        for alias in fm.get("aliases") or []:
            if isinstance(alias, str):
                known.add(alias)
    try:
        for entry in pending_store.load(memory_path):
            known.add(entry.name)
            known.update(a for a in (entry.aliases or []) if isinstance(a, str))
    except Exception:   # a damaged store never stops the report
        pass
    return {k for k in known if k}


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
          home: str | os.PathLike | None, dirs: Iterable[Path], lines: int = DEFAULT_LINES,
          names: Iterable[str] = (), keep: Iterable[str] = ()) -> str:
    """The backend half of the report, as plain text (the app adds its own lines on top). ``names`` are the bank's
    known page ids, names and aliases (:func:`bank_names_known`); ``keep`` the ids a report may name (channels,
    agents)."""
    lines = max(1, min(int(lines), MAX_LINES))
    dirs = list(dirs)
    on = sorted({str(s) for s in sources_on if s})
    redactor = Redactor(home=home, names=names, bank_names=bank_names, keep=set(keep) | set(on))

    def clean(raw: list[str]) -> list[str]:
        return [_cut(redactor.line(line)) for line in raw]

    backend_path = newest(dirs, BACKEND_LOGS)
    app_path = newest(dirs, APP_LOGS)
    backend_raw = tail(backend_path, lines) if backend_path else []
    backend = clean(backend_raw)
    app = clean(tail(app_path, lines)) if app_path else []
    errors = clean(recent_errors(backend_raw))
    mac = platform.mac_ver()[0]
    system = f"macOS {mac}" if mac else f"{platform.system()} {platform.release()}"
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
