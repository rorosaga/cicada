"""One scrub for every episode writer (R-N3 · R3 P3 · extends G114).

Until this module the secret scrub ran in exactly one place —
``transcript_extract._Builder._add`` (G105 R6) — so a key pasted into a chat
export, a passcode in a calendar invite, or a one-time code dictated into a
note-taker reached the bank verbatim through every OTHER writer. G114 made
"one rule for every writer" the house shape for ids and clocks; this is the
same move for the one thing that must never be stored.

Two families, applied in order:

* **Secrets** — the G105 R6 rules, moved here verbatim from
  ``transcript_extract`` (API keys, bearer tokens, vendor prefixes, JWTs, PEM
  blocks, ``key=value`` credentials, long hex/base64 runs).
  ``transcript_extract.scrub_secrets`` is now :func:`scrub`, so the Stop-hook
  path and every other writer cannot drift apart.
* **One-time codes** (R-LS5) — a 4–8 digit number joined to a code keyword by
  a short connector (``is``/``was``, ``:``, ``=``, ``#``, ``-`` or plain
  whitespace), in either order: "code: 482913", "482913 is your verification
  code". Only the digits are replaced, so the sentence still says a code was
  sent. The connector grammar replaces R3's "within ~24 characters" window on
  purpose: a raw window also ate years in ordinary prose ("wrote code in 2019").

Pure and engine-free. :func:`record` adds one ``capture`` ledger row when
something was replaced — a writer enum and a count, never what was replaced
(the transcript path records its own count in ``transcript_capture._record``).
"""

from __future__ import annotations

import re

REDACTED = "[redacted]"

#: The writer enums a ``capture`` row may carry — ids and enums only (R-LS6).
WRITERS = frozenset({
    "import", "folder", "wispr-flow", "telegram", "media", "apple-notes",
    "calendar", "mcp", "demo",
    "backlog",  # G150 R-B10: a backlog item's title, description and notes
    "tab-groups",  # G160 (round 4): a Chrome tab group's name and its tabs' titles and links
    "video_queue",  # G162: a release reason an agent wrote for a video it could not do
    "note",  # G212: a note a paired device sent (`/capture/note`)
    "file",  # G91: a photo or file a paired device sent (`/capture/file`) — its caption and name, a text file's words
    "saved-why",  # G191: the person's answer to "what made you save this?"
    "imessage",  # G179: a ticked Messages conversation's words, both sides
    "whatsapp",  # G179 (2026-10-28): a ticked WhatsApp chat's words, every speaker
    "telegram-chats",  # ruling 47a: a ticked Telegram chat's words, every speaker
    "watch-history",  # G71 (2026-10-16): a watched video's title and channel, one day's episode
    "linkedin-connections",  # 2026-10-16: a connection's name, company and position; a profile read's quotes
    "reminders",  # G219: a reminder's title and notes, from the lists the person ticked
    "linear",  # ROR-115: a Linear issue and its comments, every author's words
    "notion",  # G219: a Notion export's pages and database rows
    "agent-memory",  # ruling 43: an agent's own memory notes, posted by the harness's hook
    "readwise",  # ruling 47 tier 2: Readwise highlights, their notes and their documents
    "github",  # G230: a repository the person owns — its name, description and topics
    "listening-history",  # G32: a Spotify listening day's titles, artists and albums
    "project",  # G222 (review of #595, B2): a project's description, the person's own paragraphs, from every door
})

