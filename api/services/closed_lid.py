"""Closed-lid Sleep runs — a BETA, off by default, behind an admin step the person runs themselves (G243 part 3).

macOS sleeps a MacBook when its lid closes, and no assertion (``keep_awake``) changes that. The one known way to
keep it reading is ``pmset -a disablesleep 1``, which needs root and is system-wide. Cicada never holds root. The
person runs ONE command in Terminal (shown in the app, exact, built here: ``install_command``) that writes a sudoers
rule for exactly two commands::

    <user> ALL=(root) NOPASSWD: /usr/bin/pmset -a disablesleep 1, /usr/bin/pmset -a disablesleep 0

sudoers matches arguments exactly, so the rule opens nothing else — but it is for the person's account, so **any
program running as them can use it**. That is said in words every time the beta is turned on (``WARNING``), with the
one way to remove it (``REMOVE_COMMAND``). Nothing here runs ``sudo`` to *install* anything: only the two commands
above (``_ALLOWED``, pinned by a test) and ``sudo -n -l`` to ask whether the rule exists.

The safety nets, in the order a hold goes through them (``engage``; each one that fails means NO hold, said as an
enum in ``last_end``, never a failed run):

1. the beta AND the keep-awake switch are on, this Mac has a battery (a desktop has no lid);
2. on power, battery at or above ``BATTERY_FLOOR_PCT``, not thermally throttled;
3. the rule is installed (``sudo -n -l``);
4. the recovery agent is installed (a launchd agent every minute: ``restore script`` below) and the journal is
   written FIRST, so a crash between the write and the read-back still leaves something to undo;
5. ``disablesleep 1``, then ``pmset -g`` is read back: if ``SleepDisabled`` is not 1 it did not take, and it is undone.

While held, a monitor beats the journal every ``TICK_S`` and ends the hold on: power lost, battery below the floor,
heat, or ``SleepDisabled`` no longer 1. The hold ends with the run (``sleep_cycle.run``'s outermost ``finally``),
with ``disablesleep 0`` read back. If the backend or the app dies, the journal's heartbeat goes stale (or its pid is
gone, or its hard ``MAX_HOLD_S`` passes) and the launchd agent undoes it within a minute — also at login/boot
(``RunAtLoad``); a restarting backend undoes a stale journal itself (``restore_stale``). Only a hold *Cicada* journaled
is ever undone: a ``disablesleep`` the person set themselves is never touched.

Not done (said in the PR and the warning): the panel is not darkened by Cicada. Insomnia dims it itself because, with
sleep off, macOS may not turn the lid-closed panel off; whether that holds on this Mac is the owner's lid test.
"""
from __future__ import annotations

import getpass
import logging
import os
import plistlib
import re
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

PMSET = "/usr/bin/pmset"
SUDO = "/usr/bin/sudo"
RULE_FILE = "/etc/sudoers.d/cicada-closed-lid"
#: The only privileged argv this module ever runs. A test fails if anything else gets to ``_priv``.
_ON = (SUDO, "-n", PMSET, "-a", "disablesleep", "1")
_OFF = (SUDO, "-n", PMSET, "-a", "disablesleep", "0")
_ALLOWED = frozenset({_ON, _OFF})

BATTERY_FLOOR_PCT = 20  # ends the hold below this even on power (a charger that cannot keep up); Insomnia ends at 10
TICK_S = 30.0
MAX_HOLD_S = 6 * 3600  # the journal's hard stop, whatever else is true
STALE_S = 180  # the recovery agent treats a heartbeat older than this as a dead owner
AGENT_LABEL = "com.cicada.closed-lid-restore"
AGENT_INTERVAL_S = 60

#: What the person is told every time the beta is turned on. One source: the API serves it and refuses an on without
#: the acknowledgement; the app shows it as it receives it.
WARNING = (
    "Closed lid is a beta. With the lid closed this Mac stays awake, so it runs hotter and uses far more battery than a sleeping "
    "Mac. Never use it with the Mac in a bag, a sleeve or under a blanket, and take it off if it gets hot. "
    "It needs an admin step you run yourself in Terminal, once: it lets any program running as you turn sleep on and off "
    "on this Mac without a password, until you remove it. Cicada uses it only on power, only while Sleep reads, and puts "
    "sleep back at the end; a small background helper (a launchd agent in your own Library, no extra permission) puts it "
    "back within a minute if Cicada stops. To remove the admin step: " + "sudo rm " + RULE_FILE
)
REMOVE_COMMAND = f"sudo rm {RULE_FILE}"
RESTORE_COMMAND = f"sudo {PMSET} -a disablesleep 0"

_USER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9._-]{0,31}$")  # a plain account name; nothing a shell or sudoers would read

