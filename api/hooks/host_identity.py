"""Which app launched this harness session, read from the hook's own launch chain (G228). Stdlib only, run by path.

A *host* is an app that drives a harness Cicada already captures, without being one itself. T3 Code runs Claude Code
through the Agent SDK with the person's user settings loaded, so Cicada's own capture and recall hooks already fire
inside a T3 Code thread, under the harness that ran it (Claude Code, Codex, Cursor). Nothing needs installing in
T3 Code. The one thing the hook cannot see in its payload is that T3 Code was the window the person typed into: the
payload carries a session id, a transcript path and a cwd, and T3 Code sets no variable of its own on the agent's
environment (checked against its source, commit 3748c5c2, 2026-10-29). So the hook looks at who started the
harness — the process chain above it — and names the host when one of the ancestors is T3 Code's own server.

**What is read — the hook's own launch chain: parent pid and exec path only, bounded, in-process, never another
process's arguments or environment.** For each of at most :data:`MAX_DEPTH` ancestors: its parent pid
(``proc_pidinfo``'s BSD info on macOS, ``/proc/<pid>/stat`` on Linux) and its executable path (``proc_pidpath``;
``/proc/<pid>/exe``). No ``KERN_PROCARGS2``, no ``/proc/<pid>/cmdline`` or ``environ``, no subprocess, no shell, no
file of the app's. Nothing read is logged, stored or sent: the answer is one enum (``t3code``) or ``None``, and a
failure at any step is ``None`` — the capture goes ahead exactly as before, under its harness.

Matching (pure, :func:`host_of`), from T3 Code's source, on the exec path alone:
- the desktop app's server is the app's own executable run as Node (``…/T3 Code (Beta).app/Contents/MacOS/…``,
  ``apps/desktop/src/backend/DesktopBackendConfiguration.ts``);
- the command-line server and ``t3 service`` run an executable named ``t3`` (``apps/server/package.json`` ``bin``;
  the Linux app's ``<root>/t3``).
Not detected, by decision (coordinator, 2026-10-29): ``npx t3``, an npm-global install or a checkout, whose exec is
``node``/``bun`` — telling them apart would need the runtime's arguments. Those threads are still captured, under
their harness; only the ``host`` label is missing. Unverified against a running T3 Code; the capture log's
``via t3code`` is the verification signal.
"""
from __future__ import annotations

import os
import sys

#: The hosts this module can name (the backend keeps the same closed list, ``agent_catalog.HOSTS``).
HOSTS = ("t3code",)
#: How far up the chain to look: hook → (shell) → harness → (SDK worker) → host server → (app / launchd).
MAX_DEPTH = 10
#: A detached capture child (``capture._detach``) has lost its ancestors; its parent passes the answer down.
ENV = "CICADA_HOOK_HOST"


def host_of(exe: str | None) -> str | None:
    """The host one process is, from its executable path alone."""
    exe = exe or ""
    if "/T3 Code" in exe and ".app/" in exe:
        return "t3code"
    if exe.rsplit("/", 1)[-1] == "t3":
        return "t3code"
    return None


# --- reading a process: parent pid and exec path, nothing else --------------------------------------------------


def _linux(pid: int) -> tuple[int | None, str | None]:
    try:
        with open(f"/proc/{pid}/stat", "rb") as fh:
            stat = fh.read(4096).decode("utf-8", "replace")
        ppid = int(stat[stat.rindex(")") + 2:].split()[1])
    except (OSError, ValueError, IndexError):
        return None, None
    try:
        exe = os.readlink(f"/proc/{pid}/exe")
    except OSError:
        exe = None
    return ppid, exe


_libproc = None


def _mac_libproc():
    global _libproc
    if _libproc is None:
        import ctypes

        try:
            lib = ctypes.CDLL("/usr/lib/libproc.dylib")
        except OSError:
            lib = ctypes.CDLL("/usr/lib/libSystem.B.dylib")   # libproc's calls live in libSystem on current macOS
        _libproc = (ctypes, lib)
    return _libproc


#: ``PROC_PIDTBSDINFO`` and ``sizeof(struct proc_bsdinfo)``; ``pbi_ppid`` is the fifth uint32.
_PIDTBSDINFO, _BSDINFO_SIZE, _PPID_OFFSET = 3, 136, 16


def _mac(pid: int) -> tuple[int | None, str | None]:
    ctypes, lib = _mac_libproc()
    info = ctypes.create_string_buffer(_BSDINFO_SIZE)
    if lib.proc_pidinfo(pid, _PIDTBSDINFO, ctypes.c_uint64(0), info, _BSDINFO_SIZE) != _BSDINFO_SIZE:
        return None, None
    ppid = int.from_bytes(info.raw[_PPID_OFFSET:_PPID_OFFSET + 4], "little")
    path = ctypes.create_string_buffer(4096)
    n = lib.proc_pidpath(pid, path, 4096)
    return ppid, (path.raw[:n].decode("utf-8", "replace") if n > 0 else None)


def _reader():
    if sys.platform == "darwin":
        return _mac
    if sys.platform.startswith("linux"):
        return _linux
    return None


def detect(environ=None, *, start: int | None = None, read=None, depth: int = MAX_DEPTH) -> str | None:
    """The host above this process, or ``None``. Never raises. ``read`` (tests) maps a pid to ``(ppid, exe)``;
    ``start`` is the first pid to look at (this process's parent by default)."""
    environ = os.environ if environ is None else environ
    passed = str(environ.get(ENV) or "").strip()
    if passed in HOSTS:
        return passed
    read = read or _reader()
    if read is None:
        return None
    pid = os.getppid() if start is None else start
    try:
        for _ in range(depth):
            if not pid or pid <= 1:
                return None
            ppid, exe = read(pid)
            found = host_of(exe)
            if found:
                return found
            if ppid is None or ppid == pid:
                return None
            pid = ppid
    except Exception:  # noqa: BLE001 - a host is a label; reading it must never fail a capture
        return None
    return None
