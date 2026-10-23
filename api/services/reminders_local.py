"""Apple Reminders through EventKit — the backend half (G219, the G142 path).

The memory is meant to replace the lists a person kept elsewhere, so what already sits in Reminders comes in, one way:
the APP reads EventKit after the one Reminders prompt and posts the reminders of the lists the person ticked; the
backend never opens ``~/Library`` (the Awake rail) and never writes back (ruling 38). Each reminder becomes one episode
through the G20 stager keyed ``reminders-local:<id>`` (``id`` = ``calendarItemExternalIdentifier``): an edit rewrites
it in place and re-queues it, a reminder gone from a ticked list is tombstoned and kept, and every body is scrubbed
before it is hashed. No model runs here — turning a completed reminder into progress, or a dated one into a planned
milestone, is Sleep's reading of the episode, not capture's.

What one request carries: open reminders plus those completed since ``completed_since`` (the app sends 90 days), for
the lists it names. A reminder is tombstoned only when its list is named, it was not posted, and it could have been —
open when last seen, or completed on or after ``completed_since``. One completed before that has aged out of the
window, not out of Reminders, and is kept as it was. A list the request does not name says nothing about its
reminders: unticking a list stops reading it and deletes nothing.

Dated when it happened (ruling 37B's spirit, read on time): a completed reminder at its completion, an open one at its
creation; neither known, the day Cicada learned of it. The due date is a fact in the body and in ``reminder_due``,
never the episode's date — a reminder due next month was not said next month. A reminder completed after it was first
read moves to its completion in place (``EpisodeDraft.redate``; the id keeps its first day, ruling 34).

Whose words: a reminder is the person's own (``evidence_kind: user``), except in a list the person marked as one
others add to, where any item may be someone else's (``assistant``: never the person's own words, the folder rule).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from api.services import episode_ids, episode_scrub, episode_staging
from api.services.calendar_local import PayloadError, _clip, _link, _notes, instant

CHANNEL_ID = "reminders-local"
LABEL = "Apple Reminders"
ORIGIN = CHANNEL_ID
#: The scrub ledger's writer word (`episode_scrub.WRITERS`).
SCRUB_WRITER = "reminders"
SOURCE_PREFIX = f"{CHANNEL_ID}:"
MAX_REMINDERS = 5000
MAX_LISTS = 200

__all__ = ["CHANNEL_ID", "LABEL", "MAX_LISTS", "MAX_REMINDERS", "ORIGIN", "PayloadError", "SCRUB_WRITER",
           "SOURCE_PREFIX", "body_for", "sync"]


def _priority(value) -> str | None:
    """EventKit's 0–9: 0 none, 1–4 high, 5 medium, 6–9 low (`EKReminderPriority`)."""
    try:
        n = int(value or 0)
    except (TypeError, ValueError):
        return None
    if 1 <= n <= 4:
        return "High"
    if n == 5:
        return "Medium"
    if 6 <= n <= 9:
        return "Low"
    return None


def _completed_at(reminder: dict) -> datetime | None:
    return instant(reminder.get("completed_at")) if reminder.get("completed") else None


def body_for(reminder: dict, lst: dict | None) -> tuple[str, int]:
    """The episode body: what the reminder says, its list, its status and its dates as facts. Returns the body and how
    many notes replacements the scrub made (for the ledger). Nothing here changes from one read to the next unless the
    reminder did, so a re-read is a skip."""
    lines = [f"# {_clip(reminder.get('title')) or 'Untitled reminder'}", ""]
    if lst and (name := _clip(lst.get("title"))):
        account = _clip(lst.get("account"))
        lines.append(f"**List:** {name}" + (f" ({account})" if account else "")
                     + (" · others add to this list" if lst.get("shared") else ""))
    done = _completed_at(reminder)
    if reminder.get("completed"):
        lines.append("**Status:** Completed" + (f" {reminder.get('completed_at')}" if done else ""))
    else:
        lines.append("**Status:** Open")
    if reminder.get("created"):
        lines.append(f"**Created:** {reminder['created']}")
    if reminder.get("due"):
        lines.append(f"**Due:** {reminder['due']}" + (" (all-day)" if reminder.get("due_all_day") else ""))
    if priority := _priority(reminder.get("priority")):
        lines.append(f"**Priority:** {priority}")
    if link := _link(reminder.get("url")):
        lines.append(f"**Link:** {link}")
    notes, scrubbed = _notes(reminder.get("notes"))
    if notes:
        lines += ["", "## Notes", notes]
    return "\n".join(lines), scrubbed


