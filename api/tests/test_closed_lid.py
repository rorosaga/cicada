"""G243 part 3: the closed-lid beta. Nothing here runs sudo, pmset, launchctl or a lid: `_run` is faked and the recovery
script is run against fake `sudo`/`pmset` files in a temp dir."""
from __future__ import annotations

import os
import stat
import subprocess
import time

import pytest

from api.services import closed_lid as cl
from api.services import sleep_run_prefs

BATT_AC = "Now drawing from 'AC Power'\n -InternalBattery-0 (id=1)\t80%; charging; 1:00 remaining present: true\n"
BATT_BAT = "Now drawing from 'Battery Power'\n -InternalBattery-0 (id=1)\t80%; discharging; 4:00 remaining present: true\n"
BATT_LOW = BATT_AC.replace("80%", "12%")
DESKTOP = "Now drawing from 'AC Power'\n"
THERM_OK = "Note: No thermal warning level has been recorded\nNote: No performance warning level has been recorded\n"
THERM_HOT = "CPU_Scheduler_Limit \t= 100\nCPU_Available_CPUs \t= 8\nCPU_Speed_Limit \t= 70\n"


class FakeMac:
    """Answers the commands closed_lid may run; records every one."""

    def __init__(self, tmp, batt=BATT_AC, therm=THERM_OK, rule=True, takes=True):
        self.calls, self.batt, self.therm, self.rule, self.takes = [], batt, therm, rule, takes
        self.disabled = False
        self.tmp = tmp
        self.journal_at_on = None

    def __call__(self, argv, timeout=10.0):
        argv = tuple(argv)
        self.calls.append(argv)
        if argv[:3] == (cl.SUDO, "-n", "-l"):
            return (0 if self.rule else 1), ""
        if argv == cl._ON:
            self.journal_at_on = cl.journal_path().exists()
            if self.takes:
                self.disabled = True
            return 0, ""
        if argv == cl._OFF:
            self.disabled = False
            return 0, ""
        if argv == (cl.PMSET, "-g", "batt"):
            return 0, self.batt
        if argv == (cl.PMSET, "-g", "therm"):
            return 0, self.therm
        if argv == (cl.PMSET, "-g"):
            return 0, f" SleepDisabled\t\t{1 if self.disabled else 0}\n"
        if argv[0] == "/bin/launchctl":
            return 0, ""
        raise AssertionError(f"unexpected command {argv}")

    def privileged(self):
        return [c for c in self.calls if c[0] == cl.SUDO and c[1:3] != ("-n", "-l")]


