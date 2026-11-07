"""Export requests the person said yes to, for their own agent to carry out (ROR-126).

Once an agent with a browser is connected, Cicada offers to have it request the chat export from a provider, in the
person's own signed-in browser. The person says yes **one provider at a time**; each yes lands here, and the agent picks
it up through ``cicada_export_requests`` when the person next talks to it — Cicada never opens a browser, never signs in
and never schedules an agent (G166), exactly like the explore queue it is modelled on.

``$CICADA_HOME/export_requests/<bank slug>.json`` — outside every bank, ids and enums only (a vendor, a state, a
date and the harness's name): no text from anyone's account ever reaches it. States:

* ``asked`` — the person said yes; the agent has not reported back.
* ``requested`` — the agent asked the provider; the export is on its way (the app starts the wait, ruling 58's one-off).
* ``manual`` — the provider's page could not be driven reliably (a sign-in, a captcha, a changed page); the person
  does this one by hand with the walkthrough, and the row says why in one short line.

A row is removed when its export is imported, when the person stops waiting, and after 14 days (the wait's own limit).
Nothing here watches email or looks in Downloads (ruling 58).
"""
from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from api.services import video_queue
from api.services.auth import cicada_home

SCHEMA_V = 1
MAX_AGE = timedelta(days=14)
MAX_REASON = 200

#: The only providers whose chats the importer reads, with the page that holds the export button. The one table the
#: agent's reply is built from; the app has its own copy in ``WalkthroughVendor`` (kept equal by a test).
VENDORS: dict[str, dict[str, str]] = {
    "claude": {"title": "Claude", "url": "https://claude.ai/settings/data-privacy-controls"},
    "chatgpt": {"title": "ChatGPT", "url": "https://chatgpt.com/#settings/DataControls"},
    "gemini": {"title": "Gemini", "url": "https://takeout.google.com/"},
}
STATES = ("asked", "requested", "manual")
OUTCOMES = ("requested", "manual")


class RequestError(ValueError):
    pass


def path_for(memory_path: Path) -> Path:
    try:
        slug = video_queue.bank_slug(memory_path)
    except video_queue.QueueError as exc:
        raise RequestError("this memory bank cannot have export requests") from exc
    return cicada_home() / "export_requests" / f"{slug}.json"


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(value) -> datetime | None:
    try:
        return datetime.strptime(str(value), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _clean_row(raw) -> dict | None:
    if not isinstance(raw, dict) or raw.get("vendor") not in VENDORS or raw.get("state") not in STATES:
        return None
    asked = _parse(raw.get("asked_at"))
    if asked is None:
        return None
    row = {"vendor": raw["vendor"], "state": raw["state"], "asked_at": _iso(asked)}
    for name in ("requested_at",):
        moment = _parse(raw.get(name))
        if moment:
            row[name] = _iso(moment)
    for name, limit in (("harness", 64), ("reason", MAX_REASON)):
        text = " ".join(str(raw.get(name) or "").split())[:limit]
        if text:
            row[name] = text
    return row


def _read(target: Path, now: datetime) -> dict[str, dict]:
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    rows = data.get("rows") if isinstance(data, dict) else None
    out: dict[str, dict] = {}
    for raw in rows if isinstance(rows, list) else []:
        row = _clean_row(raw)
        if row and now - _parse(row["asked_at"]) < MAX_AGE:
            out[row["vendor"]] = row
    return out


@contextmanager
def _locked(memory_path: Path):
    target = path_for(memory_path)
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with open(target.with_name(target.name + ".lock"), "a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield target
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _write(target: Path, rows: dict[str, dict]) -> None:
    fd, tmp = tempfile.mkstemp(prefix=".export-requests-", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"v": SCHEMA_V, "rows": sorted(rows.values(), key=lambda r: r["vendor"])},
                                    indent=1) + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def rows(memory_path: Path, now: datetime | None = None) -> list[dict]:
    """Every live request for the bank, oldest first. Never creates anything."""
    return sorted(_read(path_for(memory_path), _now(now)).values(), key=lambda r: r["asked_at"])


def grant(memory_path: Path, vendor: str, now: datetime | None = None) -> dict:
    """The person's yes for one provider. Asking again restarts the request."""
    if vendor not in VENDORS:
        raise RequestError("unknown provider")
    moment = _now(now)
    with _locked(memory_path) as target:
        current = _read(target, moment)
        current[vendor] = {"vendor": vendor, "state": "asked", "asked_at": _iso(moment)}
        _write(target, current)
        return current[vendor]


def report(memory_path: Path, vendor: str, outcome: str, *, harness: str | None = None, reason: str | None = None,
           now: datetime | None = None) -> dict:
    """What the person's agent found. Only a request the person granted can be reported on."""
    if outcome not in OUTCOMES:
        raise RequestError("outcome must be requested or manual")
    moment = _now(now)
    with _locked(memory_path) as target:
        current = _read(target, moment)
        row = current.get(vendor)
        if row is None:
            raise RequestError("the person has not asked for that provider's export")
        row = {**row, "state": outcome}
        if outcome == "requested":
            row["requested_at"] = _iso(moment)
        if harness:
            row["harness"] = harness
        if reason:
            row["reason"] = reason
        row = _clean_row(row) or row
        current[vendor] = row
        _write(target, current)
        return row


def clear(memory_path: Path, vendor: str, now: datetime | None = None) -> bool:
    """The export arrived (or the person stopped waiting). A no-op writes nothing."""
    with _locked(memory_path) as target:
        current = _read(target, _now(now))
        if vendor not in current:
            return False
        del current[vendor]
        _write(target, current)
        return True


# --- what the agent is told --------------------------------------------------------------------------------------

def agent_brief(row: dict) -> str:
    spec = VENDORS[row["vendor"]]
    return (f"{spec['title']}: open {spec['url']} in the person's own signed-in browser, find the data export "
            f"option, request it and confirm. The provider emails the link later; stop there.")


RULES = ("Use the person's own browser session; never sign in for them, never ask for a password, and never open "
         "their email. If a sign-in, captcha or changed page stops you, report `manual` with one short reason. "
         "Report each provider with `done` once you have asked, or could not.")