def _happened(reminder: dict, now: datetime) -> datetime | None:
    """When the episode is dated: its completion once completed, else its creation — never a moment still ahead (a
    clock skew between this Mac and the account), never the due date."""
    for at in (_completed_at(reminder), instant(reminder.get("created"))):
        if at is not None and at <= now:
            return at.astimezone(timezone.utc)
    return None


def _vanished(sid: str, fm: dict, posted: dict, lists: dict, since: datetime) -> bool:
    if not sid.startswith(SOURCE_PREFIX) or sid in posted or fm.get("source_deleted_at"):
        return False
    if str(fm.get("reminder_list_id") or "") not in lists:
        return False      # a list this request does not name says nothing about its reminders
    done = fm.get("reminder_completed_at")
    if not done:
        return True       # open when last read and no longer in its list: deleted, moved away or completed long ago
    at = instant(done)
    return at is not None and at >= since


def sync(memory_path: Path, payload: dict, *, bank: str | None = None) -> dict:
    """Stage one read of the ticked lists. ``payload`` is the request with snake_case keys. Returns the four counts,
    the live reminder count for the channel row, and the bank-relative paths to commit."""
    since = instant(payload.get("completed_since"))
    if since is None:
        raise PayloadError("completedSince must be a time with a UTC offset")
    lists = {str(item.get("id")): item for item in (payload.get("lists") or []) if item.get("id")}
    if len(lists) > MAX_LISTS:
        raise PayloadError(f"at most {MAX_LISTS} lists per sync")
    reminders: dict[str, dict] = {}
    for item in payload.get("reminders") or []:
        if item.get("id") and str(item.get("list_id") or "") in lists:
            reminders[SOURCE_PREFIX + str(item["id"])] = item      # a repeated id: the last one wins
    if len(reminders) > MAX_REMINDERS:
        raise PayloadError(f"at most {MAX_REMINDERS} reminders per sync")
    drafts: list[episode_staging.EpisodeDraft] = []
    scrubbed = 0
    now = datetime.now(timezone.utc)
    for sid, item in reminders.items():
        lst = lists.get(str(item.get("list_id") or ""))
        body, n = body_for(item, lst)
        title, m = episode_scrub.scrub(_clip(item.get("title")) or "Untitled reminder")
        scrubbed += n + m
        shared = bool(lst and lst.get("shared"))
        done = _completed_at(item)
        # Every key every time: the stager merges extras into the frontmatter, so a reopened reminder must write its
        # completion back to null or the stale one would keep it out of the tombstone rule.
        extra: dict = {"reminder_list_id": str(item.get("list_id") or ""),
                       "reminder_list_shared": shared,
                       "reminder_completed_at": done.astimezone(timezone.utc).isoformat() if done else None,
                       "reminder_due": str(item["due"]) if item.get("due") else None,
                       "evidence_kind": "assistant" if shared else "user"}
        when = _happened(item, now)
        drafts.append(episode_staging.EpisodeDraft(
            title=title, source_id=sid, source_updated_at=str(item.get("last_modified") or "") or None,
            timestamp=when.isoformat() if when else None, original_date=episode_ids.id_day(when) if when else None,
            source=ORIGIN, origin=ORIGIN, body=body, extra=extra, writer=SCRUB_WRITER, redate=True))
    episodes_dir = Path(memory_path) / "episodes"
    episodes_dir.mkdir(parents=True, exist_ok=True)
    with episode_staging.STAGE_LOCK:
        index, _ = episode_staging.scan(episodes_dir)
        gone = sorted(sid for sid, entry in index.items() if _vanished(sid, entry.fm, reminders, lists, since))
        result = episode_staging.stage(drafts, episodes_dir, deleted_source_ids=gone, bank=bank)
    # The notes and the frontmatter title were scrubbed here, before the stager saw them; the stager records its own
    # body pass under the same writer.
    episode_scrub.record(SCRUB_WRITER, scrubbed, bank=bank)
    return {"created": result.created, "updated": result.updated, "unchanged": result.skipped,
            "tombstoned": result.tombstoned, "live": len(reminders), "paths": list(result.paths)}
