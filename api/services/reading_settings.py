"""The person's reading settings (G166, spec §7.2): a machine-wide file, never in a bank.

``$CICADA_HOME/reading.json`` (0600, atomic write) — the same home as
``owner.json`` and ``connections.json`` — holds:

* ``agent`` — the master switch, "Let an agent read pages for you". **On by
  default behind the consent sheet** (owner decision 2026-10-22, ruling 36 D6):
  stored only when the person turns it off, and it counts only once the current
  first-use sheet is accepted (``agent_ack``) — until then nothing reads, as
  before. While it is off ``cicada_reading_queue`` returns nothing, the tools
  refuse, and contract item 9 is not in the primer.
* ``agent_sites`` — ``{site: day}``: the sites the person let an agent read with
  their own browser (owner, 2026-09-30: there is no pre-picked list; a site is
  surfaced on Reading in your browser (the Sources page) when Cicada's own reader could not
  read a page of it, and the person turns each on). A standing permission,
  granted per site (``reading_hosts.site_of``); it only counts while the master
  switch is on. Empty by default. The earlier ``agent_hosts`` key is ignored by
  every reader and dropped on the next write: no carry-over, the branch had not
  shipped.
* ``explore_signed_in`` (G166 exploring, owner 2026-10-14, D2 amended) — whether
  an agent exploring saved sites uses the person's everyday signed-in browser
  session. **On by default** (stored only when the person turns it off); off
  means a private, cookie-less browser context. Every capture records which.
* ``never_explore`` — ``{site: day}``: sites the person said never to explore (a
  standing deny, machine-wide, D3).
* ``youtube_lists`` — ``{list: day}`` (G71, owner 2026-10-16): the YouTube lists
  (``watch_later``, ``history``) the person asked their own agent to keep current
  from their signed-in browser (``youtube_lists``). On by default since 2026-10-26 (see ``youtube_lists_off``); each is a
  standing ask for exactly that page (never a youtube.com site grant), needs a current acknowledgement
  to turn on, and counts only while the master switch is on.
* ``saved_lists`` — ``{site: day}`` (G206, redesign 2026-10-22): the saved lists on
  X (Bookmarks), Instagram (Saved) and LinkedIn (Saved posts) the person asked
  their own agent to keep current (``saved_lists``), on the same terms as
  ``youtube_lists``: on by default since 2026-10-26 (see ``saved_lists_off``), a standing ask for exactly that list page,
  never a site grant.
* ``youtube_lists_off`` / ``saved_lists_off`` — ``{key: day}`` (owner 2026-10-26, ruling 39 dated line): the lists
  the person turned OFF. The lists are on by default since then — asked once, pre-ticked, in onboarding (the answer
  is the consent), and on an existing install turned on by :func:`apply_list_defaults` only for an account this memory
  already shows — so an off must be remembered to be respected: nothing automatic ever turns on a list held here.
* ``lists_defaulted`` — ``{key: day}``: the lists :func:`apply_list_defaults` turned on, so it never decides one twice.
* ``agent_ack`` — ``{date, v}``: the person's "I understand" on the first-use
  sheet. Turning the switch on needs a current one; a change of the sheet's
  wording bumps ``ACK_VERSION`` and asks again (until they do, the switch reads
  off).

Read on EVERY call and never cached: the stdio MCP server and the backend are
two processes that both read this file (the split-brain rule — a value one
process cached would outlive the person's own change in the other).
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import date
from pathlib import Path

from api.services import reading_hosts
from api.services.auth import cicada_home

FILENAME = "reading.json"
#: Bump when the first-use sheet's wording changes: every earlier "I understand"
#: stops counting and the person is asked again. (2: the sheet lost its site
#: picker and gained the credentials line. 3, owner 2026-10-14 D3: the exploring
#: paragraph — exploring uses the signed-in session by default, and the person's
#: accounts carry the terms-of-service risk.)
ACK_VERSION = 3


def path() -> Path:
    return cicada_home() / FILENAME


def _load() -> dict:
    try:
        data = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(data: dict) -> None:
    target = path()
    fd, tmp = tempfile.mkstemp(prefix=".reading-", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(data, indent=2, sort_keys=True) + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def mtime() -> float:
    """The file's mtime, 0.0 when absent — the sync component reads it."""
    try:
        return path().stat().st_mtime
    except OSError:
        return 0.0