# last_end reasons (enums, never text)
HELD = "held"
RUN_ENDED = "run-ended"
OFF = "off"
NO_RULE = "no-rule"
NO_POWER = "not-on-power"
NO_LID = "no-battery"
LOW_BATTERY = "battery-low"
HOT = "hot"
DIDNT_TAKE = "didnt-take"
RESET = "reset-by-something-else"
NO_HELPER = "no-helper"
UNAVAILABLE = "unavailable"

_lock = threading.Lock()
_state: dict = {"run_id": None, "stop": None, "thread": None, "last_end": None}


# ---- shell seams (tests replace ``_run``; nothing else spawns a process) -----------------------------------------

def _run(argv: list[str] | tuple[str, ...], timeout: float = 10.0) -> tuple[int, str]:
    try:
        done = subprocess.run(list(argv), capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
        return done.returncode, (done.stdout or "")
    except (OSError, subprocess.SubprocessError) as e:  # noqa: BLE001
        logger.warning("closed-lid: %s did not run (%s)", argv[0], type(e).__name__)
        return 127, ""


def _priv(argv: tuple[str, ...]) -> bool:
    """Run one of the two allowed privileged commands; True on exit 0. Anything else is a bug, not a request."""
    if tuple(argv) not in _ALLOWED:
        raise ValueError("not an allowed privileged command")
    return _run(argv)[0] == 0


# ---- the sudoers rule and its commands ---------------------------------------------------------------------------

def available() -> bool:
    """Only macOS has the tools; whether this Mac has a lid is read when a hold is tried (``NO_LID``)."""
    return sys.platform == "darwin" and os.path.exists(PMSET) and os.path.exists(SUDO)


def username() -> str | None:
    try:
        name = getpass.getuser()
    except Exception:  # noqa: BLE001
        return None
    return name if _USER_RE.match(name) else None


def rule_text(user: str) -> str:
    return f"{user} ALL=(root) NOPASSWD: {PMSET} -a disablesleep 1, {PMSET} -a disablesleep 0"


def install_command(user: str | None = None) -> str | None:
    """The exact line the person pastes into Terminal. It checks the rule's syntax with ``visudo`` BEFORE installing
    it (a broken sudoers file would break ``sudo`` itself), installs it root-owned 0440, and leaves a temp file behind
    never. None when the account name is not a plain one (nothing odd is ever put in a sudoers file)."""
    user = username() if user is None else user
    if not user or not _USER_RE.match(user):
        return None
    return (
        f'f=$(mktemp) && printf \'%s\\n\' {shlex.quote(rule_text(user))} > "$f" '
        f'&& sudo /usr/sbin/visudo -cf "$f" '
        f'&& sudo /usr/bin/install -m 0440 -o root -g wheel "$f" {RULE_FILE}; rm -f "$f"'
    )


def rule_installed() -> bool:
    """Ask sudo, without running anything: both commands permitted with no password. ``sudo -n -l <cmd>`` exits 0 only
    when the rule allows exactly that command line."""
    return all(_run([SUDO, "-n", "-l", PMSET, "-a", "disablesleep", v])[0] == 0 for v in ("1", "0"))


# ---- reading the Mac (no root) -----------------------------------------------------------------------------------

def parse_power(text: str) -> tuple[bool | None, int | None]:
    """``pmset -g batt`` → (on AC, battery %). Either is None when the text does not say."""
    on_ac = None
    m = re.search(r"Now drawing from '([^']+)'", text)
    if m:
        on_ac = m.group(1).strip().lower().startswith("ac")
    pct = re.search(r"(\d{1,3})%", text)
    return on_ac, (int(pct.group(1)) if pct else None)


def parse_hot(text: str) -> bool:
    """``pmset -g therm`` → True when macOS is limiting the CPU for heat (a limit under 100) or has recorded a thermal
    warning. The healthy text says "No thermal warning level has been recorded" and has no limit under 100."""
    for m in re.finditer(r"CPU_(?:Speed|Scheduler)_Limit\s*=\s*(\d+)", text):
        if int(m.group(1)) < 100:
            return True
    for line in text.splitlines():
        low = line.lower()
        if "thermal warning level" in low and "no thermal warning" not in low:
            return True
    return False


def parse_sleep_disabled(text: str) -> bool | None:
    m = re.search(r"SleepDisabled\s+(\d)", text)
    return None if not m else m.group(1) == "1"


def _power() -> tuple[bool | None, int | None]:
    rc, out = _run([PMSET, "-g", "batt"])
    return parse_power(out) if rc == 0 else (None, None)


def _hot() -> bool:
    rc, out = _run([PMSET, "-g", "therm"])
    return rc == 0 and parse_hot(out)


def _sleep_disabled() -> bool | None:
    rc, out = _run([PMSET, "-g"])
    return parse_sleep_disabled(out) if rc == 0 else None


# ---- the journal and the recovery agent -------------------------------------------------------------------------

def _home() -> Path:
    from api.services import runtime_layout

    return runtime_layout.cicada_home()


def journal_path() -> Path:
    return _home() / "closed-lid.journal"


def script_path() -> Path:
    return _home() / "bin" / "closed-lid-restore"


def plist_path() -> Path:
    return Path(os.environ.get("LAUNCH_AGENTS_DIR") or (Path.home() / "Library" / "LaunchAgents")) / f"{AGENT_LABEL}.plist"


def _write_journal(run_id: str, started: float) -> bool:
    now = int(time.time())
    body = f"run={run_id}\npid={os.getpid()}\nstarted={int(started)}\nbeat={now}\nuntil={int(started) + int(MAX_HOLD_S)}\n"
    try:
        path = journal_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(body)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
        return True
    except OSError as e:
        logger.warning("closed-lid: journal not written (%s)", type(e).__name__)
        return False


def _read_journal() -> dict[str, str] | None:
    try:
        text = journal_path().read_text()
    except OSError:
        return None
    return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)