# Secret shapes (G105 R6), moved verbatim from transcript_extract. Ordered
# longest-context first so a PEM block is taken whole before its base64 body
# is chewed up piecemeal. The hex and base64 runs are deliberately long
# (32 / 64) so a short git SHA or an ordinary word survives; a base64
# candidate with three or more ``/`` is a path, not a token, and is kept.
#
# **A word boundary is not a name boundary (2026-11-06).** ``\b`` does not fall between ``_`` and a letter, so
# ``\bpassword`` never matched inside ``DB_PASSWORD`` and ``AWS_SECRET_ACCESS_KEY=…`` was stored whole. A prefix now
# starts after anything that is not a letter or digit (:data:`_START`), and an assignment's NAME may carry any prefix.
_START = r"(?<![A-Za-z0-9])"
_PASS_RES: tuple[re.Pattern[str], ...] = tuple(re.compile(p, f) for p, f in (
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL),
    (_START + r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}", 0),
    (_START + r"bearer\s+[A-Za-z0-9._~+/=-]{16,}", re.IGNORECASE),
))
#: A vendor's prefix and a random tail. A tail that is a placeholder (``sk-your-key-here-…``, ``sk_live_xxxx…``) is a
#: documentation example, not a key, and is kept (:func:`placeholder_value`).
_KEY_RES: tuple[re.Pattern[str], ...] = tuple(re.compile(p) for p in (
    _START + r"sk-[A-Za-z0-9_-]{16,}",
    _START + r"(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}",
    _START + r"github_pat_[A-Za-z0-9_]{20,}",
    _START + r"xox[abopr]s?-[A-Za-z0-9-]{10,}",
    _START + r"AKIA[0-9A-Z]{16}\b",
    _START + r"AIza[0-9A-Za-z_-]{30,}",
    # Vendor shapes `sensitive_text` already reported but this scrub did not take (2026-11-06): a live Stripe key, and the
    # other prefixes that carry a long random tail. A prefix alone is never enough, so each wants its tail.
    _START + r"[sr]k_live_[A-Za-z0-9]{16,}",
    _START + r"glpat-[A-Za-z0-9_-]{16,}",
    _START + r"npm_[A-Za-z0-9]{30,}",
    _START + r"hf_[A-Za-z0-9]{30,}",
    _START + r"SG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}",
    _START + r"xai-[A-Za-z0-9]{30,}",
    _START + r"gsk_[A-Za-z0-9]{30,}",
    _START + r"pplx-[A-Za-z0-9]{30,}",
))
_HEX_RE = re.compile(r"\b[0-9a-fA-F]{32,}\b")

# ``NAME = value`` where NAME says what it holds. A BARE name (``password``, ``api_key``…) keeps G105's rule: 12+ value
# characters, nothing else asked. A PREFIXED name (``DB_PASSWORD``, ``AWS_SECRET_ACCESS_KEY``, ``stripe_secret``) is
# unmistakable as a variable, so it takes the wider list of keywords and a shorter value, but the value must look like a
# secret rather than a word (:func:`_secret_like`). The value is one token, bare or quoted; a quoted sentence is prose
# ("password: 'ask the admin'") and stays. The name and the separator are kept, so the line still says what was set.
_BARE_KEYWORD = r"api[_-]?key|access[_-]?token|secret[_-]?key|client[_-]?secret|password|passwd|token"
_ANY_KEYWORD = (_BARE_KEYWORD + r"|apikey|api[_-]?secret|access[_-]?key|secret[_-]?access[_-]?key|private[_-]?key"
                r"|auth[_-]?token|refresh[_-]?token|pwd|secret")
_BARE_NAME_RE = re.compile(rf"(?:{_BARE_KEYWORD})", re.IGNORECASE)
_ASSIGN_RE = re.compile(
    _START + rf"(?P<name>(?:[A-Za-z0-9]+[_-])*(?:{_ANY_KEYWORD}))(?P<close>[\"']?)(?P<sep>\s*[=:]\s*)"
    r"(?:(?P<q>[\"'`])(?P<qv>[^\s\"'`]{8,200})(?P=q)|(?P<v>[^\s\"'`,;]{8,}))", re.IGNORECASE)