def agent_enabled() -> bool:
    """On unless the person turned it off — and never before the current sheet is accepted (the ack gate)."""
    return _load().get("agent") is not False and ack_current()


def allowed_sites() -> dict[str, str]:
    """``{site: day granted}`` as stored, in site order. A hand-edited key that is
    not a valid site key grants nothing. NOT gated on the master switch — use
    :func:`site_allowed` to ask whether a site counts right now."""
    raw = _load().get("agent_sites")
    out: dict[str, str] = {}
    if isinstance(raw, dict):
        for key in sorted(raw):
            if isinstance(key, str) and reading_hosts.valid_site_key(key):
                out[key] = str(raw[key] or "")[:10]
    return out


def site_allowed(site: str) -> bool:
    """Does the person's permission for ``site`` count right now? False whenever
    the master switch is off — one place, so every reader agrees."""
    return agent_enabled() and site in allowed_sites()


def ack() -> dict | None:
    raw = _load().get("agent_ack")
    if not isinstance(raw, dict):
        return None
    try:
        version = int(raw.get("v"))
    except (TypeError, ValueError):
        return None
    day = str(raw.get("date") or "")[:10]
    return {"date": day, "v": version} if day else None


def ack_current() -> bool:
    held = ack()
    return held is not None and held["v"] >= ACK_VERSION


def explore_signed_in() -> bool:
    """Does exploring use the person's signed-in browser session? True unless they turned it off (D2 amended)."""
    return _load().get("explore_signed_in") is not False


def never_explore() -> dict[str, str]:
    """``{site: day}`` the person said never to explore, in site order (a bad key denies nothing)."""
    raw = _load().get("never_explore")
    out: dict[str, str] = {}
    if isinstance(raw, dict):
        for key in sorted(raw):
            if isinstance(key, str) and reading_hosts.valid_site_key(key):
                out[key] = str(raw[key] or "")[:10]
    return out


#: The YouTube lists an agent may be asked to read (``youtube_lists.LISTS``' keys).
YOUTUBE_LISTS = ("watch_later", "history")


def youtube_lists() -> dict[str, str]:
    """``{list: day granted}`` as stored. NOT gated on the master switch — see :func:`youtube_list_allowed`."""
    raw = _load().get("youtube_lists")
    if not isinstance(raw, dict):
        return {}
    return {k: str(raw[k] or "")[:10] for k in YOUTUBE_LISTS if k in raw}


def youtube_list_allowed(name: str) -> bool:
    return agent_enabled() and name in youtube_lists()


#: The saved lists on walled sites an agent may be asked to read (G206; ``saved_lists.PLATFORMS``' keys).
SAVED_LISTS = ("x", "instagram", "linkedin")


def saved_lists() -> dict[str, str]:
    """``{site: day granted}`` as stored. NOT gated on the master switch — see :func:`saved_list_allowed`."""
    raw = _load().get("saved_lists")
    if not isinstance(raw, dict):
        return {}
    return {k: str(raw[k] or "")[:10] for k in SAVED_LISTS if k in raw}


def saved_list_allowed(key: str) -> bool:
    return agent_enabled() and key in saved_lists()


def _day_map(raw, keys) -> dict[str, str]:
    return {k: str(raw[k] or "")[:10] for k in keys if k in raw} if isinstance(raw, dict) else {}


def youtube_lists_off() -> dict[str, str]:
    """``{list: day turned off}`` — the person's explicit offs (never turned on by a default)."""
    return _day_map(_load().get("youtube_lists_off"), YOUTUBE_LISTS)


