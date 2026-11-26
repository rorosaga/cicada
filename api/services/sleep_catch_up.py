"""A scheduled run the Mac slept or was off through runs once, soon after it is back (owner, 2026-10-19).

The daily and interval schedules are APScheduler timers in the backend's own process. A timer that comes due while the
Mac is asleep fires late on wake, past its grace, and is dropped; one that comes due while the Mac is off is never seen
— the backend starts later and computes the *next* time. A laptop closed at night therefore never ran its scheduled
Sleep. This module is the catch-up: a probe every ``PROBE_MINUTES`` (registered beside the schedule's own job for
``daily`` and ``interval`` only; ``manual`` and ``after_import`` are unchanged) asks whether a due time went by with no
run since, and if so runs **once**, however many due times were missed — the latest one is the one named.

**Where "the last due time / the last run" is known from.** The due time is computed from the schedule (``daily``: the
latest HH:MM at or before now; ``interval``: the last anchor plus N hours). What happened since is the latest of:

* ``handled_at`` — stamped by every scheduled fire, on time or caught up, *before* it reads, including one that found
  a running cycle, a paused run or nothing readable. A fire that then fails (a plan engine with the person's
  "Scheduled runs may use my plan" switch off, ruling 4b) is therefore tried once per missed time and says so once —
  never again on every wake;
* ``last_run_at`` — stamped by ``sleep_cycle.run`` at the start of every run that reads (the person's or a schedule's);
* the newest run in ``sleep_runs`` (``runs.json``) and the newest real ``Sleep cycle`` commit — the record that predates
  this file, so an upgrade does not catch up a night that a run already covered;
* ``since`` — when this schedule (its mode and time) was first seen, so setting "daily at 03:00" at 14:00 never catches
  up the 03:00 that came before the schedule existed. On the first start after an upgrade it is the schedule file's own
  modification time (when the person last saved it).

The stamps live machine-local in ``$CICADA_HOME/sleep/<bank>/schedule.json`` (``sleep_local``: a 0700 folder of 0600
files, timestamps only, never in a bank or git). The schedule is a fact about this Mac's process — the bank's git
history cannot say that a scheduled fire found nothing to read, nor that a fire failed — and it survives a restart,
which in-memory scheduler state does not.

**The settle.** A missed time is first *noticed*, then run one probe later (``SETTLE``) if it is still missed — so the
catch-up never lands on login or the moment the lid opens. A gap between two probes longer than ``2 × PROBE_MINUTES``
means the Mac slept (or the process just started), and the settle starts again.

**Rails.** A catch-up is a scheduled run: ``user_triggered=False`` (ruling 4/4b — a plan only through the person's
switch, never flipped here); it reads everything waiting (ruling 16, ``_scheduled_drain``); it never stacks on a
running cycle (it looks again next probe); a paused run gets the engine-free upkeep only, exactly as the cron's
``_run_if_idle``; it resolves the bank active when it fires (``bank_registry.unpin``, G183(d)); and it *reads* only
when something readable waits (a parked conversation or index-only history is not readable). A missed time with
nothing readable runs the engine-free tail alone (G245, ``run(tail_only=True, engine_free=True)``): the polls, expiry
and the state refresh happen, no engine starts, no plan is spent and no run is recorded. The run's summary carries
``catch_up_for`` — the missed time — so Past nights can say "Missed 03:00 — caught up at 08:12".

**A run refused before it read is tried again the same night (2026-11-25).** "Runs once" is about *reading*: the stamps
above are written before the read so a run that fails after it started (a plan engine the person switched off, a
spend) is never repeated on every wake — that rule protects the person's plan and money and is unchanged. A run
that never read anything is another case: ``sleep_cycle.run`` refused it at the write window (a writer admitted before
it still held the bank for ``write_admission.WAIT_MAX_S``), nothing was spent, nothing recorded, and yet both stamps
said the night was taken — one slow write cost a whole night, silently. ``sleep_cycle.run`` now records that refusal
here (``note_refused``, for a scheduled run only: not a person's click, not a paused run's upkeep, not a Continue), and
the probe tries it again — through the very same gates as a catch-up (settle, never on a running cycle, never over a
pause, ``user_triggered=False``, ruling 4 untouched): at most ``MAX_TRIES`` attempts in all, the next one
``RETRY_AFTER`` after the last refusal (10 min, 30 min, then 90 min — a stuck writer is not hammered), and none after
``RETRY_WINDOW`` from the first, so it stays one night's run. A run that opens the window clears the record, which is
also what ends the retries on success (``clear_refused``); a pause, or nothing readable, clears it too. While a record
stands the status carries it as a calm ``notice`` — never as the run's ``error`` (``refusal``: a one-line text, the full
``detail``, when the next try is) — including when every try was refused.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from loguru import logger

from api.services import sleep_local

FILE = "schedule.json"
JOB_ID = "sleep_catch_up"
PROBE_MINUTES = 5
#: A missed time noticed on one probe runs on the next one (five minutes on, a minute's slack for timer jitter).
SETTLE = timedelta(minutes=PROBE_MINUTES - 1)
#: How late the schedule's own timer may still fire as "on time" (a Mac that wakes at 03:00:40); later is ours.
ON_TIME_GRACE_S = 60

#: A scheduled run refused at the write window before it read anything (see the module docstring).
REFUSED = "window_refused"
#: Total attempts for one scheduled time: the run itself plus the retries. The wait for a writer is already bounded by
#: ``write_admission.WAIT_MAX_S`` per attempt, so four attempts cost at most four minutes of waiting in a night.
MAX_TRIES = 4
#: The pause after the Nth refusal before the next attempt (N = 1, 2, 3): growing, so a stuck writer is not hammered.
RETRY_AFTER = (timedelta(minutes=10), timedelta(minutes=30), timedelta(minutes=90))
#: A refusal is only retried this long after the first one: the night's run, never the next day's.
RETRY_WINDOW = timedelta(hours=6)

# In-memory, per bank: the last probe's wall time (a long gap = the Mac slept) and the missed time noticed, with when.
_last_probe: dict[str, datetime] = {}
_noticed: dict[str, tuple[datetime, datetime]] = {}


def _now() -> datetime:
    return datetime.now().astimezone()


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _parse(raw) -> datetime | None:
    if not raw or not isinstance(raw, str):
        return None
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return dt.astimezone() if dt.tzinfo is None else dt   # a naive stamp is local (one machine)


def fingerprint(cfg) -> str | None:
    """The schedule's identity: a changed mode, time or interval is a new schedule with its own ``since``."""
    mode = getattr(cfg, "mode", None)
    if mode == "daily":
        return f"daily@{int(cfg.hour):02d}:{int(cfg.minute):02d}"
    if mode == "interval":
        return f"interval@{int(cfg.interval_hours)}h"
    return None