#: ``scheme://user:PASSWORD@host``: the password of a connection URL, whatever the scheme. The user may be empty
#: (``redis://:pw@host``).
_URL_CRED_RE = re.compile(r"(?P<head>\b[a-z][a-z0-9+.-]*://[^\s:/@]*:)(?P<value>[^\s/@]{2,})(?=@)", re.IGNORECASE)
#: What a local connection string says when it has no password worth keeping: every README's ``postgres://postgres:postgres@``.
_URL_DEFAULTS = frozenset({"postgres", "postgresql", "mysql", "root", "redis", "mongo", "mongodb", "guest", "rabbitmq",
                           "localhost", "pass", "password", "pwd", "user", "admin", "secret", "changeme"})

#: A word that makes a value a placeholder when it is a whole segment of it (``your_api_key_here``,
#: ``example-password``), never when it is a piece of a longer word.
_PLACEHOLDER_SEGMENTS = frozenset({
    "your", "yours", "example", "sample", "dummy", "fake", "placeholder", "changeme", "replace", "redacted", "insert",
    "here", "todo", "tbd", "undefined", "xxx", "xxxx", "yourkey", "mykey",
})
#: Words that make a *variable's* value a placeholder (``DB_PASSWORD=password``) but say nothing about a vendor key: a
#: key a person pasted that begins ``sk-test…`` is still theirs to lose.
_WEAK_PLACEHOLDER_SEGMENTS = frozenset({
    "password", "passwd", "secret", "token", "key", "value", "string", "none", "null", "test", "testing", "foo", "bar", "baz",
})
_CODE_VALUE_RE = re.compile(r"[()\[\]{}<>\\|]|^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+$")
_VALUE_OPENERS = ("$", "<", "{", "%", "[", "(", "*", "•", "#", "@", "/", "~")


def placeholder_value(value: str, *, vendor: bool = False) -> bool:
    """Is this value a stand-in rather than a secret: a variable reference (``$DB_PASSWORD``, ``${…}``, ``%PW%``), a
    template (``<password>``), a mask (``****``, ``[redacted]``), an expression (``process.env.KEY``, ``getpass()``),
    ``x``-runs, one repeated character, or a name made of placeholder words (``your_api_key_here``, ``changeme``)?
    A trailing counter does not make it a secret (``password123``, ``changeme2``). ``vendor=True`` is for a key with a
    vendor's prefix: no code tests (``SG.…`` has dots) and only the plainly empty words count, not ``test`` or ``secret``. Shared with `sensitive_text`, so the scrub and the
    finder agree on what a placeholder is."""
    value = (value or "").strip().strip("\"'`")
    if not value or value.startswith(_VALUE_OPENERS) or "redacted" in value.lower():
        return True
    if "***" in value or "..." in value or "…" in value or "•" in value or (not vendor and _CODE_VALUE_RE.search(value)):
        return True
    if len(value) >= 6 and len(set(value.lower())) <= 2:        # "aaaaaa", "ababab"; a two-letter password is still one
        return True
    segments = [seg for seg in (s.rstrip("0123456789") for s in re.split(r"[_\-. ]+", value.lower())) if seg]
    words = _PLACEHOLDER_SEGMENTS if vendor else _PLACEHOLDER_SEGMENTS | _WEAK_PLACEHOLDER_SEGMENTS
    return bool(segments) and any(seg in words or set(seg) == {"x"} and len(seg) >= 3 for seg in segments)


def _secret_like(value: str) -> bool:
    """A digit, mixed case or a symbol: what a generated secret has and a word does not."""
    return (any(c.isdigit() for c in value) or (any(c.islower() for c in value) and any(c.isupper() for c in value))
            or any(c in "+/=~!@#%^&*" for c in value))


def _scrub_keys(text: str) -> tuple[str, int]:
    count = 0

    def sub(m: re.Match[str]) -> str:
        nonlocal count
        if placeholder_value(m.group(0), vendor=True):
            return m.group(0)
        count += 1
        return REDACTED

    for rx in _KEY_RES:
        text = rx.sub(sub, text)
    return text, count