def saved_lists_off() -> dict[str, str]:
    """``{site: day turned off}`` — the person's explicit offs (never turned on by a default)."""
    return _day_map(_load().get("saved_lists_off"), SAVED_LISTS)


def apply_list_defaults(*, detected: set[str], read_before: set[str] = frozenset(),
                        today: date | None = None) -> list[str]:
    """Lists are on by default (owner 2026-10-26): turn on, once, each list the person never decided, for an account
    this memory already shows (``detected``: ``youtube``, ``x``, ``instagram``, ``linkedin``) — and only once agent
    reading counts (its sheet, or onboarding's question, acknowledged; the master switch not turned off), since that
    answer is the consent. A list with an explicit on or off is never touched. ``read_before`` (``youtube:history``,
    ``saved:x``…) names lists an agent read before that hold no on now: the person turned those off before the off was
    recorded, so they are recorded off, never on. Returns the ``family:key`` names changed."""
    data = _load()
    if not (data.get("agent") is not False and _ack_ok(data)):
        return []
    day = (today or date.today()).isoformat()
    changed: list[str] = []
    defaulted = data.get("lists_defaulted") if isinstance(data.get("lists_defaulted"), dict) else {}
    for family, keys, account in (("youtube", YOUTUBE_LISTS, lambda _k: "youtube"),
                                  ("saved", SAVED_LISTS, lambda k: k)):
        on_key, off_key = f"{family}_lists", f"{family}_lists_off"
        on = data.get(on_key) if isinstance(data.get(on_key), dict) else {}
        off = data.get(off_key) if isinstance(data.get(off_key), dict) else {}
        for key in keys:
            name = f"{family}:{key}"
            if key in on or key in off or name in defaulted:
                continue
            if name in read_before:
                off[key] = day
            elif account(key) in detected:
                on[key] = day
                defaulted[name] = day
            else:
                continue
            changed.append(name)
        if on:
            data[on_key] = dict(sorted(on.items()))
        if off:
            data[off_key] = dict(sorted(off.items()))
    if changed:
        if defaulted:
            data["lists_defaulted"] = dict(sorted(defaulted.items()))
        _save(data)
    return changed


def snapshot() -> dict:
    held = ack()
    lists = youtube_lists()
    saved = saved_lists()
    yt_off = youtube_lists_off()
    saved_off = saved_lists_off()
    return {
        "agentEnabled": agent_enabled(),
        "allowedSites": allowed_sites(),
        "ackedAt": held["date"] if held else None,
        "ackCurrent": ack_current(),
        "exploreSignedIn": explore_signed_in(),
        "neverExplore": never_explore(),
        "youtubeLists": {"watchLater": "watch_later" in lists, "history": "history" in lists},
        "savedLists": {k: k in saved for k in SAVED_LISTS},
        # 2026-10-26: the lists the person turned off (an off is remembered; nothing automatic turns it on again).
        "youtubeListsOff": {"watchLater": "watch_later" in yt_off, "history": "history" in yt_off},
        "savedListsOff": {k: k in saved_off for k in SAVED_LISTS},
    }


class SettingsError(ValueError):
    """A change the person's settings refuse, with a sentence they can read."""


