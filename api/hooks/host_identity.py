"""Which app launched this harness session, read from the hook's own ancestors (G228). Stdlib only, run by path.

A *host* is an app that drives a harness Cicada already captures, without being one itself. T3 Code runs Claude Code
through the Agent SDK with the person's user settings loaded, so Cicada's own capture and recall hooks already fire
inside a T3 Code thread, under the harness that ran it (Claude Code, Codex, Cursor). Nothing needs installing in
T3 Code. The one thing the hook cannot see in its payload is that T3 Code was the window the person typed into: the
payload carries a session id, a transcript path and a cwd, and T3 Code sets no variable of its own on the agent's
environment (checked against its source, commit 3748c5c2, 2026-10-29). So the hook looks at who started the
harness — the process chain above it — and names the host when one of the ancestors is T3 Code's own server.

What is read, and only this: each ancestor's parent pid, its executable path and, only for a ``node``/``bun``
ancestor (the ``npx t3`` and development servers), its argument vector. Read in this process (``libproc`` and
``sysctl`` on macOS, ``/proc`` on Linux), never through a subprocess, a shell or a file of the app's. Nothing read is
logged, stored or sent: the answer is one enum (``t3code``) or ``None``, and a failure at any step is ``None`` —
the capture goes ahead exactly as before, under its harness.

Matching (pure, :func:`host_of`), from T3 Code's source:
- the desktop app's server is the app's own executable run as Node (``…/T3 Code (Beta).app/Contents/MacOS/…``,
  ``apps/desktop/src/backend/DesktopBackendConfiguration.ts``);
- the command-line server and ``t3 service`` run the ``t3`` executable (``apps/server/package.json`` ``bin``; the
  Linux app's ``<root>/t3``);
- ``npx t3`` and a checkout run ``node …/t3/dist/bin.mjs`` (or ``…/.bin/t3``, or ``apps/server/src/bin.ts``).
Unverified against a running T3 Code (no live check on the owner's Mac); the capture log's ``via t3code`` is the
verification signal.
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
_RUNTIMES = frozenset({"node", "nodejs", "bun"})
_ARGV_MAX = 64 * 1024


def host_of(exe: str | None, argv: list[str] | None = None) -> str | None:
    """The host one process is, from its executable path and (for a JavaScript runtime) its arguments."""
    exe = exe or ""
    base = exe.rsplit("/", 1)[-1].lower()
    if "/T3 Code" in exe and ".app/" in exe:
        return "t3code"
    if base in ("t3", "t3code"):
        return "t3code"
    if base in _RUNTIMES and argv:
        for arg in argv[1:4]:
            a = arg.replace("\\", "/")
            if a.endswith("/t3/dist/bin.mjs") or a.endswith("/.bin/t3") or (
                    a.endswith("/apps/server/src/bin.ts") and "t3code" in a.lower()):
                return "t3code"
    return None


# --- reading a process -------------------------------------------------------------------------------------------


def _linux(pid: int) -> tuple[int | None, str | None, list[str] | None]:
    try:
        with open(f"/proc/{pid}/stat", "rb") as fh:
            stat = fh.read(4096).decode("utf-8", "replace")
        ppid = int(stat[stat.rindex(")") + 2:].split()[1])
    except (OSError, ValueError, IndexError):
        return None, None, None
    try:
        exe = os.readlink(f"/proc/{pid}/exe")
    except OSError:
        exe = None
    argv = None
    if exe and exe.rsplit("/", 1)[-1].lower() in _RUNTIMES:
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as fh:
                argv = [a.decode("utf-8", "replace") for a in fh.read(_ARGV_MAX).split(b"\0") if a]
        except OSError:
            argv = None
    return ppid, exe, argv


_libs = None


def _mac_libs():
    global _libs
    if _libs is None:
        import ctypes
        import ctypes.util

        libc = ctypes.CDLL(ctypes.util.find_library("c") or "/usr/lib/libSystem.B.dylib", use_errno=True)
        try:
            libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        except OSError:
            libproc = libc   # libproc's calls live in libSystem on current macOS
        _libs = (ctypes, libc, libproc)
    return _libs


#: ``PROC_PIDTBSDINFO`` and ``sizeof(struct proc_bsdinfo)``; ``pbi_ppid`` is the fifth uint32.
_PIDTBSDINFO, _BSDINFO_SIZE, _PPID_OFFSET = 3, 136, 16
_CTL_KERN, _KERN_PROCARGS2 = 1, 49


def _mac(pid: int) -> tuple[int | None, str | None, list[str] | None]:
    ctypes, libc, libproc = _mac_libs()
    info = ctypes.create_string_buffer(_BSDINFO_SIZE)
    if libproc.proc_pidinfo(pid, _PIDTBSDINFO, ctypes.c_uint64(0), info, _BSDINFO_SIZE) != _BSDINFO_SIZE:
        return None, None, None
    ppid = int.from_bytes(info.raw[_PPID_OFFSET:_PPID_OFFSET + 4], "little")
    path = ctypes.create_string_buffer(4096)
    n = libproc.proc_pidpath(pid, path, 4096)
    exe = path.raw[:n].decode("utf-8", "replace") if n > 0 else None
    argv = None
    if exe and exe.rsplit("/", 1)[-1].lower() in _RUNTIMES:
        argv = _mac_argv(pid)
    return ppid, exe, argv


def _mac_argv(pid: int) -> list[str] | None:
    ctypes, libc, _ = _mac_libs()
    mib = (ctypes.c_int * 3)(_CTL_KERN, _KERN_PROCARGS2, pid)
    size = ctypes.c_size_t(_ARGV_MAX)
    buf = ctypes.create_string_buffer(_ARGV_MAX)
    if libc.sysctl(mib, 3, buf, ctypes.byref(size), None, ctypes.c_size_t(0)) != 0:
        return None
    raw = buf.raw[:size.value]
    if len(raw) < 4:
        return None
    argc = int.from_bytes(raw[:4], "little")
    rest = raw[4:]
    end = rest.find(b"\0")          # the exec path, then NUL padding, then argv
    if end < 0:
        return None
    parts = [p for p in rest[end:].split(b"\0") if p]
    return [p.decode("utf-8", "replace") for p in parts[:max(0, argc)]]


def _reader():
    if sys.platform == "darwin":
        return _mac
    if sys.platform.startswith("linux"):
        return _linux
    return None


def detect(environ=None, *, start: int | None = None, read=None, depth: int = MAX_DEPTH) -> str | None:
    """The host above this process, or ``None``. Never raises. ``read`` (tests) maps a pid to
    ``(ppid, exe, argv)``; ``start`` is the first pid to look at (this process's parent by default)."""
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
            ppid, exe, argv = read(pid)
            found = host_of(exe, argv)
            if found:
                return found
            if ppid is None or ppid == pid:
                return None
            pid = ppid
    except Exception:  # noqa: BLE001 - a host is a label; reading it must never fail a capture
        return None
    return None