def _scrub_assignments(text: str) -> tuple[str, int]:
    count = 0

    def sub(m: re.Match[str]) -> str:
        nonlocal count
        quoted = m.group("q") is not None
        value = m.group("qv") if quoted else m.group("v")
        if _BARE_NAME_RE.fullmatch(m.group("name")):
            # Unquoted keeps G105's 12; a quoted value (JSON, YAML, a .env) is a value for certain, so 8 and not a word.
            if placeholder_value(value) or (len(value) < 12 and not (quoted and _secret_like(value))):
                return m.group(0)
        elif placeholder_value(value) or not _secret_like(value):
            return m.group(0)
        count += 1
        q = m.group("q") or ""
        return f"{m.group('name')}{m.group('close')}{m.group('sep')}{q}{REDACTED}{q}"

    return _ASSIGN_RE.sub(sub, text), count


def _scrub_url_credentials(text: str) -> tuple[str, int]:
    count = 0

    def sub(m: re.Match[str]) -> str:
        nonlocal count
        value = m.group("value")
        if (value.casefold() in _URL_DEFAULTS or (value.isdigit() and len(value) <= 5)   # a port, not a password
                or placeholder_value(value)):
            return m.group(0)
        count += 1
        return m.group("head") + REDACTED

    return _URL_CRED_RE.sub(sub, text), count


_BASE64_RUN_RE = re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{64,}={0,2}(?![A-Za-z0-9+/])")

_OTP_KEYWORD = (
    r"(?:one[- ]time\s+(?:pass)?code|verification\s+code|security\s+code|login\s+code"
    r"|sign[- ]in\s+code|auth(?:entication)?\s+code|confirmation\s+code"
    r"|2fa(?:\s+code)?|otp|passcode|pin|code)"
)
_OTP_FORWARD_RE = re.compile(
    rf"\b{_OTP_KEYWORD}(?:\s+(?:is|was))?\s*[:=#-]?\s*(?P<digits>\d{{4,8}})\b", re.IGNORECASE)
_OTP_REVERSE_RE = re.compile(
    rf"\b(?P<digits>\d{{4,8}})\s+is\s+(?:your|the)\s+(?:[A-Za-z]+\s+){{0,2}}{_OTP_KEYWORD}\b",
    re.IGNORECASE)


def _scrub_base64(m: re.Match[str]) -> str:
    return m.group(0) if m.group(0).count("/") >= 3 else REDACTED


def _redact_digits(m: re.Match[str]) -> str:
    start, end = m.span("digits")
    whole, base = m.group(0), m.start()
    return whole[: start - base] + REDACTED + whole[end - base:]


def _named(text: str) -> tuple[str, int]:
    """Every NAMED secret shape — the vendor prefixes, a connection URL's password, a ``NAME=value`` credential — and
    not the bare hex / base64 runs (a content hash, a device id legitimately is one)."""
    count = 0
    for rx in _PASS_RES:
        text, n = rx.subn(REDACTED, text)
        count += n
    for step in (_scrub_keys, _scrub_url_credentials, _scrub_assignments):
        text, n = step(text)
        count += n
    return text, count


def scrub(text: str) -> tuple[str, int]:
    """Redact secrets, then one-time codes. Returns ``(text, replacements)`` —
    a count for the ledger, never what was replaced."""
    text, count = _named(text or "")
    text, n = _HEX_RE.subn(REDACTED, text)
    count += n
    # The base64 pass keeps path-like runs (three or more ``/``), so count
    # only the matches that were actually replaced — ``subn`` would count
    # every match, kept or not.
    count += sum(1 for m in _BASE64_RUN_RE.finditer(text) if m.group(0).count("/") < 3)
    text = _BASE64_RUN_RE.sub(_scrub_base64, text)
    for rx in (_OTP_FORWARD_RE, _OTP_REVERSE_RE):
        text, n = rx.subn(_redact_digits, text)
        count += n
    return text, count