def pending_restore() -> bool:
    return journal_path().exists()


#: The recovery agent's program: plain sh, no Cicada code, nothing from the network. It undoes only a hold a journal
#: says Cicada made, and only when the owner is gone (pid dead), silent (heartbeat stale) or past its hard stop.
RESTORE_SCRIPT = f"""#!/bin/sh
# Cicada closed-lid safety net. Run by launchd every {AGENT_INTERVAL_S} s while the beta is on.
J="${{CICADA_HOME:-$HOME/.cicada}}/closed-lid.journal"
[ -f "$J" ] || exit 0
pid=; beat=; until=
while IFS='=' read -r k v; do
  case "$k" in pid) pid=$v ;; beat) beat=$v ;; until) until=$v ;; esac
done < "$J"
now=$(/bin/date +%s)
alive=0; fresh=0; inside=0
case "$pid" in ''|*[!0-9]*) ;; *) /bin/kill -0 "$pid" 2>/dev/null && alive=1 ;; esac
case "$beat" in ''|*[!0-9]*) ;; *) [ $((now - beat)) -le {STALE_S} ] && fresh=1 ;; esac
case "$until" in ''|*[!0-9]*) ;; *) [ "$now" -lt "$until" ] && inside=1 ;; esac
[ "$alive" = 1 ] && [ "$fresh" = 1 ] && [ "$inside" = 1 ] && exit 0
{SUDO} -n {PMSET} -a disablesleep 0 || exit 1
{PMSET} -g | /usr/bin/grep -Eq 'SleepDisabled[[:space:]]+0' && /bin/rm -f "$J"
exit 0
"""


def _plist_bytes() -> bytes:
    return plistlib.dumps({
        "Label": AGENT_LABEL,
        "ProgramArguments": ["/bin/sh", str(script_path())],
        "StartInterval": AGENT_INTERVAL_S,
        "RunAtLoad": True,
        "EnvironmentVariables": {"CICADA_HOME": str(_home())},
        "StandardErrorPath": str(_home() / "closed-lid-restore.log"),
        "StandardOutPath": "/dev/null",
    })


def agent_installed() -> bool:
    return script_path().exists() and plist_path().exists()


def install_agent() -> bool:
    """Write the script and the launchd agent (the person's own domain, no root) and load it. False when it is not
    in place — the caller then does not turn the beta on, and a run never holds a lid without it."""
    if sys.platform != "darwin":
        return False
    try:
        script_path().parent.mkdir(parents=True, exist_ok=True)
        script_path().write_text(RESTORE_SCRIPT)
        os.chmod(script_path(), 0o755)
        plist_path().parent.mkdir(parents=True, exist_ok=True)
        plist_path().write_bytes(_plist_bytes())
    except OSError as e:
        logger.warning("closed-lid: helper not written (%s)", type(e).__name__)
        return False
    domain = f"gui/{os.getuid()}"
    _run(["/bin/launchctl", "bootout", f"{domain}/{AGENT_LABEL}"])  # absent is fine
    return _run(["/bin/launchctl", "bootstrap", domain, str(plist_path())])[0] == 0


def uninstall_agent() -> None:
    """Unload and delete the helper — never while a hold is still journaled (it is the only thing that would undo it)."""
    if pending_restore():
        return
    _run(["/bin/launchctl", "bootout", f"gui/{os.getuid()}/{AGENT_LABEL}"])
    for p in (plist_path(), script_path()):
        try:
            p.unlink()
        except OSError:
            pass


