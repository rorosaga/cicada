"""The backend sends the sessions its own hooks kept for it (B3, 2026-11-25).

When the Stop hook posts a session to this computer's own backend and gets no answer (the backend was restarting, as a
dev auto-update does every few commits) or a 5xx, it keeps the request in ``$CICADA_HOME/spool/capture`` — the route
``/capture/transcript``, the transcript's PATH and a few fields, never its words — and a *later firing of the hook*
sends it (``capture._flush_local``). A computer where no session ends afterwards has no later firing: the entry waited
for weeks, and on a copy the device's ``unsent`` count kept the machine's light on attention for as long. The follower
sends ``/capture/session`` and ``/capture/turn`` entries, never this one (it names a file the home cannot read).

**The backend finishes them itself, once it is up** — a daemon thread started with the backend in both modes
(:func:`start`): a first pass a few seconds after the start, then every :data:`INTERVAL_S` while anything waits, at most
:data:`PER_PASS` entries a pass, off the event loop. It takes an entry only when

* its route is the local one and its target names *this* backend's own address (``runtime_layout.local_backend_url``):
  one kept for another address or port waits for its own server ("what waits goes only where it was meant");
* it is due (``hook_spool.due``: an entry the backend only accepted waits :data:`hook_spool.ACCEPT_CONFIRM_S` for the
  write to finish, a held one its retry time).

**One path for both modes, two ends.** Whatever the mode, the entry is a ``/capture/transcript`` request and it goes
through the same two functions a live request does, never a second way to open a transcript (only a path that resolves
under the harness root as ``<session_id>.jsonl`` is read, ``validate_transcript_path``):

* a computer that keeps a copy: ``replica_gateway.keep_session`` — the very function its route answers a live request
  with — reads the one transcript and keeps the session for the home as a ``/capture/session`` entry, which the follower
  sends on its next pass (it is woken here);
* the home or a single computer: ``routers.capture.transcript_job`` — the very writer the route runs — writes the
  session into its own bank (the demo is never one: nothing is written and the entry waits), in one episode per session
  (G104), and queues the awake read as the route does.

They differ only in where the session lands, and that is decided by the mode the backend started in, which is what
decides where a live request goes too. **The write window:** awake capture never takes admission
(``write_admission``), the route takes none, and neither does this.

Marking follows ``hook_spool``'s rules: the entry that was sent is removed under the short spool lock only while it is
still that file (``signature``), so a newer snapshot a hook kept meanwhile survives and the hook and this thread may try
the same entry at once (the write is idempotent: one episode per session, by content hash). An entry whose transcript is
gone, refused (not the harness's file for that session) or empty finishes: removed and counted in the ``rejected``
number the machine reports, never waiting forever. A failure is logged by class and tried again on a later pass; it
never fails a capture or the follower. Counts only leave this machine, never a path or a word."""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

#: The first pass runs this long after the backend started (never contending with its start), then every ``INTERVAL_S``.
FIRST_PASS_S = 5.0
INTERVAL_S = 60.0
#: A pass takes this many entries at most, and stops past this many seconds: a long transcript is read in the worker
#: thread, but a backlog drains over a few passes instead of holding it.
PER_PASS = 3
PASS_BUDGET_S = 20.0

#: A local entry holds a path and a few fields (about 500 bytes): a bigger file is a session post, never read here.
LOCAL_ENTRY_MAX_BYTES = 256 * 1024

_STOP = threading.Event()
_WAKE = threading.Event()
_THREAD: list[threading.Thread] = []
_PASS = threading.Lock()


def _entries(home: Path, spool):
    """The ``s-*`` entries of the local route, with each file's signature, oldest first."""
    from api.hooks import hook_client

    found = []
    for path in spool.entries(home):
        if not path.name.startswith("s-"):
            continue
        try:
            if path.stat().st_size > LOCAL_ENTRY_MAX_BYTES:
                continue                         # a session post the follower sends (a whole conversation): not read here
        except OSError:
            continue
        stamp = spool.signature(path)
        entry = spool.read(path)
        found.append((path, stamp, entry, bool(entry) and entry.get("route") == hook_client.LOCAL_ROUTE))
    return found