def _path(memory_path, *, create: bool = False) -> Path:
    return sleep_local.bank_dir(Path(memory_path), create=create) / FILE


def load(memory_path) -> dict:
    data = sleep_local.read_json(_path(memory_path))
    return data if isinstance(data, dict) else {}


def _save(memory_path, data: dict) -> None:
    sleep_local.write_json(_path(memory_path, create=True), data)


def _update(memory_path, **fields) -> None:
    """Never raises: a stamp that cannot be written costs at most one extra catch-up, never a run."""
    try:
        data = load(memory_path)
        data.update(fields)
        _save(memory_path, data)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"catch-up stamp not written: {type(e).__name__}")


def note_schedule(memory_path, cfg, *, now: datetime | None = None) -> None:
    """Record when this schedule began, once per schedule. A bank with no stamp yet (the first start after an upgrade)
    takes the schedule file's own modification time — when the person last saved it — so last night still counts; a
    changed schedule starts from now. Never raises."""
    fp = fingerprint(cfg)
    if fp is None:
        return
    try:
        data = load(memory_path)
        if data.get("fingerprint") == fp and _parse(data.get("since")) is not None:
            return
        now = now or _now()
        since = now
        if not data.get("fingerprint"):
            from api.services import sleep_scheduler

            try:
                mtime = (Path(memory_path) / sleep_scheduler.SCHEDULE_FILE).stat().st_mtime
                since = min(now, datetime.fromtimestamp(mtime).astimezone())
            except OSError:
                pass
        data.update({"fingerprint": fp, "since": _iso(since)})
        _save(memory_path, data)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"catch-up schedule not noted: {type(e).__name__}")


def note_handled(memory_path, *, now: datetime | None = None) -> None:
    """A scheduled fire (on time or caught up) took its turn — stamped before it reads, so a fire that then fails is
    not tried again on the next wake."""
    _update(memory_path, handled_at=_iso(now or _now()))


def note_run_started(memory_path, *, now: datetime | None = None) -> None:
    """``sleep_cycle.run`` began a run that reads — anyone's. Any run after a due time covers it."""
    _update(memory_path, last_run_at=_iso(now or _now()))


def _refusal(memory_path) -> dict | None:
    rec = load(memory_path).get(REFUSED)
    if not isinstance(rec, dict) or _parse(rec.get("for")) is None or _parse(rec.get("last_at")) is None:
        return None
    try:
        rec["tries"] = max(1, int(rec.get("tries") or 1))
    except (TypeError, ValueError):
        rec["tries"] = 1
    return rec