def update(*, agent_enabled_: bool | None = None, acknowledge: bool = False, sites=None,
           surfaced=None, today: date | None = None, explore_signed_in_: bool | None = None,
           never_explore_=None, youtube_lists_=None, saved_lists_=None) -> dict:
    """Apply one change and return the new snapshot.

    Turning the switch on needs a current acknowledgement — either already
    stored, or given in this same call (``acknowledge``). ``sites`` is a *patch*
    ``{site: bool}``: True stamps today, False removes; an invalid key refuses
    the whole call, nothing written. A grant (True) for a site that is neither
    currently surfaced (``surfaced``, the sites the reader could not read) nor
    already granted is refused too — a permission for a site nothing has asked
    about would be a pre-picked list through the side door. A grant with no
    current acknowledgement (stored, or given in the same call) is refused with
    the sheet sentence; with one, it is stored even while the switch is off and
    counts once it is on (``site_allowed``). Turning the switch off keeps the
    acknowledgement and the grants (they read as not counting until it is back)."""
    data = _load()
    original = json.loads(json.dumps(data))
    data.pop("agent_hosts", None)  # the pre-picked list is gone; nothing carries over
    if sites is not None:
        if not isinstance(sites, dict):
            raise SettingsError("sites must be a map of site to true or false.")
        bad = sorted(str(k) for k in sites if not reading_hosts.valid_site_key(str(k)))
        if bad:
            raise SettingsError(f"That is not a site name: {', '.join(bad)}. Nothing was changed.")
    if never_explore_ is not None:
        if not isinstance(never_explore_, dict):
            raise SettingsError("neverExplore must be a map of site to true or false.")
        bad = sorted(str(k) for k in never_explore_ if not reading_hosts.valid_site_key(str(k)))
        if bad:
            raise SettingsError(f"That is not a site name: {', '.join(bad)}. Nothing was changed.")
    if acknowledge:
        data["agent_ack"] = {"date": (today or date.today()).isoformat(), "v": ACK_VERSION}
    if explore_signed_in_ is not None:
        # Stored only when off: the default is the person's signed-in session (D2 amended).
        if explore_signed_in_:
            data.pop("explore_signed_in", None)
        else:
            data["explore_signed_in"] = False
    if never_explore_:
        held_never = data.get("never_explore") if isinstance(data.get("never_explore"), dict) else {}
        held_never = {str(k): str(v) for k, v in held_never.items() if reading_hosts.valid_site_key(str(k))}
        for key, on in never_explore_.items():
            if on:
                held_never.setdefault(str(key), (today or date.today()).isoformat())
            else:
                held_never.pop(str(key), None)
        if held_never:
            data["never_explore"] = dict(sorted(held_never.items()))
        else:
            data.pop("never_explore", None)
    if youtube_lists_ is not None:
        if not isinstance(youtube_lists_, dict) or any(str(k) not in YOUTUBE_LISTS for k in youtube_lists_):
            raise SettingsError("youtubeLists must be a map of watch_later or history to true or false. "
                                "Nothing was changed.")
        if any(youtube_lists_.values()) and not _ack_ok(data):
            raise SettingsError(
                "Read the sheet and tick I understand before turning this on. Nothing was changed.")
        held_lists = data.get("youtube_lists") if isinstance(data.get("youtube_lists"), dict) else {}
        held_lists = {k: str(v) for k, v in held_lists.items() if k in YOUTUBE_LISTS}
        held_off = data.get("youtube_lists_off") if isinstance(data.get("youtube_lists_off"), dict) else {}
        held_off = {k: str(v) for k, v in held_off.items() if k in YOUTUBE_LISTS}
        for key, on in youtube_lists_.items():
            if on:
                held_lists.setdefault(str(key), (today or date.today()).isoformat())
                held_off.pop(str(key), None)
            else:
                held_lists.pop(str(key), None)
                # Remembered (2026-10-26): lists are on by default, so an off must outlive every default.
                held_off.setdefault(str(key), (today or date.today()).isoformat())
        if held_off:
            data["youtube_lists_off"] = dict(sorted(held_off.items()))
        else:
            data.pop("youtube_lists_off", None)
        if held_lists:
            data["youtube_lists"] = dict(sorted(held_lists.items()))
        else:
            data.pop("youtube_lists", None)
    if saved_lists_ is not None:
        # G206: the same standing ask as a YouTube list, one per walled site's saved list.
        if not isinstance(saved_lists_, dict) or any(str(k) not in SAVED_LISTS for k in saved_lists_):
            raise SettingsError("savedLists must be a map of x, instagram or linkedin to true or false. "
                                "Nothing was changed.")
        if any(saved_lists_.values()) and not _ack_ok(data):
            raise SettingsError(
                "Read the sheet and tick I understand before turning this on. Nothing was changed.")
        held_saved = data.get("saved_lists") if isinstance(data.get("saved_lists"), dict) else {}
        held_saved = {k: str(v) for k, v in held_saved.items() if k in SAVED_LISTS}
        held_off = data.get("saved_lists_off") if isinstance(data.get("saved_lists_off"), dict) else {}
        held_off = {k: str(v) for k, v in held_off.items() if k in SAVED_LISTS}
        for key, on in saved_lists_.items():
            if on:
                held_saved.setdefault(str(key), (today or date.today()).isoformat())
                held_off.pop(str(key), None)
            else:
                held_saved.pop(str(key), None)
                # Remembered (2026-10-26): lists are on by default, so an off must outlive every default.
                held_off.setdefault(str(key), (today or date.today()).isoformat())
        if held_off:
            data["saved_lists_off"] = dict(sorted(held_off.items()))
        else:
            data.pop("saved_lists_off", None)
        if held_saved:
            data["saved_lists"] = dict(sorted(held_saved.items()))
        else:
            data.pop("saved_lists", None)
    if agent_enabled_ is not None:
        if agent_enabled_ and not _ack_ok(data):
            raise SettingsError(
                "Read the sheet and tick I understand before turning this on. Nothing was changed.")
        # Stored only when off: on is the default once the sheet is accepted (2026-10-22).
        if agent_enabled_:
            data.pop("agent", None)
        else:
            data["agent"] = False
    if sites:
        wants_on = [str(k) for k, v in sites.items() if v]
        if wants_on and not _ack_ok(data):
            raise SettingsError(
                "Read the sheet and tick I understand before turning this on. Nothing was changed.")
        held = data.get("agent_sites") if isinstance(data.get("agent_sites"), dict) else {}
        held = {str(k): str(v) for k, v in held.items() if reading_hosts.valid_site_key(str(k))}
        known = set(held) | {str(k) for k in (surfaced or ())}
        stranger = sorted(k for k in wants_on if k not in known)
        if stranger:
            raise SettingsError(
                f"Cicada hasn't needed your browser for {', '.join(stranger)}, so there is nothing to allow yet. "
                "Nothing was changed.")
        for key, on in sites.items():
            key = str(key)
            if on:
                held.setdefault(key, (today or date.today()).isoformat())
            else:
                held.pop(key, None)
        if held:
            data["agent_sites"] = dict(sorted(held.items()))
        else:
            data.pop("agent_sites", None)
    if data != original:
        # A no-op call writes nothing, so the sync component's mtime never
        # moves for a change that changed nothing.
        _save(data)
    return snapshot()