def _deliver(fields: dict, *, replica_mode: bool, settings) -> str:
    """Send one session the local way. ``"done"`` (written, or kept for the home), ``"empty"`` (read, nothing worth
    keeping), ``"refused"`` (not the harness's file for that session, or gone, or a malformed request) or ``"wait"``
    (try again later: no real bank to write into, a read that failed). Never raises."""
    try:
        if replica_mode:
            from api.services import replica_gateway

            try:
                answer = replica_gateway.keep_session(json.dumps(fields).encode("utf-8"))
            except replica_gateway.Refused:
                return "refused"
            return "done" if answer.get("status") == "queued" else "empty"
        from pydantic import ValidationError

        from api.config import get_settings
        from api.routers import capture as capture_router

        try:
            req = capture_router.TranscriptCaptureRequest(**fields)
        except (ValidationError, TypeError):
            return "refused"
        target, _memory_path, work, landed = capture_router.transcript_job(req, settings or get_settings())
        if target is None:
            return "wait"                # only the demo is open: nothing is read, the entry waits for a real bank
        result = work()
        if result.status == "refused":
            return "wait" if result.reason == "demo_bank" else "refused"
        landed(result)
        return "empty" if result.status == "empty" else "done"
    except OSError as exc:
        logger.info(f"local spool: a session was not read ({type(exc).__name__}); tried again later")
        return "wait"
    except Exception as exc:  # noqa: BLE001 - never a crash: the entry stays and the next pass tries again
        logger.warning(f"local spool: a session was not sent ({type(exc).__name__})")
        return "wait"


def drain_once(*, environ=None, settings=None, limit: int = PER_PASS, budget_s: float = PASS_BUDGET_S) -> dict:
    """One pass over the entries this backend's own hooks kept for it. ``{"done", "finished", "waiting"}``: sessions
    sent, entries removed without a session (gone, refused or empty — counted as ``rejected``) and entries left."""
    import os

    from api.hooks import hook_client
    from api.services import runtime_layout

    env = os.environ if environ is None else environ
    out = {"done": 0, "finished": 0, "waiting": 0}
    if not _PASS.acquire(blocking=False):
        return out                       # one pass at a time
    try:
        home = runtime_layout.cicada_home(env)
        spool = hook_client.spool_module()
        base = runtime_layout.local_backend_url(env)
        replica_mode = runtime_layout.is_replica(env)
        end = time.monotonic() + budget_s
        taken = 0
        for path, stamp, entry, local in _entries(home, spool):
            if entry is None:
                spool.remove(path, stamp)        # an entry nobody can read is never resent (``hook_spool``'s rule)
                continue
            target = spool.target_of(entry)
            if not local or target is None or not spool.same_server(target["base"], base):
                continue                         # a client's, or one kept for another address or port
            if not spool.due(entry):
                out["waiting"] += 1
                continue
            fields = entry.get("body")
            if taken >= limit or time.monotonic() >= end:
                out["waiting"] += 1
                continue
            taken += 1
            outcome = _deliver(fields, replica_mode=replica_mode, settings=settings) if isinstance(fields, dict) \
                else "refused"
            if outcome == "wait":
                out["waiting"] += 1
                continue
            removed = spool.remove(path, stamp)   # only while it is still the file that was sent
            if outcome == "done":
                out["done"] += 1
            else:
                out["finished"] += 1
                if removed:
                    spool.count_rejected(home)
        if out["done"] or out["finished"]:
            if replica_mode:
                from api.services import replica

                replica.wake()   # the follower sends what was kept and tells the home what is left: the light clears
            logger.info(f"local spool: {out['done']} session(s) sent, {out['finished']} finished with nothing to keep, "
                        f"{out['waiting']} waiting")
        return out
    finally:
        _PASS.release()


def pending() -> bool:
    """Does anything for this backend wait? A glob of the spool folder, never a read of its entries' bodies beyond
    the small JSON of each ``s-*`` file."""
    import os

    from api.hooks import hook_client
    from api.services import runtime_layout

    try:
        home = runtime_layout.cicada_home(os.environ)
        spool = hook_client.spool_module()
        return any(local for _p, _s, _e, local in _entries(home, spool))
    except Exception:  # noqa: BLE001
        return False


def _run(first_pass_s: float, interval_s: float) -> None:
    if _STOP.wait(first_pass_s):
        return
    while not _STOP.is_set():
        wait = interval_s
        try:
            if pending():
                out = drain_once()
                if (out["done"] or out["finished"]) and out["waiting"]:
                    wait = 1.0           # more waits behind the ones just sent: no need to wait a minute
        except Exception as exc:  # noqa: BLE001 - tried again on the next pass
            logger.info(f"local spool: pass skipped ({type(exc).__name__})")
        _WAKE.wait(wait)
        _WAKE.clear()


def start(*, first_pass_s: float = FIRST_PASS_S, interval_s: float = INTERVAL_S) -> bool:
    """Start the backend's drain of its own spool (the lifespan, in either mode). One thread; False if one runs."""
    if any(t.is_alive() for t in _THREAD):
        return False
    _STOP.clear()
    _WAKE.clear()
    thread = threading.Thread(target=_run, args=(first_pass_s, interval_s), name="cicada-local-spool", daemon=True)
    _THREAD[:] = [thread]
    thread.start()
    return True


def stop(timeout: float = 2.0) -> None:
    _STOP.set()
    _WAKE.set()
    for thread in list(_THREAD):
        if thread is not threading.current_thread():
            thread.join(timeout)
    _THREAD.clear()