def note_refused(memory_path, due_iso: str, *, now: datetime | None = None) -> None:
    """A scheduled run for ``due_iso`` was refused at the write window before it read: count the attempt. The same
    scheduled time keeps its first refusal and its count; another time starts afresh. Never raises."""
    try:
        now = now or _now()
        rec = _refusal(memory_path)
        if rec is not None and rec.get("for") == due_iso:
            tries, first = rec["tries"] + 1, rec.get("first_at") or _iso(now)
        else:
            tries, first = 1, _iso(now)
        _update(memory_path, **{REFUSED: {"for": due_iso, "first_at": first, "last_at": _iso(now), "tries": tries}})
    except Exception as e:  # noqa: BLE001
        logger.debug(f"refused-run stamp not written: {type(e).__name__}")


def clear_refused(memory_path) -> None:
    """The run was covered (the window opened, so it reads), or the retry no longer applies. Writes only when a record
    is there, so a normal run costs one small read."""
    try:
        if REFUSED in load(memory_path):
            data = load(memory_path)
            data.pop(REFUSED, None)
            _save(memory_path, data)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"refused-run stamp not cleared: {type(e).__name__}")


def _touch_refused(memory_path, now: datetime) -> None:
    """A retry is starting: space the next one from now, whatever this one turns out to be."""
    rec = _refusal(memory_path)
    if rec is not None:
        _update(memory_path, **{REFUSED: {**rec, "last_at": _iso(now)}})


def _may_retry(rec: dict, now: datetime) -> bool:
    first = _parse(rec.get("first_at")) or _parse(rec.get("last_at"))
    return rec["tries"] < MAX_TRIES and now - first <= RETRY_WINDOW


def retry_due(memory_path, now: datetime) -> datetime | None:
    """The scheduled time whose run was refused before it read and is due another try — or ``None``. Pure reads: the
    record says how often it was refused and when; nothing here decides whether a run may start (``probe`` does)."""
    rec = _refusal(memory_path)
    if rec is None or not _may_retry(rec, now):
        return None
    last = _parse(rec["last_at"])
    ran = _parse(load(memory_path).get("last_run_at"))
    if ran is not None and ran > last:
        return None                      # a run read since: it covered the night (the window opening clears it too)
    if now < last + RETRY_AFTER[min(rec["tries"], len(RETRY_AFTER)) - 1]:
        return None
    return _parse(rec["for"])


#: The ``kind`` of the one notice the status carries today; a client that does not know a kind shows its ``text`` as is.
NOTICE_KIND = "scheduled_run_refused"


def _run_label(due: datetime, now: datetime) -> str:
    """Which run it was, in the words a person uses, and only when that is true: a run from the small hours or the
    evening within the last day is "last night's"; otherwise today's, yesterday's, or the day by name."""
    due, now = due.astimezone(), now.astimezone()
    hhmm = due.strftime("%H:%M")
    if now - due < timedelta(hours=18) and (due.hour < 6 or due.hour >= 20):
        return f"Last night's {hhmm} run"
    days = (now.date() - due.date()).days
    if days == 0:
        return f"Today's {hhmm} run"
    if days == 1:
        return f"Yesterday's {hhmm} run"
    return f"The {due.strftime('%b')} {due.day} {hhmm} run"


def _next_scheduled_words(memory_path, now: datetime) -> str:
    """When the schedule runs next, in words: its time when that is within a day, else only that it will."""
    try:
        from api.services import sleep_scheduler

        raw = sleep_scheduler.next_run_at(Path(memory_path), now.astimezone().replace(tzinfo=None))
        nxt = datetime.fromisoformat(raw) if raw else None
        if nxt is not None:
            local = nxt if nxt.tzinfo else nxt.astimezone()
            if timedelta(0) < local - now <= timedelta(hours=24):
                return f"at {_local_hhmm(local)}"
    except Exception as e:  # noqa: BLE001
        logger.debug(f"next scheduled time not read: {type(e).__name__}")
    return "at its next scheduled time"


