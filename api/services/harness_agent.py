"""Cicada's own agent: a real harness session that finds an answer out (ruling 83, owner 2026-11-25; G209).

The owner: "i always said cicada should have by default access to the computer to look for stuff and use the browser
with the browser harness skill and everything. Also to use the power of the harness itself (like claude code)". Ruling 54's
step was a model with no tool at all whose every query passed code; this is the person's own Claude Code, run as they
would run it, to work one open question. **It finds things out. Cicada's own code does every write to memory.**

**The grant is a permission set, enforced by the harness before a call runs, never by the prompt alone.** One session is
``claude -p`` in the pinned safe mode (no CLAUDE.md, skills, plugins, hooks, MCP servers or user settings: so it cannot
capture itself, recall, or be widened by anything the person configured) with ``--permission-mode dontAsk`` and
``--permission-prompts none``: whatever is not allowed below is refused at once and never asked. What is allowed:

* ``Read``, ``Glob`` and ``Grep``, each limited to :func:`read_roots` (the person's own folders; never a dot-folder, never
  ``Library``, and unless the person started this from their own shell never Documents, Desktop or Downloads, which a
  child of the backend cannot list and would raise a prompt nobody answers; measured on this machine) and refused on the
  bank, Cicada's home and secret-shaped files. No ``Write``, ``Edit``, ``NotebookEdit`` or any other tool exists.
* ``WebSearch`` and ``WebFetch``: the plan's own web tools (a read of a public address; no cookies, nothing signed in).
* ``Bash``, only for the exact program prefix ``python3 <read_browser.py>``: :mod:`api.harness_tools.read_browser`, whose
  verbs only read (open an address in a new tab of the person's own browser through the harness's CLI, read its text, close
  the tabs it opened). It never starts a browser, clicks, types or signs in; a page asking for a password is reported
  ``NEEDS A LOGIN`` and left. Every other command, a compound one (``;``, ``&&``, a pipe, a redirect, ``$(...)``) included,
  is refused: measured on ``claude`` 2.1.331 with an allowlist of one prefix.
* Not offered in this slice: reading an app on screen (the macOS harness), which could not be proven without driving the
  person's own apps.

**What a page may do.** Everything the session reads is data. A page that tells the agent to run something finds no tool
that can: no write exists, no command but the one above, no file outside the roots. What it can still cause is a read:
an address opened, a file read. Every call is the audit (:class:`Audit`), kept with the settle, and a call the harness
refused is listed beside it (``denied``): the dry run and the battery report both.

**The agent's answer is checked by code.** It returns an answer, evidence (an address or a file path, a quote of at most
:data:`MAX_QUOTE_CHARS` characters) and a confidence it must justify. :func:`verify` accepts an item only when the address
or file is one the audit shows was really read and the quote is located (exact, then whitespace-folded, then case-folded;
never fuzzy) in what that call returned; a page that wanted a login is never evidence; an option or an answer must be
carried by the quote's own words. Anything less is no answer.

**A private person's name** may be searched in public (owner 2026-11-25: "i dont see why we cant search in public too"); the
audit of every query and address is transparency now, shown beside the settle. The bank's folder is readable (read-only) so
a pair is read like a person would read it.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import threading
import time
import unicodedata
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from loguru import logger

RULE = "found_by_agent"
#: One question's bounds: tool calls and wall clock. A session over either is killed and the question left as it was.
MAX_CALLS = 14
SESSION_TIMEOUT_S = 240.0
MAX_QUOTE_CHARS = 240
MAX_EVIDENCE = 3
MIN_CONFIDENCE = 0.8
#: A pair read as two people: its gate is two located lines, one per side, in the bank's own conversations; undo is one tap.
PAIR_MIN_CONFIDENCE = 0.7
RESULT_KEEP = 60000   # per tool result, kept in memory only to locate a quote (never stored)

#: Folders a child of the backend cannot list (measured: a launchd child, no prior grant, lists the home and ordinary
#: folders but not these) and whose first access would raise a prompt nobody is there to answer.
PROTECTED = frozenset({"Documents", "Desktop", "Downloads", "Pictures", "Movies", "Music", "Library", "Public",
                       "Applications"})
#: Secret-shaped files, refused wherever they are inside a root.
SECRET_GLOBS = ("**/.env", "**/.env.*", "**/*.pem", "**/*.key", "**/id_rsa*", "**/id_ed25519*", "**/*.p12",
                "**/.netrc", "**/.npmrc", "**/.git-credentials", "**/credentials*.json")
BROWSE_SCRIPT = Path(__file__).resolve().parent.parent / "harness_tools" / "read_browser.py"

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["answered", "not_found", "needs_login", "cannot_tell"]},
        "option": {"type": ["string", "null"]},
        "answer": {"type": ["string", "null"]},
        "confidence": {"type": "number"},
        "why": {"type": "string"},
        "evidence": {"type": "array", "items": {"type": "object", "properties": {
            "where": {"type": "string"}, "quote": {"type": "string"}, "side": {"type": "string", "enum": ["a", "b"]}},
            "required": ["where", "quote"]}},
        "mixed": {"type": "object", "properties": {"a": {"type": "array", "items": {"type": "string"}},
                                                    "b": {"type": "array", "items": {"type": "string"}}}},
        "found": {"type": "string"},
    },
    "required": ["status", "confidence", "why", "evidence"],
}


# --------------------------------------------------------------------------- the grant


@dataclass(frozen=True)
class Policy:
    roots: tuple[str, ...] = ()          # folders the file tools may read
    refused: tuple[str, ...] = ()        # folders inside a root they may not (the bank, Cicada's home)
    browser: bool = False                # the read-only browser window is offered
    web: bool = True
    python: str = "python3"


def read_roots(home: Path, *, attended: bool, refused: tuple[str, ...] = ()) -> tuple[str, ...]:
    """The person's own top-level folders the file tools may read: every plain folder of the home that is not a
    dot-folder (config, keys, tokens) and, unless the person started this from their own shell (``attended``), not a
    protected one. Listed here, so no rule has to describe the whole home and no search starts in a folder it may not
    read. A folder holding a refused path is still listed: the refusal rules name the path."""
    out: list[str] = []
    try:
        for entry in sorted(os.scandir(home), key=lambda e: e.name):
            if not entry.is_dir(follow_symlinks=False) or entry.name.startswith("."):
                continue
            if entry.name in PROTECTED and not (attended and entry.name not in ("Library", "Applications")):
                continue
            out.append(entry.path)
    except OSError:
        return ()
    return tuple(out)


def _rule(tool: str, path: str) -> str:
    return f"{tool}(/{path.rstrip('/')}/**)"      # a leading `//` is the harness's spelling of an absolute path


def settings_for(policy: Policy) -> dict:
    """The ``--settings`` object: what the session may call and what it may never read. No write tool is listed anywhere."""
    allow: list[str] = []
    for root in policy.roots:
        allow += [_rule(t, root) for t in ("Read", "Glob", "Grep")]
    if policy.web:
        allow += ["WebSearch", "WebFetch"]
    if policy.browser:
        allow.append(f"Bash({policy.python} {BROWSE_SCRIPT}:*)")
    deny = ["Write", "Edit", "NotebookEdit"]
    for path in policy.refused:
        deny += [_rule(t, path) for t in ("Read", "Glob", "Grep")]
    for glob in SECRET_GLOBS:
        deny += [f"Read({glob})", f"Grep({glob})", f"Glob({glob})"]
    return {"permissions": {"allow": allow, "deny": deny}}


def tools_for(policy: Policy) -> str:
    tools = ["Read", "Glob", "Grep"]
    if policy.web:
        tools += ["WebSearch", "WebFetch"]
    if policy.browser:
        tools.append("Bash")
    return ",".join(tools)


def build_argv(*, model: str, system_prompt: str, policy: Policy, binary: str = "claude") -> list[str]:
    """The session's invocation. Never ``--bare`` (it would ignore the plan's sign-in), never an MCP config, never a
    permission mode that asks: ``dontAsk`` with ``--permission-prompts none`` refuses what is not listed."""
    from api.services import agent_engine

    if not agent_engine.is_valid_model_id(model):
        raise ValueError("invalid model")
    return [binary, "-p", "--output-format", "stream-json", "--verbose", "--safe-mode", "--strict-mcp-config",
            "--setting-sources", "", "--no-session-persistence", "--permission-mode", "dontAsk",
            "--permission-prompts", "none", "--tools", tools_for(policy),
            "--settings", json.dumps(settings_for(policy), separators=(",", ":")),
            "--model", model, f"--system-prompt={system_prompt}",
            "--json-schema", json.dumps(ANSWER_SCHEMA, separators=(",", ":"))]


# --------------------------------------------------------------------------- the session and its audit


@dataclass
class Call:
    id: str
    tool: str
    kind: str          # file | file_search | search | address | browser | shell
    what: str          # the address, the path, the query: what the audit shows
    result: str = ""   # kept in memory to locate a quote; never stored
    denied: bool = False
    error: bool = False

    def line(self) -> dict:
        return {"tool": self.kind, "what": self.what[:300], **({"denied": True} if self.denied else {})}


@dataclass
class Session:
    calls: list[Call] = field(default_factory=list)
    answer: dict | None = None
    stopped: str = ""          # "" | timeout | too_many_calls | no_binary | failed
    seconds: float = 0.0
    cost: float | None = None
    model: str = ""
    final_text: str = ""

    @property
    def audit(self) -> list[dict]:
        return [c.line() for c in self.calls]

    @property
    def denied(self) -> list[Call]:
        return [c for c in self.calls if c.denied]


_DENIED = re.compile(r"permission to use .* has been denied|don't ask mode|was denied|not allowed", re.I)


def classify(name: str, inp: dict) -> tuple[str, str]:
    """``(kind, what)`` for one tool call: the line the audit shows."""
    if name == "Read":
        return "file", str(inp.get("file_path") or "")
    if name in ("Glob", "Grep"):
        return "file_search", f"{inp.get('pattern') or ''} in {inp.get('path') or '.'}"
    if name == "WebSearch":
        return "search", str(inp.get("query") or "")
    if name == "WebFetch":
        return "address", str(inp.get("url") or "")
    if name == "Bash":
        command = str(inp.get("command") or "")
        try:
            parts = shlex.split(command)
        except ValueError:
            parts = []
        if len(parts) >= 4 and parts[2:3] != [] and Path(parts[1]).name == "read_browser.py" and parts[2] == "open":
            return "address", parts[3]
        if len(parts) >= 3 and Path(parts[1]).name == "read_browser.py":
            return "browser", " ".join(parts[2:])
        return "shell", command[:200]
    return "shell", name


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(b.get("text") or "") for b in content if isinstance(b, dict))
    return ""


def _answer_of(envelope: dict) -> dict | None:
    structured = envelope.get("structured_output")
    if isinstance(structured, dict):
        return structured
    text = str(envelope.get("result") or "").strip()
    match = re.search(r"\{.*\}", text, re.S)
    if match:
        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else None
        except ValueError:
            return None
    return None


def run(argv: list[str], prompt: str, *, cwd: str, env: dict[str, str], timeout: float = SESSION_TIMEOUT_S,
        max_calls: int = MAX_CALLS, on_call: Callable[[Call], None] | None = None) -> Session:
    """Run one session, reading its stream as it goes: the audit grows call by call (``on_call`` shows each as it is made),
    and a session over its call count or its clock is killed, the question left as it was. Never raises."""
    session = Session()
    started = time.monotonic()
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                cwd=cwd, env=env, start_new_session=True)
    except OSError:
        session.stopped = "no_binary"
        return session
    by_id: dict[str, Call] = {}
    killed = threading.Event()

    def stop(why: str) -> None:
        session.stopped = session.stopped or why
        killed.set()
        try:
            os.killpg(proc.pid, 9)
        except OSError:
            pass

    timer = threading.Timer(timeout, stop, args=("timeout",))
    timer.daemon = True
    timer.start()
    try:
        assert proc.stdin is not None and proc.stdout is not None
        proc.stdin.write(prompt)
        proc.stdin.close()
        for raw in proc.stdout:
            try:
                event = json.loads(raw)
            except ValueError:
                continue
            kind = event.get("type")
            message = event.get("message") or {}
            if kind == "assistant":
                for block in message.get("content") or []:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        if block.get("name") == "StructuredOutput":   # the answer itself, not a call on the world
                            continue
                        inp = block.get("input") if isinstance(block.get("input"), dict) else {}
                        what_kind, what = classify(str(block.get("name") or ""), inp)
                        call = Call(str(block.get("id") or ""), str(block.get("name") or ""), what_kind, what)
                        session.calls.append(call)
                        by_id[call.id] = call
                        if on_call is not None:
                            on_call(call)
                        if len(session.calls) > max_calls:
                            stop("too_many_calls")
                    elif isinstance(block, dict) and block.get("type") == "text":
                        session.final_text = str(block.get("text") or "")
            elif kind == "user":
                for block in message.get("content") or []:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        call = by_id.get(str(block.get("tool_use_id") or ""))
                        if call is not None:
                            text = _text_of(block.get("content"))
                            call.result = text[:RESULT_KEEP]
                            call.error = bool(block.get("is_error"))
                            call.denied = bool(_DENIED.search(text[:300])) and (call.error or "denied" in text[:300].lower())
            elif kind == "result":
                session.answer = _answer_of(event)
                cost = event.get("total_cost_usd")
                session.cost = float(cost) if isinstance(cost, (int, float)) else None
                usage = event.get("modelUsage")
                if isinstance(usage, dict) and usage:
                    session.model = max(usage, key=lambda k: int((usage[k] or {}).get("outputTokens") or 0))
                if event.get("is_error"):
                    session.stopped = session.stopped or "failed"
        proc.wait(timeout=10)
    except Exception as exc:  # noqa: BLE001 - a session never raises into Sleep
        logger.info(f"harness session: stopped ({type(exc).__name__})")
        session.stopped = session.stopped or "failed"
        stop("failed")
    finally:
        timer.cancel()
        session.seconds = round(time.monotonic() - started, 1)
        if proc.poll() is None:
            stop("failed")
    if killed.is_set():
        session.answer = None
    return session


# --------------------------------------------------------------------------- checking the answer


def fold(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(text or "")).casefold().split())


def located(quote: str, text: str) -> bool:
    """Is ``quote`` in ``text``: exact, then whitespace-folded, then case-folded. Never fuzzy (G118)."""
    if not quote.strip():
        return False
    return quote in text or " ".join(quote.split()) in " ".join(text.split()) or fold(quote) in fold(text)


def _same_address(a: str, b: str) -> bool:
    def norm(u: str) -> str:
        p = urllib.parse.urlsplit(u.strip())
        return f"{p.scheme}://{p.netloc.lower()}{p.path.rstrip('/')}{'?' + p.query if p.query else ''}"
    return bool(a and b) and norm(a) == norm(b)


def _strip_place(where: str) -> str:
    return re.split(r"[,:#( ]\s*(?:line\s*)?\d+\)?$", where.strip())[0]


def _names_file(where: str, read: str) -> bool:
    """``where`` is the file that was read, optionally followed by a place in it ("<path>, line 2", "<path>:2")."""
    if not read:
        return False
    where = _strip_place(where)
    return where == read or (not where.startswith("/") and read.endswith("/" + where.lstrip("./")))


@dataclass
class Evidence:
    where: str
    kind: str       # address | file
    quote: str


def verify(answer: dict | None, session: Session, min_confidence: float = MIN_CONFIDENCE) -> tuple[list[Evidence], str]:
    """``(evidence the code could check, why not)``. An item counts only when what it names was really opened or read in
    this session, what that call returned holds the quote, and the page did not ask for a login."""
    if not isinstance(answer, dict) or answer.get("status") != "answered":
        return [], str((answer or {}).get("status") or "no_answer")
    try:
        confidence = float(answer.get("confidence"))
    except (TypeError, ValueError):
        confidence = 0.0
    if confidence < min_confidence:
        return [], "low_confidence"
    out: list[Evidence] = []
    for item in (answer.get("evidence") or [])[:MAX_EVIDENCE]:
        if not isinstance(item, dict):
            continue
        where, quote = str(item.get("where") or "").strip(), " ".join(str(item.get("quote") or "").split())
        if not where or not quote or len(quote) > MAX_QUOTE_CHARS:
            continue
        for call in session.calls:
            if call.denied or call.error or "NEEDS A LOGIN" in call.result[:600]:
                continue
            if call.kind == "address" and _same_address(where, call.what) and located(quote, call.result):
                out.append(Evidence(where, "address", quote))
                break
            if call.kind == "file" and _names_file(where, call.what) and located(quote, call.result):
                out.append(Evidence(call.what, "file", quote))   # the path as it was read, even when the agent wrote it shorter
                break
            if call.kind == "file_search" and not where.startswith(("http://", "https://")) and located(quote, call.result):
                base = _strip_place(where)
                if base and base in call.result:   # a search that printed the line, under the file's own path
                    out.append(Evidence(base, "file", quote))
                    break
            if call.kind == "search" and where.startswith(("http://", "https://")) and where in call.result \
                    and located(quote, call.result):
                out.append(Evidence(where, "address", quote))
                break
    return (out, "") if out else ([], "evidence_not_located")


def side_of(answer: dict, evidence: "Evidence") -> str:
    """Which side (a or b) of a pair the agent filed this evidence under; the quote and place must match one item."""
    for item in answer.get("evidence") or []:
        if isinstance(item, dict) and _names_file(str(item.get("where") or "").strip(), evidence.where) \
                and " ".join(str(item.get("quote") or "").split()) == evidence.quote and item.get("side") in ("a", "b"):
            return str(item["side"])
    return ""


def in_folder(path: str, folder: str) -> bool:
    try:
        return Path(path).resolve().is_relative_to(Path(folder).resolve() / "episodes")
    except (OSError, ValueError):
        return False


def mixed_of(answer: dict | None, memory_path: Path) -> dict | None:
    """The conversations the agent says belong to each person of a mixed page: only ids of conversations that exist."""
    raw = (answer or {}).get("mixed")
    if not isinstance(raw, dict):
        return None
    out = {}
    for side in ("a", "b"):
        ids = [str(i) for i in (raw.get(side) or []) if re.fullmatch(r"ep_[0-9A-Za-z_-]{1,40}", str(i))
               and (Path(memory_path) / "episodes" / f"{i}.md").is_file()]
        if ids:
            out[side] = ids[:20]
    return out or None


def carried(text: str, evidence: list[Evidence]) -> bool:
    """Do the quotes themselves say ``text`` (an option's label, a free-text answer)? Folded containment, never a guess."""
    want = fold(text)
    return bool(want) and any(want in fold(e.quote) for e in evidence)


# --------------------------------------------------------------------------- tools and the environment


def browser_ready(python: str = "python3", timeout: float = 20.0) -> bool:
    """Is the person's own browser reachable through the harness, right now, with no start of anything? One cheap read."""
    try:
        out = subprocess.run([python, str(BROWSE_SCRIPT), "status"], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return out.stdout.strip() == "ready"


def session_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """The environment Cicada spawns every CLI under (provider keys stripped, capture and recall off), plus nothing else
    of Cicada's: the session cannot see the bank's path or Cicada's home."""
    from api.services.connections import base

    env = base.scrubbed_env("claude")
    for key in ("CICADA_HOME", "CICADA_MEMORY_PATH", "MEMORY_PATH", "CICADA_API_TOKEN", "CICADA_TOKEN"):
        env.pop(key, None)
    env["CICADA_BROWSE_STATE"] = str(Path(env.get("TMPDIR", "/tmp")) / f"cicada-browse-{os.getpid()}.json")
    env.update(extra or {})
    return env