# ---- the hold ----------------------------------------------------------------------------------------------------

def holding() -> bool:
    return _state["run_id"] is not None


def last_end() -> str | None:
    return _state["last_end"]


def _restore() -> bool:
    """``disablesleep 0``, read back; the journal goes only when the read-back says 0. Idempotent."""
    ok = _priv(_OFF)
    if ok and _sleep_disabled() is False:
        try:
            journal_path().unlink()
        except OSError:
            pass
        return True
    logger.warning("closed-lid: sleep was not confirmed back on; the helper will retry within a minute")
    return False


def restore_stale() -> None:
    """At backend start: a journal left by a previous process is undone now, not a minute from now."""
    if holding() or not pending_restore():
        return
    try:
        _restore()
    except Exception as e:  # noqa: BLE001
        logger.warning("closed-lid: stale restore failed (%s)", type(e).__name__)


def _check() -> str | None:
    """The floors, in one place: the reason to end now, or None."""
    on_ac, pct = _power()
    if on_ac is not True:
        return NO_POWER
    if pct is not None and pct < BATTERY_FLOOR_PCT:
        return LOW_BATTERY
    if _hot():
        return HOT
    return None


def engage(run_id: str, *, beta: bool, keep_awake: bool) -> str:
    """Try to hold a closed lid for ``run_id``. Returns ``HELD`` or the reason it did not (an enum). Never raises."""
    try:
        return _engage(run_id, beta=beta, keep_awake=keep_awake)
    except Exception as e:  # noqa: BLE001
        logger.warning("closed-lid: not held (%s)", type(e).__name__)
        _state["last_end"] = UNAVAILABLE
        return UNAVAILABLE


def _engage(run_id: str, *, beta: bool, keep_awake: bool) -> str:
    if not (beta and keep_awake):
        return OFF  # not a refusal worth recording
    with _lock:
        if _state["run_id"] == run_id:
            return HELD
        if _state["run_id"] is not None:
            return UNAVAILABLE
        reason = _gate()
        if reason:
            _state["last_end"] = reason
            return reason
        started = time.time()
        if not _write_journal(run_id, started):
            _state["last_end"] = NO_HELPER
            return NO_HELPER
        if not _priv(_ON) or _sleep_disabled() is not True:
            _restore()
            _state["last_end"] = DIDNT_TAKE
            return DIDNT_TAKE
        stop = threading.Event()
        thread = threading.Thread(target=_monitor, args=(run_id, started, stop), name="closed-lid-monitor", daemon=True)
        _state.update(run_id=run_id, stop=stop, thread=thread, last_end=HELD)
        thread.start()
        return HELD


def _gate() -> str | None:
    if sys.platform != "darwin":
        return UNAVAILABLE
    on_ac, pct = _power()
    if pct is None:
        return NO_LID
    if on_ac is not True:
        return NO_POWER
    if pct < BATTERY_FLOOR_PCT:
        return LOW_BATTERY
    if _hot():
        return HOT
    if not agent_installed():
        return NO_HELPER
    if not rule_installed():
        return NO_RULE
    return None


def _monitor(run_id: str, started: float, stop: threading.Event) -> None:
    while not stop.wait(TICK_S):
        reason = _check()
        if reason is None and _sleep_disabled() is not True:
            reason = RESET
        if reason is None and time.time() - started >= MAX_HOLD_S:
            reason = RUN_ENDED
        if reason is not None:
            _end(run_id, reason)
            return
        _write_journal(run_id, started)


def _end(run_id: str, reason: str) -> None:
    with _lock:
        if _state["run_id"] != run_id:
            return
        stop = _state["stop"]
        _state.update(run_id=None, stop=None, thread=None, last_end=reason)
        if stop is not None:
            stop.set()
        try:
            _restore()
        except Exception as e:  # noqa: BLE001
            logger.warning("closed-lid: restore failed (%s)", type(e).__name__)


def release(run_id: str) -> None:
    """The run is over (every exit path): sleep goes back, read back. Idempotent; never raises."""
    try:
        _end(run_id, RUN_ENDED)
    except Exception as e:  # noqa: BLE001
        logger.warning("closed-lid: release failed (%s)", type(e).__name__)


def turn_on() -> bool:
    """The beta switch goes on: the helper must be in place first."""
    return install_agent()


def turn_off() -> None:
    """The beta switch goes off: end a hold now, undo a leftover one, drop the helper (only once nothing is journaled)."""
    with _lock:
        rid = _state["run_id"]
    if rid is not None:
        _end(rid, OFF)
    restore_stale()
    uninstall_agent()
