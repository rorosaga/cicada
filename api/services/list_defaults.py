"""Saved lists on by default, for an existing install (owner 2026-10-26; ruling 39's dated line; G71, G206).

Owner: "By default the user should have them all on. Re-reading my saved stuff should be the default." A new install
is asked once, in onboarding, with every list pre-ticked — that answer is the consent and is stored as explicit ons and
offs. An install that predates the question gets the same default here, narrowly:

* only once agent reading counts (its first-use sheet acknowledged, the master switch not turned off) — that
  acknowledgement already named the platforms' terms, and nothing is read without it;
* only for an account this memory already shows — an export, a watched day, an earlier list read
  (:data:`ACCOUNT_ORIGINS`) — so nobody without an Instagram account gets a weekly "sign in to Instagram" request;
* never over the person's own choice: a list with an on or off on record is left alone, and a list an agent read
  before that holds no switch now was turned off before offs were recorded, so it is recorded off.

Called from ``GET /reading/settings`` (the Sources page and the Agents page read it), off the event loop. One pass
over the bank's cached episode headers (``bank_index``); nothing is fetched and no bank file is written.
"""
from __future__ import annotations

from pathlib import Path

from api.services import bank_index, reading_settings, saved_lists, youtube_lists

#: The episode origins that show the person has an account there.
ACCOUNT_ORIGINS: dict[str, frozenset[str]] = {
    "youtube": frozenset({"youtube-playlist", "youtube-history"}),
    "x": frozenset({"x-bookmarks", "x-likes"}),
    "instagram": frozenset({"instagram-saved"}),
    "linkedin": frozenset({"linkedin-saved"}),
}


def detected(memory_path: Path) -> set[str]:
    """The accounts (``youtube``, ``x``, ``instagram``, ``linkedin``) this memory holds anything from."""
    wanted = {origin: account for account, origins in ACCOUNT_ORIGINS.items() for origin in origins}
    found: set[str] = set()
    try:
        entries = bank_index.files(Path(memory_path), "episodes")
    except OSError:
        return found
    for entry in entries:
        account = wanted.get(str((entry.frontmatter or {}).get("origin") or ""))
        if account:
            found.add(account)
            if len(found) == len(ACCOUNT_ORIGINS):
                break
    return found


def read_before() -> set[str]:
    """``family:key`` for every list an agent recorded an outcome for, in any memory on this machine."""
    out: set[str] = set()
    for family, module in (("youtube", youtube_lists), ("saved", saved_lists)):
        banks = module._load().get("banks")
        if not isinstance(banks, dict):
            continue
        for entries in banks.values():
            if isinstance(entries, dict):
                out.update(f"{family}:{key}" for key in entries)
    return out


def apply(memory_path: Path) -> list[str]:
    """Turn on the never-decided lists of accounts this memory shows (see the module doc). Cheap when nothing is
    left to decide: no bank read once every list has a recorded choice or the sheet is not acknowledged."""
    if not reading_settings.agent_enabled():
        return []
    decided = (set(reading_settings.youtube_lists()) | set(reading_settings.youtube_lists_off())
               | {f"s:{k}" for k in reading_settings.saved_lists()} | {f"s:{k}" for k in reading_settings.saved_lists_off()})
    if len(decided) >= len(reading_settings.YOUTUBE_LISTS) + len(reading_settings.SAVED_LISTS):
        return []
    # A list turned on here was never read, so it holds no pause to lift.
    return reading_settings.apply_list_defaults(detected=detected(memory_path), read_before=read_before())