#: Frontmatter keys that are keys, paths or ids: a writer and its readers match on them byte for byte (a folder's
#: `relpath` against its globs, a chat's message keys), so they are never altered — re-check of #560: a year in a
#: folder path became "[redacted]" and the person's authorship rule stopped matching the file.
_KEY_FIELDS = frozenset({"relpath", "path", "paths", "source_id", "conversation", "conversation_id", "message_keys",
                         "jid", "jids", "id", "ids", "file", "files", "project", "hash", "sha", "session_id",
                         "origin_session_id", "origin_episode", "device", "harness", "origin", "source"})
_KEY_SUFFIXES = ("_id", "_ids", "_key", "_keys", "_path", "_paths", "_hash", "_sha", "relpath")


def _is_key_field(name) -> bool:
    name = str(name or "").lower()
    return name in _KEY_FIELDS or name.endswith(_KEY_SUFFIXES)


def _is_url_field(name) -> bool:
    name = str(name or "").lower()
    return name in ("url", "urls", "link", "links", "href") or name.endswith(("_url", "_urls"))


def scrub_value(value, *, key=None):
    """``(value, replacements)`` with the strings a writer passes beside the body (``EpisodeDraft.extra``, a title)
    scrubbed of NAMED secret shapes only (``sk-``, ``ghp_``, AWS, JWT, ``token=``/``password=`` values, a connection URL's password …) — review of
    #560: a note's description reached the primer raw. Never the one-time-code rule or the bare hex / base64 runs:
    those ate years in titles ("Advent of Code 2024") and Notion's 32-hex file ids, the "phone scrub erased dates"
    class. ``key`` names the field: a key, path or id field (:data:`_KEY_FIELDS`) is never altered; a URL field
    keeps its address and loses only a named secret in its query. Other values pass through."""
    if isinstance(value, str):
        if _is_key_field(key):
            return value, 0
        if _is_url_field(key):
            base, sep, query = value.partition("?")
            base, n = _scrub_url_credentials(base)     # ``scheme://user:password@host`` is a secret in an address too
            if not sep:
                return base, n
            query, m = _named(query)
            return base + sep + query, n + m
        return _named(value)
    if isinstance(value, dict):
        out, total = {}, 0
        for k, v in value.items():
            out[k], n = scrub_value(v, key=key if _is_key_field(key) else k)
            total += n
        return out, total
    if isinstance(value, (list, tuple)):
        items, total = [], 0
        for v in value:
            item, n = scrub_value(v, key=key)
            items.append(item)
            total += n
        return (type(value)(items) if isinstance(value, tuple) else items), total
    return value, 0


def record(writer: str, count: int, *, bank: str | None = None) -> None:
    """One ``capture`` ledger row for a write that replaced something. Never
    raises: the ledger must not fail a capture (``telemetry.record`` already
    swallows its own I/O errors; the import guard covers a stripped install)."""
    if count <= 0:
        return
    try:
        from api.services import telemetry

        telemetry.record(telemetry.UsageEvent(
            kind="capture", stage="capture", bank=bank, billing="free", invocations=0,
            refs={"writer": writer if writer in WRITERS else "other", "status": "scrubbed",
                  "scrubbed": int(count)},
        ))
    except Exception:  # noqa: BLE001
        pass


#: The writers whose words are a texted conversation — where a phone number is a person's contact detail, never content
#: to keep (2026-10-28, #502 review B2: a WhatsApp group's @mention is the member's number). Every chat source.
PHONE_WRITERS = frozenset({"imessage", "whatsapp", "telegram-chats"})