def refusal(memory_path, *, now: datetime | None = None) -> dict | None:
    """What the Sleep page says while a scheduled run stands refused, as data: ``kind``, a one-line ``text`` for the
    page, the full ``detail`` (what happened, that nothing was read or used), when the next try is (``retry_at``, local
    ISO, ``None`` once it gave up), how many tries it had (``tries`` of ``max_tries``) and ``gave_up``. ``None`` when
    nothing stands refused (or the bank no longer has a scheduled run to retry). A refusal read nothing and spent
    nothing: it is a notice, never an error, and it is never stored as a sentence, only derived from the record."""
    try:
        from api.services import sleep_scheduler

        rec = _refusal(memory_path)
        if rec is None or fingerprint(sleep_scheduler.load_schedule(Path(memory_path))) is None:
            return None
        now = (now or _now()).astimezone()
        due = _parse(rec["for"]).astimezone()
        when = f"{due.strftime('%b')} {due.day} at {_local_hhmm(due)}"
        tries = rec["tries"]
        base = (f"The scheduled run for {when} did not start: something was still writing to your memory, so Sleep "
                "read nothing and used nothing.")
        label = _run_label(due, now)
        if _may_retry(rec, now):
            nxt = max(_parse(rec["last_at"]) + RETRY_AFTER[min(tries, len(RETRY_AFTER)) - 1], now)
            return {
                "kind": NOTICE_KIND,
                "text": f"{label} hasn't started yet. Next try after {_local_hhmm(nxt)}.",
                "detail": f"{base} It will try again after {_local_hhmm(nxt)} (try {tries + 1} of {MAX_TRIES}).",
                "retry_at": nxt.astimezone().isoformat(timespec="seconds"),
                "tries": tries, "max_tries": MAX_TRIES, "gave_up": False,
            }
        return {
            "kind": NOTICE_KIND,
            "text": f"{label} didn't start. It runs again {_next_scheduled_words(memory_path, now)}.",
            "detail": (f"{base} It tried {tries} time{'s' if tries != 1 else ''} and stopped; it will run at its next "
                       "scheduled time, or you can start it yourself."),
            "retry_at": None,
            "tries": tries, "max_tries": MAX_TRIES, "gave_up": True,
        }
    except Exception as e:  # noqa: BLE001 - a status read never fails on this
        logger.debug(f"refusal notice not built: {type(e).__name__}")
        return None


def refusal_notice(memory_path, *, now: datetime | None = None) -> str | None:
    """The full sentence of ``refusal`` (its ``detail``): the notice's ``.help`` and VoiceOver hint, never its line."""
    notice = refusal(memory_path, now=now)
    return notice["detail"] if notice else None


async def _latest_run(memory_path) -> datetime | None:
    """The record that predates this file: the newest run summary and the newest real Sleep cycle commit."""
    best: datetime | None = None
    try:
        from api.services import sleep_runs

        for run in sleep_runs.all_runs(Path(memory_path)).values():
            ts = _parse((run or {}).get("started_at"))
            if ts is not None and (best is None or ts > best):
                best = ts
    except Exception:  # noqa: BLE001
        pass
    try:
        from api.services import sleep_debt

        last = await sleep_debt._last_cycle_at(Path(memory_path))
        if last is not None:
            last = last.astimezone()
            if best is None or last > best:
                best = last
    except Exception:  # noqa: BLE001
        pass
    return best


def due_before(cfg, now: datetime, anchor: datetime) -> datetime | None:
    """The latest due time at or before ``now`` that nothing has covered (``anchor``: the latest run, fire or the
    schedule's own start), or ``None``. Pure. However many were missed, one time comes back — the latest."""
    if cfg.mode == "daily":
        local = now.astimezone().replace(tzinfo=None)
        due_naive = local.replace(hour=int(cfg.hour), minute=int(cfg.minute), second=0, microsecond=0)
        if due_naive > local:
            due_naive -= timedelta(days=1)
        due = due_naive.astimezone()   # through the local zone, so a DST day keeps its wall-clock time
        return due if due > anchor else None
    if cfg.mode == "interval":
        step = timedelta(hours=int(cfg.interval_hours))
        due = anchor + step
        if due > now:
            return None
        # The latest of the missed steps, never a backlog of them.
        return anchor + step * int((now - anchor) / step)
    return None


async def missed_due(memory_path, cfg, *, now: datetime | None = None) -> datetime | None:
    """The scheduled time that went by with no run since, or ``None``. A bank that has not seen this schedule yet
    notes it here and owes nothing."""
    if fingerprint(cfg) is None:
        return None
    now = now or _now()
    data = load(memory_path)
    since = _parse(data.get("since")) if data.get("fingerprint") == fingerprint(cfg) else None
    if since is None:
        note_schedule(memory_path, cfg, now=now)
        data = load(memory_path)
        since = _parse(data.get("since")) if data.get("fingerprint") == fingerprint(cfg) else None
        if since is None:
            return None
    marks = [since, _parse(data.get("handled_at")), _parse(data.get("last_run_at")), await _latest_run(memory_path)]
    anchor = max(m for m in marks if m is not None)
    return due_before(cfg, now, anchor)


