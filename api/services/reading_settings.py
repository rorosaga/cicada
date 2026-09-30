"""The person's reading settings (G166, spec §7.2): a machine-wide file, never in a bank.

``$CICADA_HOME/reading.json`` (0600, atomic write) — the same home as
``owner.json`` and ``connections.json`` — holds:

* ``agent`` — the master switch, "Let an agent read pages for you". Off by
  default; while it is off ``cicada_reading_queue`` returns nothing, the tools
  refuse, and contract item 9 is not in the primer.
* ``agent_sites`` — ``{site: day}``: the sites the person let an agent read with
  their own browser (owner, 2026-09-30: there is no pre-picked list; a site is
  surfaced on Settings, Reading the web, when Cicada's own reader could not
  read a page of it, and the person turns each on). A standing permission,
  granted per site (``reading_hosts.site_of``); it only counts while the master
  switch is on. Empty by default. The earlier ``agent_hosts`` key is ignored by
  every reader and dropped on the next write: no carry-over, the branch had not
  shipped.
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
#: picker and gained the credentials line.)
ACK_VERSION = 2


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
    return _load().get("agent") is True and ack_current()


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


def snapshot() -> dict:
    held = ack()
    return {
        "agentEnabled": agent_enabled(),
        "allowedSites": allowed_sites(),
        "ackedAt": held["date"] if held else None,
        "ackCurrent": ack_current(),
    }


class SettingsError(ValueError):
    """A change the person's settings refuse, with a sentence they can read."""


def update(*, agent_enabled_: bool | None = None, acknowledge: bool = False, sites=None,
           surfaced=None, today: date | None = None) -> dict:
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
    if acknowledge:
        data["agent_ack"] = {"date": (today or date.today()).isoformat(), "v": ACK_VERSION}
    if agent_enabled_ is not None:
        if agent_enabled_ and not _ack_ok(data):
            raise SettingsError(
                "Read the sheet and tick I understand before turning this on. Nothing was changed.")
        data["agent"] = bool(agent_enabled_)
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