# What counts as a phone number, chosen to leave years, prices, dates, times, versions, ids and IP addresses alone:
#  1. ``+`` then 7–15 digits with optional space, hyphen, dot or bracket separators — the international form (E.164 is
#     at most 15 digits); a ``+`` before a digit run is not how a price, a year or an id is written.
#  2. ``@`` then 6–15 digits — a WhatsApp mention, which stores the member's number in the words.
#  3. ``tel:`` / ``wa.me/`` then digits — a link that IS a number.
#  4. A bracketed area code then two groups — "(555) 010-1234", "(020) 7946 0958": the bracket is the phone's own
#     layout, which no date, time, year list, price, SKU or room list has.
#  5. The North American dotted form, exactly 3.3.4 — "555.010.1234" (an IP's 3.3.1.3 is not it).
# **False negatives over lost words** (#502 re-check, 2026-10-29). A scrub runs before storage, so a wrong redaction
# destroys the person's words for good. An unbracketed grouped number ("555 010 1234", "06 12 34 56 78") is therefore
# NOT treated as a phone: the same shape is a timestamp ("2026-10-28 10:30"), a year list ("2024 2025 2026"), a range
# ("1999-2003-2010"), a price ("1 299 000 000"), a SKU ("123-456-789"), a room list or a card-style code, and the
# reviewer's examples all lost real content to it. Nor is a bare run of digits (an order id, a tracking code, a unix
# timestamp). A number written that way in a chat stays; every form a person or WhatsApp writes unambiguously as a
# phone — international "+", a mention, a tel:/wa.me link, a bracketed area code, the dotted NANP form — is caught.
_PHONE_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?<![\w+])\+\(?\d[\d ().\-]{5,22}\d(?!\w)"),
    re.compile(r"(?<![\w@])@\d{6,15}(?!\w)"),
    re.compile(r"(?i)\b(?:tel:|wa\.me/)\+?\d[\d\-]{5,17}\d\b"),
    re.compile(r"(?<![\w+@.\-])\(\d{2,4}\)[ \-]?\d{3,4}[ \-]\d{3,4}(?![\w.\-])"),
    re.compile(r"(?<![\w.])\d{3}\.\d{3}\.\d{4}(?![\w.])"),
)


def plus_numbers(text: str) -> list[tuple[int, int]]:
    """Where a "+" number stands, exactly what :func:`scrub_phones` would blank by that rule: a person's own line keeps it
    as a token instead (`phone_numbers`, ruling 55, 2026-11-05)."""
    return [m.span() for m in _PHONE_RES[0].finditer(text or "") if 7 <= sum(c.isdigit() for c in m.group(0)) <= 15]


def _phone(m: re.Match[str]) -> str:
    digits = sum(c.isdigit() for c in m.group(0))
    keep_at = m.group(0).startswith("@")
    if not 7 <= digits <= 15 or (not keep_at and not m.group(0).startswith(("+", "tel", "TEL", "wa.")) and digits < 9):
        return m.group(0)
    return "@someone" if keep_at else REDACTED


def scrub_phones(text: str) -> tuple[str, int]:
    """Phone numbers out of a chat's words (:data:`PHONE_WRITERS`); ``(text, replacements)``. A mention keeps its
    ``@`` and reads "@someone"."""
    count = 0
    for rx in _PHONE_RES:
        out = rx.sub(_phone, text)
        if out != text:
            count += sum(1 for m in rx.finditer(text) if _phone(m) != m.group(0))
        text = out
    return text, count


def scrub_for(text: str, writer: str | None) -> tuple[str, int]:
    """:func:`scrub`, plus :func:`scrub_phones` for a chat source's words — the one call the stager makes per text, so
    every render of a draft scrubs it the same way."""
    cleaned, n = scrub(text)
    if writer in PHONE_WRITERS:
        cleaned, m = scrub_phones(cleaned)
        n += m
    return cleaned, n


def scrub_body(text: str, *, writer: str, bank: str | None = None) -> str:
    """:func:`scrub_for` + :func:`record`, for a writer that holds one body."""
    cleaned, n = scrub_for(text, writer)
    record(writer, n, bank=bank)
    return cleaned