def _local_hhmm(dt: datetime) -> str:
    return dt.astimezone().strftime("%H:%M")


async def probe(settings) -> None:
    """The catch-up job (see the module docstring). Never stacks, never reads over a pause, never flips ruling 4.

    The schedule is the ACTIVE bank's own (`load_schedule`), read at every probe — never the one the job was
    registered with: a bank switch re-registers the jobs from the new bank's schedule
    (``sleep_scheduler.follow_active_bank``), but a probe still in flight, or a switch that came by another path, must
    never catch a bank set to ``manual`` (or ``after_import``, which has no due times) up on another bank's 03:00. A demo bank is never read on a schedule
    (`demo_guard`)."""
    from api.services import bank_registry, demo_guard, sleep_cycle, sleep_debt, sleep_scheduler

    bank_registry.unpin()   # G183(d): the bank active now, whatever context registered this job
    memory_path = settings.memory_path
    key = str(memory_path)
    cfg = sleep_scheduler.load_schedule(Path(memory_path))
    if fingerprint(cfg) is None or demo_guard.is_demo(Path(memory_path)):
        _noticed.pop(key, None)
        return
    now = _now()
    last = _last_probe.get(key)
    _last_probe[key] = now
    woke = last is None or now - last > timedelta(minutes=2 * PROBE_MINUTES)

    due = await missed_due(memory_path, cfg, now=now)
    retry = False
    if due is None:
        # A scheduled run that was refused before it read (a writer still held the bank) is owed another try.
        due = retry_due(memory_path, now)
        retry = due is not None
    if due is None:
        _noticed.pop(key, None)
        return
    seen = _noticed.get(key)
    if woke or seen is None or seen[0] != due:
        _noticed[key] = (due, now)       # the settle starts: run on a later probe if still missed
        what = "was refused by a write still in progress — trying again" if retry else "was missed — catching up"
        logger.info(f"Scheduled sleep: the {_local_hhmm(due)} run {what} after a short settle")
        return
    if now - seen[1] < SETTLE:
        return
    if sleep_cycle.get_sleep_state().status == "running":
        return                           # never stack; whatever is reading may cover it, else the next probe
    _noticed.pop(key, None)
    cycle_id = f"sleep_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}"
    if retry:
        _touch_refused(memory_path, now)  # the next try is spaced from this one, whatever this one turns out to be
    if sleep_scheduler._paused_for_the_person(memory_path):
        if retry:
            clear_refused(memory_path)    # a pause is the person's: nothing is read over it, and nothing stays owed
        note_handled(memory_path, now=now)
        logger.info("Scheduled sleep catch-up: a paused run waits for the person — upkeep only")
        await sleep_cycle.run(settings, cycle_id, user_triggered=False, tail_only=True)
        return
    debt = await sleep_debt.compute(memory_path, settings)
    readable = getattr(debt, "readable_count", None)
    if readable is None:
        readable = getattr(debt, "unprocessed_count", 0)
    note_handled(memory_path, now=now)   # before reading: a run that fails is tried once, not on every wake
    if not readable and not history_index_turns_due(memory_path):
        if retry:
            clear_refused(memory_path)    # nothing waits to be read: the refused run owes nothing
        # G245 (track C1): nothing to read is no reason to skip the upkeep — the polls, expiry and the state refresh
        # run, with no engine and no run recorded, so a quiet night never leaves a source stale.
        logger.info(f"Scheduled sleep catch-up: nothing to read for the missed {_local_hhmm(due)} run — upkeep only")
        await sleep_cycle.run(settings, cycle_id, user_triggered=False, tail_only=True, engine_free=True)
        return
    if sleep_cycle.get_sleep_state().status == "running":
        return                           # a run began while the queue was counted: it reads what waits
    logger.info(f"Scheduled sleep: {'trying again' if retry else 'catching up on'} the "
                f"{'refused' if retry else 'missed'} {_local_hhmm(due)} run")
    await sleep_cycle.run(settings, cycle_id, user_triggered=False,
                          drain=sleep_scheduler._scheduled_drain(settings), catch_up_for=_iso(due))


def history_index_turns_due(memory_path: Path) -> bool:
    """Ruling 80: a missed night with nothing waiting still reads its share of the pile (`history_index.turns_due`)."""
    from api.services import history_index

    try:
        return history_index.turns_due(memory_path)
    except Exception:  # noqa: BLE001 - the pile waits one more night
        return False


def reset_for_tests() -> None:
    _last_probe.clear()
    _noticed.clear()