@pytest.fixture
def mac(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("LAUNCH_AGENTS_DIR", str(tmp_path / "LaunchAgents"))
    monkeypatch.setattr(cl.sys, "platform", "darwin")
    m = FakeMac(tmp_path)
    monkeypatch.setattr(cl, "_run", m)
    monkeypatch.setattr(cl, "_state", {"run_id": None, "stop": None, "thread": None, "last_end": None})
    monkeypatch.setattr(cl, "agent_installed", lambda: True)
    yield m
    if cl._state["stop"] is not None:
        cl._state["stop"].set()


def _engage(run="r1", beta=True, keep=True):
    return cl.engage(run, beta=beta, keep_awake=keep)


# ---- the switch and the command -----------------------------------------------------------------------------------

class _Reg:
    def __init__(self):
        self.p = {}

    def prefs(self):
        return self.p

    def set_pref(self, key, field, value):
        e = self.p.setdefault(key, {})
        e.pop(field, None) if value is None else e.__setitem__(field, value)


def test_the_beta_is_off_by_default_and_never_outlives_keep_awake():
    reg = _Reg()
    assert sleep_run_prefs.load(reg).closed_lid_beta is False
    sleep_run_prefs.write(reg, closed_lid_beta=True)
    assert sleep_run_prefs.load(reg).closed_lid_beta is False, "keep-awake is off: the beta reads off"
    sleep_run_prefs.write(reg, keep_awake=True, closed_lid_beta=True)
    assert sleep_run_prefs.load(reg).closed_lid_beta is True
    sleep_run_prefs.write(reg, keep_awake=False)
    assert sleep_run_prefs.load(reg).closed_lid_beta is False
    sleep_run_prefs.write(reg, keep_awake=True)
    assert sleep_run_prefs.load(reg).closed_lid_beta is False, "turning keep-awake back on does not bring the beta back"


def test_the_command_is_exact_and_narrow():
    cmd = cl.install_command("alice")
    assert "NOPASSWD: /usr/bin/pmset -a disablesleep 1, /usr/bin/pmset -a disablesleep 0'" in cmd
    assert cmd.count("pmset") == 2 and "ALL=(root)" in cmd and "ALL=(ALL)" not in cmd
    assert "visudo -cf" in cmd and cmd.index("visudo") < cmd.index("install -m 0440"), "syntax is checked before install"
    assert cmd.endswith('rm -f "$f"') and "/etc/sudoers.d/cicada-closed-lid" in cmd
    assert cl.REMOVE_COMMAND == "sudo rm /etc/sudoers.d/cicada-closed-lid"
    assert cl.install_command("Alice.B") is not None
    for bad in ("a b", "a;rm", "", "a$(x)", "-x"):
        assert cl.install_command(bad) is None, bad


def test_the_warning_says_what_it_must():
    w = cl.WARNING.lower()
    for word in ("beta", "hotter", "battery", "bag", "admin step", "any program running as you", cl.REMOVE_COMMAND):
        assert word in w or word in cl.WARNING, word


def test_pmset_text_parsing():
    assert cl.parse_power(BATT_AC) == (True, 80) and cl.parse_power(BATT_BAT) == (False, 80)
    assert cl.parse_power(DESKTOP) == (True, None)
    assert cl.parse_hot(THERM_OK) is False and cl.parse_hot(THERM_HOT) is True
    assert cl.parse_hot("Note: thermal warning level 2 was recorded") is True
    assert cl.parse_sleep_disabled(" SleepDisabled\t\t1\n") is True and cl.parse_sleep_disabled("nothing") is None


# ---- the privileged commands are exactly two ---------------------------------------------------------------------

def test_only_the_two_allowed_commands_can_be_run_as_root(mac):
    for argv in ((cl.SUDO, "-n", cl.PMSET, "-a", "disablesleep", "2"), (cl.SUDO, "-n", "/bin/ls"),
                 (cl.SUDO, cl.PMSET, "-a", "disablesleep", "1"), (cl.SUDO, "-n", cl.PMSET, "schedule", "x")):
        with pytest.raises(ValueError):
            cl._priv(argv)
    assert not mac.calls


# ---- engage / release --------------------------------------------------------------------------------------------

def test_a_hold_journals_first_reads_back_and_restores_at_the_end(mac):
    assert _engage() == cl.HELD and cl.holding()
    assert mac.journal_at_on is True, "the journal exists before sleep is switched off"
    assert mac.disabled and cl.journal_path().exists()
    assert mac.privileged() == [cl._ON]
    cl.release("r1")
    assert not cl.holding() and not mac.disabled and not cl.journal_path().exists()
    assert mac.privileged() == [cl._ON, cl._OFF] and cl.last_end() == cl.RUN_ENDED
    cl.release("r1")  # twice is fine
    assert mac.privileged() == [cl._ON, cl._OFF]


@pytest.mark.parametrize("kw,reason", [({"beta": False}, cl.OFF), ({"keep": False}, cl.OFF)])
def test_not_chosen_is_never_a_hold(mac, kw, reason):
    assert _engage(**kw) == reason and not mac.calls


@pytest.mark.parametrize("setup,reason", [
    (dict(batt=BATT_BAT), cl.NO_POWER),
    (dict(batt=BATT_LOW), cl.LOW_BATTERY),
    (dict(batt=DESKTOP), cl.NO_LID),
    (dict(therm=THERM_HOT), cl.HOT),
    (dict(rule=False), cl.NO_RULE),
])
def test_every_floor_means_no_hold(mac, setup, reason):
    for k, v in setup.items():
        setattr(mac, k, v)
    assert _engage() == reason
    assert mac.privileged() == [] and not cl.journal_path().exists() and not cl.holding()
    assert cl.last_end() == reason


def test_no_helper_no_hold(mac, monkeypatch):
    monkeypatch.setattr(cl, "agent_installed", lambda: False)
    assert _engage() == cl.NO_HELPER and mac.privileged() == []


def test_a_hold_that_did_not_take_is_undone(mac):
    mac.takes = False
    assert _engage() == cl.DIDNT_TAKE
    assert mac.privileged() == [cl._ON, cl._OFF] and not cl.journal_path().exists() and not cl.holding()


def test_an_unwritable_journal_means_no_hold(mac, monkeypatch):
    monkeypatch.setattr(cl, "_write_journal", lambda *a: False)
    assert _engage() == cl.NO_HELPER and mac.privileged() == []


def test_the_monitor_ends_the_hold_when_power_is_lost(mac, monkeypatch):
    monkeypatch.setattr(cl, "TICK_S", 0.02)
    assert _engage() == cl.HELD
    mac.batt = BATT_BAT
    deadline = time.time() + 3
    while cl.holding() and time.time() < deadline:
        time.sleep(0.02)
    assert not cl.holding() and cl.last_end() == cl.NO_POWER
    assert not mac.disabled and not cl.journal_path().exists()


def test_the_monitor_ends_the_hold_when_something_else_reset_sleep(mac, monkeypatch):
    monkeypatch.setattr(cl, "TICK_S", 0.02)
    assert _engage() == cl.HELD
    mac.disabled = False
    deadline = time.time() + 3
    while cl.holding() and time.time() < deadline:
        time.sleep(0.02)
    assert cl.last_end() == cl.RESET and not cl.journal_path().exists()


def test_a_stale_journal_is_undone_at_start_and_a_fresh_hold_is_not(mac):
    cl._write_journal("old", time.time() - 100)
    mac.disabled = True
    cl.restore_stale()
    assert not mac.disabled and not cl.journal_path().exists()
    assert _engage() == cl.HELD
    before = len(mac.privileged())
    cl.restore_stale()
    assert len(mac.privileged()) == before, "a live hold is never undone by the start-up check"


def test_turning_the_beta_off_ends_a_hold_and_keeps_the_helper_while_something_is_journaled(mac, tmp_path):
    cl.install_agent()
    assert cl.script_path().exists() and cl.plist_path().exists()
    assert _engage() == cl.HELD
    cl.turn_off()
    assert not cl.holding() and not mac.disabled
    assert not cl.script_path().exists() and not cl.plist_path().exists()
    cl.install_agent()
    cl._write_journal("x", time.time())
    mac.rule = False  # restore cannot run: the journal and the helper stay
    cl._run = lambda argv, timeout=10.0: (1, "") if tuple(argv) == cl._OFF else mac(argv, timeout)
    cl.turn_off()
    assert cl.journal_path().exists() and cl.script_path().exists()


# ---- the helper ---------------------------------------------------------------------------------------------------

def test_the_helper_is_a_launchd_agent_in_the_persons_own_library(mac):
    import plistlib

    assert cl.install_agent() is True
    plist = plistlib.loads(cl.plist_path().read_bytes())
    assert plist["Label"] == cl.AGENT_LABEL and plist["StartInterval"] == 60 and plist["RunAtLoad"] is True
    assert plist["ProgramArguments"] == ["/bin/sh", str(cl.script_path())]
    assert cl.script_path().stat().st_mode & stat.S_IXUSR
    assert str(cl.plist_path()).startswith(os.environ["LAUNCH_AGENTS_DIR"])
    launch = [c for c in mac.calls if c[0] == "/bin/launchctl"]
    assert [c[1] for c in launch] == ["bootout", "bootstrap"]


def _run_script(tmp_path, journal: str | None):
    """Run the real recovery script against fake sudo/pmset; returns (sudo calls, journal still there)."""
    home = tmp_path / "h"
    home.mkdir(exist_ok=True)
    log = tmp_path / "sudo.log"
    log.write_text("")
    fake_sudo, fake_pmset = tmp_path / "sudo", tmp_path / "pmset"
    fake_sudo.write_text(f'#!/bin/sh\necho "$@" >> {log}\nexit 0\n')
    fake_pmset.write_text("#!/bin/sh\necho ' SleepDisabled 0'\n")
    for f in (fake_sudo, fake_pmset):
        f.chmod(0o755)
    script = tmp_path / "restore"
    script.write_text(cl.RESTORE_SCRIPT.replace(cl.SUDO, str(fake_sudo)).replace(cl.PMSET, str(fake_pmset)))
    j = home / "closed-lid.journal"
    j.unlink(missing_ok=True)
    if journal is not None:
        j.write_text(journal)
    done = subprocess.run(["/bin/sh", str(script)], env={"CICADA_HOME": str(home), "PATH": "/usr/bin:/bin"}, capture_output=True)
    assert done.returncode == 0, done.stderr
    return log.read_text().strip().splitlines(), j.exists()


def _j(pid=None, beat=0, until=3600):
    now = int(time.time())
    return f"run=x\npid={os.getpid() if pid is None else pid}\nbeat={now - beat}\nuntil={now + until}\n"


def test_the_recovery_script_restores_only_what_is_stale(tmp_path):
    assert _run_script(tmp_path, None) == ([], False), "no journal: nothing is touched (a person's own setting stays)"
    assert _run_script(tmp_path, _j()) == ([], True), "a live owner with a fresh beat keeps its hold"
    for stale in (_j(beat=600), _j(pid=2 ** 22 + 7), _j(until=-5), "garbage\n", "pid=\nbeat=\n"):
        calls, left = _run_script(tmp_path, stale)
        assert calls == [f"-n {tmp_path / 'pmset'} -a disablesleep 0"] and left is False, stale
