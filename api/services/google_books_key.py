"""The person's own Google Books API key (G233, ruling 71 amended 2026-11-08; ruling 47's tier-2 shape).

Google Books is an optional catalogue for a book Open Library could not describe. It runs ONLY with a key the person
made in their own Google Cloud project and pasted in Settings: Cicada ships no key and sends no keyless request, ever.
The key is a credential — ``CICADA_GOOGLE_BOOKS_KEY`` in ``$CICADA_HOME/secrets.env`` (0600), stripped from every engine
child, never returned by any route, never in a bank, a log or a cache entry. Google takes it as ``key=`` on the URL
(its Books docs), so the URL is only ever built at the fetch, never logged (the HTTP client's log is at WARNING and the
fetcher logs a class name, not a URL).

What went wrong last (a refused key, a closed quota) is kept as an enum and a time in ``$CICADA_HOME`` beside the other
connector state — never a body, never the key — so Settings can say the exact fix.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from api.services import book_lookup
from api.services.auth import cicada_home
from api.services.connections import secrets as secrets_store

SECRET_NAME = "CICADA_GOOGLE_BOOKS_KEY"
STATE_FILE = "google-books.json"
#: Where the person makes the key (Google's own Books docs: Credentials page → Create credentials → API key).
KEY_URL = "https://console.cloud.google.com/apis/credentials"
#: Where the Books API is turned on for the key's project.
ENABLE_URL = "https://console.cloud.google.com/apis/library/books.googleapis.com"

#: What Settings says it does. Provider-neutral except naming the source itself (owner 2026-11-08).
WHAT_IT_DOES = ("When Open Library has no description for a book you added without an ISBN, Cicada asks Google Books "
                "once, sending only its title and first author. Read-only; nothing else is sent.")
#: Free by construction (owner 2026-11-08: "make sure the Google books stuff is free"): a project with no billing account
#: cannot be charged, and Google's Books docs name no price. Nothing here claims a daily figure Google does not publish.
FREE_WORDS = ("Free: make the key in a Google Cloud project with no billing account, and Google cannot charge for it. "
              "The key is yours, with Google's own daily cap on requests; Cicada stops for the day when it is reached.")
#: The Books API's quota page for the key's project.
QUOTA_URL = "https://console.cloud.google.com/apis/api/books.googleapis.com/quotas"
PROBLEM_WORDS = {
    "bad_key": ("Google didn't accept this key. Make a new one at " + KEY_URL + " (Create credentials, then API key) "
                "and paste it here."),
    "not_enabled": ("Google refused this key for the Books API: it is turned off for the key's project, or the key is "
                    "restricted to other services. Turn it on at " + ENABLE_URL + ", or allow it in the key's "
                    "restrictions."),
    "quota": ("Google says this key has used its requests for now (the limit is per day). Cicada tries again later and "
              "nothing else is needed; if it never works, check the Books API's quota for the key's project at "
              + QUOTA_URL + "."),
    "unreachable": "Cicada could not reach Google just now. Try again in a moment.",
}
_KEY_RE = re.compile(r"^[A-Za-z0-9_\-]{20,128}$")


class KeyRefused(ValueError):
    """The key was not saved; ``args[0]`` says why in words."""


def key() -> str | None:
    """The saved key, or None. Reads the process environment, which ``secrets.env`` is projected into."""
    value = (os.environ.get(SECRET_NAME) or "").strip()
    return value or None


def _state_path() -> Path:
    return cicada_home() / STATE_FILE


def problem() -> dict | None:
    """``{"kind", "at"}`` for the last refusal or closed quota, or None."""
    try:
        data = json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    kind = data.get("kind") if isinstance(data, dict) else None
    return {"kind": kind, "at": data.get("at")} if kind in PROBLEM_WORDS else None


def note(kind: str | None) -> None:
    """Remember the last problem (an enum and a time), or clear it with None. Never raises."""
    try:
        path = _state_path()
        if kind is None:
            path.unlink(missing_ok=True)
        elif kind in PROBLEM_WORDS:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"kind": kind, "at": datetime.now(timezone.utc).isoformat()}), encoding="utf-8")
    except OSError:
        pass


def status() -> dict:
    """What Settings draws. Never the key."""
    have = key() is not None
    prob = problem() if have else None
    return {"connected": have, "whatItDoes": WHAT_IT_DOES, "freeWords": FREE_WORDS, "keyUrl": KEY_URL,
            "problem": prob["kind"] if prob else None, "problemWords": PROBLEM_WORDS[prob["kind"]] if prob else None,
            "problemAt": prob["at"] if prob else None}


def classify(status_code: int, body: bytes = b"") -> str | None:
    """The problem a Google answer means, or None for an answer that is not one. A 400 counts only when it is about the
    key; any other 400 is the query's."""
    if status_code == 429:
        return "quota"
    if status_code == 403:
        return "not_enabled"
    if status_code == 400 and b"API key" in (body or b""):
        return "bad_key"
    return None


async def connect(candidate: str, *, fetch=None) -> dict:
    """Check ``candidate`` with one read-only request to Google Books and save it only if Google accepts it. Raises
    :class:`KeyRefused` with the words otherwise; nothing is saved then."""
    candidate = (candidate or "").strip()
    if not _KEY_RE.match(candidate):
        raise KeyRefused(PROBLEM_WORDS["bad_key"])
    pacer = book_lookup._shared_pacer()
    await pacer.wait()
    resp = await (fetch or book_lookup.default_fetch)(
        f"{book_lookup.GOOGLE_BOOKS}?q=isbn:9780140328721&maxResults=1&fields=totalItems&key={candidate}")
    if resp.status == 200:
        secrets_store.set_secret(SECRET_NAME, candidate)
        note(None)
        return status()
    kind = classify(resp.status, resp.body) or ("unreachable" if resp.status == 0 else None)
    raise KeyRefused(PROBLEM_WORDS[kind or "unreachable"])


def disconnect() -> dict:
    """Forget the key and the last problem. What Google Books already described stays on its pages."""
    secrets_store.remove_secret(SECRET_NAME)
    note(None)
    return status()