def _ack_ok(data: dict) -> bool:
    held = data.get("agent_ack")
    try:
        return isinstance(held, dict) and int(held.get("v")) >= ACK_VERSION
    except (TypeError, ValueError):
        return False


# --- the last read an agent recorded ----------------------------------------------
#
# A day and nothing else, in its own tiny file beside ``reading.json`` (so a
# recorded read never rewrites the person's switches, and never races a settings
# change). The Agents page shows it; it used to be re-derived by parsing two months
# of the telemetry ledger on every settings request, on the event loop.

LAST_READ_FILENAME = "reading-last.json"


def record_agent_read(day: date | None = None) -> None:
    """Note that an agent recorded a successful read today. Never raises: a note
    that cannot be written must not fail the read it describes."""
    target = cicada_home() / LAST_READ_FILENAME
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".reading-last-", suffix=".tmp", dir=str(target.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(json.dumps({"day": (day or date.today()).isoformat()}) + "\n")
            os.chmod(tmp, 0o600)
            os.replace(tmp, target)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except OSError:
        return


def last_agent_read() -> str | None:
    """The day (``YYYY-MM-DD``) of the last read an agent recorded, else None."""
    try:
        data = json.loads((cicada_home() / LAST_READ_FILENAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    day = str(data.get("day") or "")[:10] if isinstance(data, dict) else ""
    try:
        date.fromisoformat(day)
    except ValueError:
        return None
    return day
