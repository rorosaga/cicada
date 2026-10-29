"""The `cicada` command's app commands: what the Cicada app does, from a shell (G180, TODO ruling 21).

Two kinds of command live here, and `cli_map` says which each one is (`Row.via`):

- **`bank`** — a read of the bank's own files (pages, the graph, the inbox, feeds, the Sleep history, the bank
  list). It runs in this process from the CLI's one bootstrap, like every other read, so it works with the
  app's backend down (ruling 21's reason).
- **`backend`** — an action on state the running backend owns: the Sleep run and its schedule, engine and
  options, the search index and model (a re-embed runs in the backend's child process), settings it reads and
  guards, a bank switch, and every page write the app makes through a route that holds the bank's write
  admission. These go to the backend's HTTP API with the token, exactly as the app sends them — the CLI never
  runs a second Sleep, never writes state the backend owns, and is one more client of the routes a browser
  front end would use. Every mutating request names the CLI's pinned bank in `X-Cicada-Bank`, so a bank switch
  between the bootstrap and the request is refused by the backend (`bank_mismatch`, exit 3) before anything is
  written. With the backend down the command refuses (`backend_down`, exit 6) and changes nothing.

**Person-only commands** (`Row.person`) change memory or spend as the person — the backend records them as
`Cicada-Author: user`, starts a run on the person's engine, or downloads a model on their command. From a shell
that names an agent's session (`session_identity.cli_identity`), they refuse (`person_only`): an agent's write
carries the agent's provenance, never the person's.

Pure at import: no service is imported until a handler runs, after the bootstrap.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlencode

from api.cli_types import Refusal, Result, UsageError

HTTP_TIMEOUT_S = 30.0
JOB_POLL_S = 1.0
JOB_WAIT_MAX_S = 3600.0
#: A write to the backend needs `/healthz` to confirm this command's memory root. The bootstrap asks for 1 s; a
#: backend that did not answer in time is asked once more, this long, before the write is refused.
CONFIRM_TIMEOUT_S = 5.0
#: Shell variables only a harness sets in the commands it runs: an agent's shell even when it names no session.
AGENT_SHELL_ENV = (("CODEX_THREAD_ID", "codex"), ("CODEX_SESSION_ID", "codex"), ("CODEX_SANDBOX", "codex"))


# --- the backend, as one more client of its API -----------------------------------------------------

def backend_headers(environ=None) -> dict[str, str]:
    """The bearer token the app sends: `CICADA_API_TOKEN`, else `$CICADA_HOME/api_token`."""
    from api.services import runtime_layout

    environ = os.environ if environ is None else environ
    if runtime_layout.is_client(environ):
        # G181 phase 2: a client of a server elsewhere signs with this device's own token, never a master token.
        token = runtime_layout.client_token(environ)
        return {"Authorization": f"Bearer {token}"} if token else {}
    token = (environ.get("CICADA_API_TOKEN") or "").strip()
    if not token:
        try:
            token = (runtime_layout.cicada_home(environ) / "api_token").read_text(encoding="utf-8").strip()
        except OSError:
            token = ""
    return {"Authorization": f"Bearer {token}"} if token else {}


def _opener():
    from api.services import runtime_layout

    # Loopback never goes through a proxy, and no redirect is followed with the token (a server elsewhere, G181).
    return runtime_layout.opener()


def probe_backend(url: str, root, timeout: float, *, bank_id: str | None = None) -> dict:
    """Ask a running backend which memory it serves. ``backend_down`` only on a refused
    connection; a timeout, an error answer or no root in it is ``unverified``, never "no backend".

    G181 phase 2 (ruling 21a, amended 2026-10-16): the memory is compared by IDENTITY — this command's pinned bank's
    id (``banks.yaml``) among the ids of the banks the backend serves (``/healthz`` ``bankIds``) — and by the root's
    path only when either side has no id yet (a backend from before the ids, a registry the backend has not given ids
    to). A path means nothing across machines or containers; an id does."""
    import socket
    import urllib.error
    import urllib.request

    # Owner decision 3 (2026-10-16): `/healthz` names the memory root only to a caller holding the token, so the
    # path fallback below asks with this machine's own token (the ids are open either way).
    request = urllib.request.Request(f"{url}/healthz", headers={**backend_headers(), "Accept": "application/json"})
    try:
        with _opener().open(request, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError:
        return {"state": "unverified"}
    except urllib.error.URLError as exc:
        return {"state": "backend_down" if isinstance(exc.reason, ConnectionRefusedError) else "unverified"}
    except ConnectionRefusedError:
        return {"state": "backend_down"}
    except (TimeoutError, socket.timeout, OSError, ValueError):
        return {"state": "unverified"}
    ids = body.get("bankIds") if isinstance(body, dict) else None
    ids = [i for i in ids if isinstance(i, str) and i] if isinstance(ids, list) else []
    if bank_id and ids:
        out = {"state": "confirmed" if bank_id in ids else "mismatch", "compared": "id"}
        if isinstance(body.get("version"), str):
            out["version"] = body["version"]
        return out
    reported = body.get("memoryRoot") if isinstance(body, dict) else None
    if not isinstance(reported, str) or not reported.strip():
        return {"state": "unverified"}
    same = os.path.realpath(os.path.expanduser(reported)) == os.path.realpath(root)
    out = {"state": "confirmed" if same else "mismatch"}
    if isinstance(body.get("version"), str):
        out["version"] = body["version"]
    return out


CLIENT_DOWN_TEXT = ("The Cicada server this shell uses (CICADA_API_BASE) is not reachable, and the memory is there. "
                    "Nothing was read or changed; try again when it is reachable.")
CLIENT_UNAUTHORIZED_TEXT = ("The Cicada server did not accept this device's token (CICADA_API_TOKEN or "
                            "~/.cicada/device_token); it may have been revoked. The person issues a new one on the "
                            "server with `cicada device add`. Nothing was read or changed.")
CLIENT_NO_TOKEN_TEXT = ("This device has no Cicada token (CICADA_API_TOKEN or ~/.cicada/device_token). The person "
                        "issues one on the server with `cicada device add <name>`. Nothing was read or changed.")
CLIENT_MASTER_ONLY_TEXT = ("Only the server itself can do this; a device's token never can. Run it in a terminal on the "
                           "server. Nothing was changed.")
CLIENT_UNVERIFIED_TEXT = ("The Cicada server did not say which memory it serves, so this command will not read or "
                          "change anything through it. Nothing was changed; try again.")


def client_probe(base: str, timeout: float = 2.0):
    """G181 phase 2: ``(probe, pin)`` for a client shell. The server's active bank — its name and its id — from ONE
    authenticated read (``GET /banks``), cross-checked with ``/healthz``'s ``bankId``; ``pin`` is None unless the
    server answered both and they agree. States: ``confirmed``, ``backend_down`` (no connection at all),
    ``unauthorized`` (the token was refused), ``no_token`` (this device holds none, so nothing was asked),
    ``unverified`` (anything else)."""
    import socket
    import urllib.error
    import urllib.request

    from api.cli_types import RemotePin

    def get(path: str, headers: dict):
        req = urllib.request.Request(base + path, headers={**headers, "Accept": "application/json"}, method="GET")
        with _opener().open(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    from api.services import runtime_layout

    try:
        health = get("/healthz", {})
    except urllib.error.HTTPError as exc:
        redirected = runtime_layout.redirect_text(exc)       # a 3xx is never followed with the token: say so
        return ({"state": "redirected", "text": redirected} if redirected else {"state": "unverified"}), None
    except urllib.error.URLError as exc:
        down = isinstance(exc.reason, (ConnectionRefusedError, socket.gaierror, OSError)) and not isinstance(
            exc.reason, (TimeoutError, socket.timeout))
        return {"state": "backend_down" if down else "unverified"}, None
    except (ConnectionRefusedError, socket.gaierror):
        return {"state": "backend_down"}, None
    except (TimeoutError, socket.timeout, OSError, ValueError):
        return {"state": "unverified"}, None
    out = {"state": "unverified"}
    if isinstance(health, dict) and isinstance(health.get("version"), str):
        out["version"] = health["version"]
    if not runtime_layout.client_token(os.environ):
        return {**out, "state": "no_token"}, None       # nothing to send: never blame a revocation
    try:
        listing = get("/banks", backend_headers())
    except urllib.error.HTTPError as exc:
        redirected = runtime_layout.redirect_text(exc)
        if redirected:
            return {**out, "state": "redirected", "text": redirected}, None
        return {**out, "state": "unauthorized" if exc.code in (401, 403) else "unverified"}, None
    except Exception:  # noqa: BLE001
        return out, None
    active = listing.get("active") if isinstance(listing, dict) else None
    record = next((b for b in listing.get("banks") or [] if isinstance(b, dict) and b.get("name") == active), None) \
        if isinstance(listing, dict) else None
    bank_id = record.get("id") if isinstance(record, dict) else None
    if not isinstance(active, str) or not active or not isinstance(bank_id, str) or not bank_id \
            or (isinstance(health, dict) and health.get("bankId") not in (None, bank_id)):
        return out, None
    return {**out, "state": "confirmed", "compared": "id"}, RemotePin(name=active, id=bank_id)


MISMATCH_TEXT = ("The app's backend uses a different memory folder than this command. Nothing was changed; "
                 "check `cicada status`.")
UNVERIFIED_TEXT = ("The app's backend did not confirm which memory folder it serves, so this command will not "
                   "change anything through it: a write could land in another memory. Nothing was changed; "
                   "check `cicada status`, or try again.")


def _confirm_root(boot) -> None:
    """A write goes only to a backend that confirmed it serves this command's memory root (ruling 21's split-brain
    guard: the backend checks the bank's NAME, and a fresh root's bank is `default` too). An unverified probe is asked
    once more with a longer timeout; anything but `confirmed` then refuses, its warnings kept."""
    if boot.probe.get("state") == "unverified":
        if getattr(boot, "client", False):
            boot.probe, pin = client_probe(boot.backend_url, CONFIRM_TIMEOUT_S)
            if pin is not None and boot.pin is not None and pin.id != boot.pin.id:
                boot.probe = {"state": "mismatch"}
        else:
            boot.probe = probe_backend(boot.backend_url, boot.root, CONFIRM_TIMEOUT_S,
                                       bank_id=getattr(boot.pin, "id", None))
    state = boot.probe.get("state")
    if state == "confirmed":
        return
    if state == "backend_down":
        raise Refusal("backend_down", down_text())
    if state == "mismatch":
        raise Refusal("root_mismatch", MISMATCH_TEXT, _warn(boot))
    raise Refusal("root_unverified", UNVERIFIED_TEXT, _warn(boot) or ["root_unverified"])


DOWN_TEXT = ("The app's backend is not running, and this command acts on it. Open Cicada (or start its backend) "
             "and try again. Nothing was changed.")
#: A Linux machine has no app to open (G181): its backend is the systemd user unit `install.sh` installs.
SERVER_DOWN_TEXT = ("Cicada's backend is not running on this machine, and this command acts on it. Start it with "
                    "`systemctl --user start cicada-backend.service` (why it stopped: `journalctl --user -u "
                    "cicada-backend.service`) and try again. Nothing was changed.")


def down_text(platform: str | None = None) -> str:
    """What a command that needs this machine's own backend says when it does not answer."""
    import sys

    return SERVER_DOWN_TEXT if (platform or sys.platform).startswith("linux") else DOWN_TEXT


def _multipart(field: str, filename: str, data: bytes) -> tuple[bytes, str]:
    boundary = f"cicada-{uuid.uuid4().hex}"
    safe_name = filename.replace('"', "_").replace("\r", "_").replace("\n", "_")
    head = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; filename=\"{safe_name}\"\r\n"
            "Content-Type: application/octet-stream\r\n\r\n").encode("utf-8")
    return head + data + f"\r\n--{boundary}--\r\n".encode("utf-8"), f"multipart/form-data; boundary={boundary}"


def call(boot, method: str, path: str, *, body=None, query: dict | None = None,
         upload: tuple[str, str, bytes] | None = None, bank_header: bool = True,
         timeout: float = HTTP_TIMEOUT_S):
    """One request to the running backend, as the app makes it. Returns the decoded JSON body.

    Refuses before sending when the bootstrap's `/healthz` cross-check found no backend (`backend_down`) or one
    that serves another memory folder (`root_mismatch`). A mutating request names the CLI's pinned bank
    (`X-Cicada-Bank`) unless ``bank_header`` is False (bank CRUD names its own bank). The backend's refusals
    become typed codes: 409 `sleep_writing` / `bank_mismatch` by their code, any other 409 `refused`, 404
    `not_found`, 400/422 a usage error carrying the backend's sentence, 401/403 `unauthorized`."""
    import socket
    import urllib.error
    import urllib.request

    state = boot.probe.get("state")
    if state == "backend_down":
        raise Refusal("backend_down", down_text())
    if state == "mismatch":
        raise Refusal("root_mismatch", MISMATCH_TEXT, _warn(boot))
    if method != "GET":
        _confirm_root(boot)              # every write, bank CRUD included: never to an unconfirmed root
    url = boot.backend_url + path + (("?" + urlencode(query, doseq=True)) if query else "")
    headers = {**backend_headers(), "Accept": "application/json"}
    data = None
    if upload is not None:
        data, headers["Content-Type"] = _multipart(*upload)
    elif body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if method != "GET" and bank_header:
        headers["X-Cicada-Bank"] = quote(boot.pin.name, safe="")
        if getattr(boot, "client", False) and getattr(boot.pin, "id", None):
            # G181 phase 2: a client names the bank's identity too — a name can repeat across memories, an id cannot.
            headers["X-Cicada-Bank-Id"] = boot.pin.id
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with _opener().open(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        _raise_for(exc, _warn(boot))
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, ConnectionRefusedError):
            raise Refusal("backend_down", down_text()) from None
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            raise Refusal("backend_timeout", "The app's backend did not answer in time; it may still be working "
                                             "on it. Check with `cicada sleep status` or the app.") from None
        raise Refusal("backend_down", down_text()) from None
    except ConnectionRefusedError:
        raise Refusal("backend_down", down_text()) from None
    except (TimeoutError, socket.timeout):
        raise Refusal("backend_timeout", "The app's backend did not answer in time; it may still be working on "
                                         "it. Check with `cicada sleep status` or the app.") from None
    if getattr(boot, "client", False):
        flush_spool()          # D3 (G202): the server answered, so what the hooks left waiting for it goes now
    if not raw:
        return {}
    try:
        return json.loads(raw.decode("utf-8"))
    except ValueError:
        raise Refusal("backend_error", "The app's backend answered something that is not JSON.") from None


def flush_spool(environ=None):
    """D3 (G202): send the captures this machine's hooks left waiting for the server it points at — only those (D1) —
    inside a short budget. ``(sent, left)``, or None when nothing waited for it. Never raises."""
    try:
        from api.hooks import hook_client
        from api.services import runtime_layout

        environ = os.environ if environ is None else environ
        return hook_client.flush_waiting(runtime_layout.cicada_home(environ), environ, surface="cli")
    except Exception:  # noqa: BLE001 - a flush is never worth a failed command
        return None


def _client() -> bool:
    from api.services import runtime_layout

    return runtime_layout.is_client(os.environ)


def door(boot, tool: str, arguments: dict, options: dict | None = None, *, project_dir: str | None = None):
    """G181 phase 2: a tool mirror run on the server (``POST /tools/call``, the command-line surface), answered as the
    local body's ``Reply`` — the same text, refusal code and data. The request names the pinned bank and its id, so a
    server whose active bank moved refuses it before anything runs."""
    from api.services import mcp_tools, session_identity

    ident = session_identity.cli_identity()
    body = {"tool": tool, "arguments": arguments, "surface": "cli", "options": options or {},
            "caller": {"session_id": ident.session_id or "", "harness": ident.harness or "unknown",
                       "project_dir": project_dir or ident.project_dir or boot.caller_cwd}}
    answer = call(boot, "POST", "/tools/call", body=body, timeout=180)
    if answer.get("error"):
        raise Refusal("backend_error", "The server could not run this: " + str(answer["error"])[:300])
    data = answer.get("data") if isinstance(answer.get("data"), dict) else None
    return mcp_tools.Reply(str(answer.get("text") or ""), code=answer.get("code"), data=data)


def _demo_refusal() -> str:
    from api.services import demo_guard

    return demo_guard.REFUSAL


def _raise_for(exc, warnings: list[str] | None = None) -> None:
    try:
        payload = json.loads(exc.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 - an unreadable body falls back to the status
        payload = {}
    detail = payload.get("detail") if isinstance(payload, dict) else None
    code = payload.get("code") if isinstance(payload, dict) else None
    if not isinstance(detail, str):
        detail = None
    status = exc.code
    w = list(warnings or [])
    from api.services import runtime_layout

    redirected = runtime_layout.redirect_text(exc)
    if redirected:
        raise Refusal("backend_error", redirected, w)    # never followed with the token (G181): said plainly
    if status == 409 and code == "bank_mismatch":
        raise Refusal("bank_mismatch", "The active memory changed before this was sent. Nothing was changed.", w)
    if status == 403 and _client():
        raise Refusal("unauthorized", CLIENT_MASTER_ONLY_TEXT, w)     # the token is fine; the path is the server's
    if status in (401, 403) and _client():
        raise Refusal("unauthorized", CLIENT_UNAUTHORIZED_TEXT, w)
    if status == 409 and code == "sleep_writing":
        raise Refusal("sleep_writing", (detail or "Sleep is updating your memory.") + " Nothing was changed; "
                                                                                       "try again in a moment.", w)
    if status == 409 and detail == _demo_refusal():
        # `demo_guard`'s capture refusal (every capture and sources write in a demo bank): the CLI's demo exit.
        raise Refusal("demo_bank", detail, w)
    if status == 409:
        raise Refusal("refused", detail or "The app's backend refused this. Nothing was changed.", w)
    if status == 404:
        raise Refusal("not_found", detail or "Not found.", w)
    if status == 413:
        raise Refusal("refused", detail or "That file is too large for Cicada. Nothing was changed.", w)
    if status in (400, 422):
        raise UsageError(detail or "the app's backend did not accept these values")
    if status in (401, 403):
        raise Refusal("unauthorized", "The app's backend did not accept this command's token "
                                      "(CICADA_API_TOKEN or ~/.cicada/api_token).", w)
    raise Refusal("backend_error", f"The app's backend could not do this (HTTP {status}).", w)


# --- the person-only rule ----------------------------------------------------------------------------

def agent_shell(environ=None) -> str | None:
    """The harness whose shell this is, or None for the person's own terminal: a session or harness the identity
    parse names (`session_identity.cli_identity`), else a variable only a harness sets in the commands it runs
    (Codex's `CODEX_THREAD_ID` / `CODEX_SESSION_ID` / `CODEX_SANDBOX`, which its shells carry without naming a
    session to Cicada)."""
    from api.services import session_identity

    environ = os.environ if environ is None else environ
    ident = session_identity.cli_identity(environ)
    if ident.session_id or ident.harness:
        return ident.harness or "unnamed harness"
    for key, harness in AGENT_SHELL_ENV:
        if (environ.get(key) or "").strip():
            return harness
    return None


def require_person(what: str) -> None:
    """Refuse when the shell belongs to an agent: the backend would record this as the person."""
    harness = agent_shell()
    if harness is not None:
        raise Refusal("person_only", f"{what} acts as the person, and this shell belongs to an agent's session "
                                     f"({harness}). The person runs it in their own terminal or the app. "
                                     "Nothing was changed.")


def _warn(boot) -> list[str]:
    return {"mismatch": ["root_mismatch"], "unverified": ["root_unverified"]}.get(boot.probe.get("state"), [])


def _run(coro):
    return asyncio.run(coro)


def _dump(model) -> dict:
    return model.model_dump(by_alias=True, mode="json") if hasattr(model, "model_dump") else model


def _page_exists(boot, entity_id: str) -> None:
    if "/" in entity_id or entity_id.startswith(".") or \
            not (Path(boot.pin.path) / "entities" / f"{entity_id}.md").is_file():
        raise Refusal("not_found", f"No page '{entity_id}' in this memory.")


# --- pages and the graph (bank) -------------------------------------------------------------------------

def _nodes(boot, types=None, statuses=None):
    from api.services.graph_builder import build_graph

    graph = build_graph(Path(boot.pin.path), types=set(types) if types else None,
                        statuses=set(statuses) if statuses else None, include_hubs=False)
    return [n for n in graph.nodes if not getattr(n, "is_facet", False) and not getattr(n, "is_hub", False)], graph


def cmd_page_list(boot, args) -> Result:
    nodes, _graph = _nodes(boot, [args.type] if args.type else None, [args.status] if args.status else None)
    pages = sorted(({"id": n.id, "name": n.name, "type": n.type, "status": getattr(n.status, "value", n.status),
                     "confidence": n.confidence} for n in nodes), key=lambda p: (p["type"], p["name"].lower()))
    lines = [f"{p['id']}  ({p['type']}, {p['status']})  {p['name']}" for p in pages]
    text = "\n".join(lines) if lines else "No pages match."
    return Result(text=text, data={"pages": pages, "total": len(pages)}, warnings=_warn(boot))


def cmd_graph(boot, args) -> Result:
    nodes, graph = _nodes(boot)
    by_type: dict[str, int] = {}
    by_status: dict[str, int] = {}
    for n in nodes:
        by_type[n.type] = by_type.get(n.type, 0) + 1
        status = getattr(n.status, "value", n.status)
        by_status[status] = by_status.get(status, 0) + 1
    page_ids = {n.id for n in nodes}
    links = sum(1 for link in graph.links if link.source in page_ids and link.target in page_ids)
    data = {"pages": len(nodes), "links": links, "by_type": dict(sorted(by_type.items())),
            "by_status": dict(sorted(by_status.items()))}
    text = "\n".join([f"{len(nodes)} page(s), {links} link(s) between them",
                      "By type: " + (", ".join(f"{k} {v}" for k, v in data["by_type"].items()) or "none"),
                      "By status: " + (", ".join(f"{k} {v}" for k, v in data["by_status"].items()) or "none")])
    return Result(text=text, data=data, warnings=_warn(boot))


def _coverage(boot, args, kind: str) -> Result:
    from api.services import coverage_report

    build = coverage_report.pictures if kind == "pictures" else coverage_report.sources
    report = build(Path(boot.pin.path), include_archived=bool(args.archived), ids=bool(args.ids))
    return Result(text=coverage_report.text(kind, report), data=report, warnings=_warn(boot))


def cmd_coverage_pictures(boot, args) -> Result:
    return _coverage(boot, args, "pictures")


def cmd_coverage_sources(boot, args) -> Result:
    return _coverage(boot, args, "sources")


def cmd_find(boot, args) -> Result:
    """The app's find (`GET /search`'s body, in process): every kind unless --kind narrows it."""
    from api.services import search_service

    kinds = (search_service.parse_kinds(",".join(args.kind), None) if args.kind else list(search_service.KINDS))
    resp = search_service.search(Path(boot.pin.path), args.query, kinds=kinds, mode="hybrid",
                                 per_kind=min(args.limit or 8, search_service.MAX_PER_KIND))
    data = _dump(resp)
    lines = [f"[{hit.get('kind')}] {hit.get('id')}  {hit.get('displayName') or hit.get('name') or ''}".rstrip()
             for hit in data.get("results", []) or []]
    warnings = _warn(boot)
    if data.get("mode") == "lexical":
        warnings.append("degraded:vector")
    return Result(text="\n".join(lines) or "Nothing matches.", data=data, warnings=warnings)


def cmd_page_history(boot, args) -> Result:
    from api.services import git_service

    _page_exists(boot, args.entity_id)
    rows = _run(git_service.get_entity_history(args.entity_id, Path(boot.pin.path)))
    entries = [_dump(r) for r in rows][: args.limit or None]
    lines = [f"{e.get('date', '')[:16]}  {e.get('commitHash', '')[:10]}  {e.get('author', '')}  "
             f"{e.get('changeType', '')}: {e.get('description', '')}".rstrip(" :") for e in entries]
    return Result(text="\n".join(lines) or "No history (this memory is not under git, or the page is new).",
                  data={"entity_id": args.entity_id, "history": entries}, warnings=_warn(boot))


def cmd_page_decay(boot, args) -> Result:
    require_person("Setting how a page fades")
    page = call(boot, "PUT", f"/entities/{quote(args.entity_id, safe='')}/decay",
                body={"decayClass": args.decay_class})
    return Result(text=f"{args.entity_id} now fades as {page.get('decayClass', args.decay_class)}.",
                  data={"entity_id": args.entity_id, "decay_class": page.get("decayClass", args.decay_class)},
                  warnings=_warn(boot))


# --- the inbox --------------------------------------------------------------------------------------------

def cmd_inbox_all(boot, args) -> Result:
    from api.services import inbox_service

    items = inbox_service.load_inbox(Path(boot.pin.path))
    wanted = set(args.kind or [])
    rows = []
    for item in items:
        kind = getattr(item.kind, "value", item.kind)
        if wanted and kind not in wanted:
            continue
        rows.append({"id": item.id, "kind": kind, "status": item.status, "entity_id": item.entity_id or None,
                     "title": item.title, "question": item.question,
                     "options": [{"key": o.key, "label": o.label} for o in (item.options or [])
                                 if getattr(o, "key", None)]})
    lines = []
    for r in rows:
        lines.append(f"{r['id']}  [{r['kind']}]  {r['question'] or r['title']}")
        lines += [f"    {o['key']}: {o['label']}" for o in r["options"]]
    return Result(text="\n".join(lines) or "The inbox is empty.", data={"items": rows, "total": len(rows)},
                  warnings=_warn(boot))


def cmd_inbox_answer(boot, args) -> Result:
    picked = [bool(args.option or args.answer), bool(args.defer), bool(args.reject)]
    if sum(picked) != 1:
        raise UsageError("give one of: --option KEY / --answer TEXT, --defer, or --reject")
    require_person("Answering an inbox question")
    if args.reject:
        body = {"action": "reject"}
    elif args.defer:
        body = {"action": "defer", **({"remindDays": args.days} if args.days is not None else {})}
    else:
        body = {"action": "resolve", **({"optionKey": args.option} if args.option else {}),
                **({"answer": args.answer} if args.answer else {})}
    result = call(boot, "POST", f"/inbox/{quote(args.item_id, safe='')}/resolve", body=body)
    status = result.get("status", "done")
    text = (f"Deferred {args.item_id} until {result.get('remindAfter', 'later')}." if status == "deferred"
            else f"Inbox item {args.item_id}: {status}.")
    return Result(text=text, data=result, warnings=_warn(boot))


# --- Sleep ------------------------------------------------------------------------------------------------

_STAGE_SAID = re.compile(r"^Stage (\d+)/(\d+):\s*(.*)$", re.S)


def _stage_line(st: dict) -> str:
    """The running stage, said once. ``stage`` counts the stages FINISHED (the app's fill), while ``progress`` names
    the one running ("Stage 5/5: Writing changes…"); printing both read "stage 4 of 5: Stage 5/5: …" (headless QA)."""
    total = st.get("totalStages", 5)
    progress = str(st.get("progress") or "").strip()
    said = _STAGE_SAID.match(progress)
    if said:
        rest = said.group(3).strip()
        return f"stage {said.group(1)} of {said.group(2)}" + (f": {rest}" if rest else "")
    try:
        running = min(int(st.get("stage", 0) or 0) + 1, int(total))
    except (TypeError, ValueError):
        running = 1
    return f"stage {running} of {total}" + (f": {progress}" if progress else "")


def cmd_sleep_status(boot, args) -> Result:
    st = call(boot, "GET", "/sleep/status")
    status = st.get("status", "unknown")
    lines = [f"Sleep: {status}" + (" (writing to your pages)" if st.get("writing") else "")]
    if status == "running":
        lines.append("  " + _stage_line(st))
    paused = st.get("paused")
    if isinstance(paused, dict) and paused:
        lines.append(f"  paused: {paused.get('reason') or paused.get('message') or 'yes'}")
    debt = st.get("debt") if isinstance(st.get("debt"), dict) else {}
    if "unprocessedCount" in debt:
        lines.append(f"  waiting: {debt['unprocessedCount']} conversation(s)")
    if st.get("error"):
        lines.append(f"  last error: {st['error']}")
    return Result(text="\n".join(lines), data=st, warnings=_warn(boot))


def cmd_sleep_start(boot, args) -> Result:
    require_person("Starting Sleep")
    result = call(boot, "POST", "/sleep/trigger", body={"continue": True} if args.continue_run else None)
    return Result(text=result.get("message") or result.get("status", ""), data=result, warnings=_warn(boot))


def cmd_sleep_stop(boot, args) -> Result:
    result = call(boot, "POST", "/sleep/cancel")
    return Result(text=result.get("message") or result.get("status", ""), data=result, warnings=_warn(boot))


def cmd_sleep_end(boot, args) -> Result:
    result = call(boot, "POST", "/sleep/run/end")
    return Result(text=result.get("message") or result.get("status", ""), data=result, warnings=_warn(boot))


def _hhmm(raw: str) -> tuple[int, int]:
    try:
        hour, minute = raw.split(":")
        h, m = int(hour), int(minute)
    except ValueError:
        raise UsageError("--at takes HH:MM (24-hour)") from None
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise UsageError("--at takes HH:MM (24-hour)")
    return h, m


def _schedule_text(cfg: dict) -> str:
    mode = cfg.get("mode", "manual")
    if mode == "daily":
        return f"Sleep runs on its own every day at {cfg.get('hour', 0):02d}:{cfg.get('minute', 0):02d}."
    if mode == "interval":
        return f"Sleep runs on its own every {cfg.get('intervalHours')} hour(s)."
    if mode == "manual":
        return "Sleep runs only when started."
    return f"Sleep schedule: {mode}."


USE_PLAN_ON_TEXT = ("Scheduled runs may now use your plan on this machine. Nightly runs count against your "
                    "plan's limits, like the runs you start; a run that reaches a limit pauses, and the next scheduled "
                    "run picks up once the limit has reset.")
USE_PLAN_OFF_TEXT = "Scheduled runs no longer use your plan; the runs you start still may."


def _schedule_warning(cfg: dict) -> str | None:
    """The schedule's no-engine warning (owner decision 2, 2026-10-16), with the command-line fix."""
    from api.services import engine_readiness

    sentence, code = cfg.get("warning"), cfg.get("warningCode")
    if not isinstance(sentence, str) or not sentence:
        return None
    return engine_readiness.Problem(code or "", sentence).with_cli_fix()


def _with_schedule_warning(text: str, cfg: dict) -> str:
    warning = _schedule_warning(cfg)
    return f"{text}\nWarning: {warning}" if warning else text


def cmd_sleep_schedule(boot, args) -> Result:
    cfg = call(boot, "GET", "/sleep/schedule")
    use_plan = _on_off(getattr(args, "use_plan", None))
    if args.mode is None and args.at is None and args.every is None and use_plan is None:
        return Result(text=_with_schedule_warning(_schedule_text(cfg), cfg), data=cfg, warnings=_warn(boot))
    require_person("Changing when Sleep runs")
    lines: list[str] = []
    data = dict(cfg)
    if use_plan is not None:
        # Ruling 4b (owner, 2026-10-16): the machine's switch; said once, here, that nightly runs then count.
        opts = call(boot, "PUT", "/sleep/run-options", body={"scheduledUsePlan": use_plan})
        lines.append(USE_PLAN_ON_TEXT if opts.get("scheduledUsePlan") else USE_PLAN_OFF_TEXT)
        data["scheduledUsePlan"] = bool(opts.get("scheduledUsePlan"))
        if args.mode is None and args.at is None and args.every is None:
            cfg = call(boot, "GET", "/sleep/schedule")   # the warning reads the switch just written
            data.update(cfg)
            return Result(text=_with_schedule_warning("\n".join([*lines, _schedule_text(cfg)]), cfg), data=data,
                          warnings=_warn(boot))
    new = {k: v for k, v in cfg.items() if k in ("mode", "hour", "minute", "intervalHours", "afterImport")}
    if args.at is not None:
        new["hour"], new["minute"] = _hhmm(args.at)
        new.setdefault("mode", "daily")
        if args.mode is None and new.get("mode") != "daily":
            new["mode"] = "daily"
    if args.every is not None:
        new["intervalHours"] = args.every
        if args.mode is None:
            new["mode"] = "interval"
    if args.mode is not None:
        new["mode"] = args.mode
    new.pop("enabled", None)
    saved = call(boot, "PUT", "/sleep/schedule", body=new)
    data.update(saved)
    return Result(text=_with_schedule_warning("\n".join([*lines, _schedule_text(saved)]), saved), data=data,
                  warnings=_warn(boot))


def cmd_sleep_engine(boot, args) -> Result:
    if args.mode is None and args.model is None:
        eng = call(boot, "GET", "/sleep/engine")
    else:
        require_person("Choosing Sleep's engine")
        current = call(boot, "GET", "/sleep/engine")
        body = {"mode": args.mode or current.get("mode")}
        if args.model is not None:
            body["model"] = args.model
        eng = call(boot, "PUT", "/sleep/engine", body=body)
    text = f"Sleep reads with: {eng.get('mode', '?')} · {eng.get('model', '?')} (set by {eng.get('source', '?')})"
    return Result(text=text, data=eng, warnings=_warn(boot))


def _on_off(raw: str | None) -> bool | None:
    if raw is None:
        return None
    word = raw.strip().lower()
    if word in ("on", "yes", "true"):
        return True
    if word in ("off", "no", "false"):
        return False
    raise UsageError("expected on or off")


def cmd_sleep_options(boot, args) -> Result:
    changes: dict = {}
    if args.batch_size is not None:
        changes["batchSize"] = args.batch_size
    if args.continue_after_reset is not None:
        changes["continueAfterReset"] = _on_off(args.continue_after_reset)
    if args.reserve is not None:
        changes["reservePct"] = None if args.reserve.strip().lower() == "off" else _int(args.reserve, "--reserve")
    if changes:
        require_person("Changing how Sleep reads")
        opts = call(boot, "PUT", "/sleep/run-options", body=changes)
    else:
        opts = call(boot, "GET", "/sleep/run-options")
    reserve = opts.get("reservePct")
    text = (f"Batch size {opts.get('batchSize')}; continue after a plan reset: "
            f"{'on' if opts.get('continueAfterReset') else 'off'}; reserve: "
            f"{'off' if reserve is None else str(reserve) + '%'}")
    return Result(text=text, data=opts, warnings=_warn(boot))


def _int(raw: str, flag: str) -> int:
    try:
        return int(raw)
    except ValueError:
        raise UsageError(f"{flag} takes a whole number or off") from None


def cmd_sleep_history(boot, args) -> Result:
    from api.services import git_service

    limit = args.limit or 15
    if not 1 <= limit <= 100:
        raise UsageError("--limit takes 1 to 100")
    rows = [_dump(r) for r in _run(git_service.get_sleep_history(Path(boot.pin.path), limit=limit))]
    lines = [f"{r.get('date', '')[:16]}  {r.get('kind', 'sleep')}  {r.get('entitiesCreated', 0)} new, "
             f"{r.get('entitiesUpdated', 0)} updated, {r.get('episodes', 0)} conversation(s)" for r in rows]
    return Result(text="\n".join(lines) or "Sleep has not run in this memory yet.", data={"runs": rows},
                  warnings=_warn(boot))


# --- the search index and model ------------------------------------------------------------------------------

def _model_text(model: dict) -> list[str]:
    lines = [f"Search model: {model.get('model', '?')}"]
    reindex = model.get("reindex") or {}
    if reindex.get("state") not in (None, "idle", "done"):
        lines.append(f"  re-embedding: {reindex.get('state')}"
                     + (f" ({reindex.get('done')}/{reindex.get('total')})" if reindex.get("total") else ""))
    install = model.get("install") or {}
    if install.get("state") not in (None, "idle", "done"):
        lines.append(f"  installing: {install.get('state')}")
    return lines


def cmd_index_status(boot, args) -> Result:
    index = call(boot, "GET", "/maintenance/search-index")
    model = call(boot, "GET", "/embeddings")
    lines = [f"Word index: {index.get('state', '?')}" + (f", built {index['builtAt']}" if index.get("builtAt") else "")]
    lines += _model_text(model)
    choices = [m.get("id") for m in model.get("models", []) or [] if isinstance(m, dict)]
    if choices:
        lines.append("  models: " + ", ".join(c for c in choices if c))
    return Result(text="\n".join(lines), data={"index": index, "model": model}, warnings=_warn(boot))


def cmd_index_rebuild(boot, args) -> Result:
    index = call(boot, "POST", "/maintenance/search-index/rebuild", timeout=600)
    return Result(text=f"Word index rebuilt ({index.get('documents', '?')} documents).", data=index,
                  warnings=_warn(boot))


def cmd_maintenance_move_watched_rows(boot, args) -> Result:
    """The dry run by default; ``--apply`` moves the rows, from the person's own terminal only."""
    if getattr(args, "apply", False):
        require_person("Moving the watched days' rows")
        done = call(boot, "POST", "/maintenance/watched-rows", timeout=600)
        return Result(text=f"Moved {done.get('moved', 0)} watched day(s)' rows into sources/watched/ in one commit.",
                      data=done, warnings=_warn(boot))
    plan = call(boot, "GET", "/maintenance/watched-rows")
    if plan.get("applied") and not plan.get("days"):
        return Result(text="Nothing to move: every watched day keeps its rows in sources/watched/.", data=plan,
                      warnings=_warn(boot))
    lines = [f"{plan.get('days', 0)} watched day(s) keep {plan.get('rows', 0)} row(s) in their episode's frontmatter "
             f"({plan.get('rows_files_kept', 0)} already have a rows file, which is kept).",
             "Moving them writes each day's rows to sources/watched/<platform>/<day>.json and drops the frontmatter "
             "copy, in one commit; nothing is re-queued for Sleep."]
    if plan.get("sample"):
        lines.append("For example: " + ", ".join(plan["sample"]))
    lines.append("Run again with --apply to move them.")
    return Result(text="\n".join(lines), data=plan, warnings=_warn(boot))


def cmd_index_use(boot, args) -> Result:
    require_person("Switching the search model")
    model = None if args.model == "default" else args.model
    status = call(boot, "POST", "/embeddings/choice", body={"model": model})
    return Result(text="\n".join(_model_text(status)), data=status, warnings=_warn(boot))


def cmd_index_install(boot, args) -> Result:
    require_person("Downloading a search model")
    model = args.model
    if not model:
        current = call(boot, "GET", "/embeddings")
        model = current.get("recommended") or current.get("nextModel")
        if not isinstance(model, str) or not model.strip():
            raise Refusal("refused", "Cicada has no search model to recommend downloading on this Mac. Name one with "
                                     "--model (`cicada index status` lists them). Nothing was downloaded.", _warn(boot))
    body = {"model": model}
    status = call(boot, "POST", "/embeddings/install", body=body)
    return Result(text="Download started.\n" + "\n".join(_model_text(status)), data=status, warnings=_warn(boot))


# --- sources and imports -----------------------------------------------------------------------------------

def cmd_feed_list(boot, args) -> Result:
    from api.services import feed_registry

    feeds = feed_registry.list_feeds(Path(boot.pin.path))
    lines = [f"{f.get('url')}" + (f"  [{', '.join(f.get('tags') or [])}]" if f.get("tags") else "") for f in feeds]
    return Result(text="\n".join(lines) or "No feeds.", data={"feeds": feeds, "total": len(feeds)},
                  warnings=_warn(boot))


def cmd_feed_add(boot, args) -> Result:
    record = call(boot, "POST", "/sources/feeds", body={"url": args.url, "tags": args.tag or None})
    return Result(text=f"Subscribed to {record.get('url', args.url)}.", data=record, warnings=_warn(boot))


def cmd_projects_new(boot, args) -> Result:
    """Ruling 45: the person starts a project from their own shell — theirs, listed (`via: cli`). Refused from an
    agent's shell (ruling 21a): an agent asks with `cicada_create_project`, where the trust list decides."""
    require_person("Starting a project as yours")
    record = call(boot, "POST", "/projects", body={"name": args.project, "description": args.description or "",
                                                   "via": "cli"})
    return Result(text=f"Started {args.project} ({record.get('id')}) in your projects.", data=record,
                  warnings=_warn(boot))


def cmd_feed_remove(boot, args) -> Result:
    result = call(boot, "DELETE", "/sources/feeds", body={"url": args.url})
    return Result(text=f"Unsubscribed from {args.url}.", data=result, warnings=_warn(boot))


def cmd_feed_poll(boot, args) -> Result:
    require_person("Fetching every feed now")
    result = call(boot, "POST", "/sources/poll-feeds", timeout=300)
    return Result(text=json.dumps(result, ensure_ascii=False), data=result, warnings=_warn(boot))


# --- connectors (ruling 47 tier 2) ---------------------------------------------------------------------------------

def _connector_line(c: dict) -> str:
    state = "connected" if c.get("connected") else "not connected"
    tail = f", last sync {c['lastSync']}" if c.get("lastSync") else ""
    error = f"\n    {c['lastError']}" if c.get("lastError") else ""
    reads = f"\n    {c['reads']}" if c.get("reads") else ""
    return f"{c.get('id')}: {c.get('label')} — {state}{tail}{error}{reads}"


def cmd_connector_list(boot, args) -> Result:
    data = call(boot, "GET", "/sources/connectors")
    rows = data.get("connectors") or []
    return Result(text="\n".join(_connector_line(c) for c in rows) or "No connectors.", data=data,
                  warnings=_warn(boot))


def read_token(label: str) -> str:
    """A token from standard input only — never argv (a process list and shell history would keep it)."""
    import getpass
    import sys

    if sys.stdin.isatty():
        return (getpass.getpass(f"{label}: ") or "").strip()
    return (sys.stdin.readline() or "").strip()


def cmd_connector_connect(boot, args) -> Result:
    """The token goes straight to the backend, which checks it with the service before writing it to secrets.env
    (0600); the CLI never stores or prints it."""
    import sys

    require_person("Connecting an account with your token")
    status = call(boot, "GET", f"/sources/connectors/{args.connector}")
    fields = list(status.get("fields") or [])
    if len(fields) != 1 or status.get("loginMode") != "credentials":
        raise Refusal("refused", f"{status.get('label') or args.connector} is connected in the app (Settings → "
                                 "Sources), where it signs in. Nothing was changed.")
    field = fields[0]
    if status.get("reads"):
        sys.stderr.write(status["reads"] + "\n")
    if status.get("tokenHelp"):
        sys.stderr.write(f"Get your token at {status['tokenHelp']}.\n")
    value = read_token(field.get("label") or "Token")
    if not value:
        raise UsageError("no token on standard input; nothing was changed")
    result = call(boot, "PUT", f"/sources/connectors/{args.connector}/credentials",
                  body={"fields": {field["name"]: value}}, timeout=60)
    return Result(text=f"{result.get('label')} is connected. It syncs every few hours; `cicada connector sync "
                       f"{args.connector}` reads it now.",
                  data={"connector": args.connector, "connected": bool(result.get("connected"))}, warnings=_warn(boot))


def cmd_connector_disconnect(boot, args) -> Result:
    require_person("Disconnecting an account")
    result = call(boot, "DELETE", f"/sources/connectors/{args.connector}/credentials")
    return Result(text=f"{result.get('label')} is disconnected; Cicada forgot its token. What it brought in stays.",
                  data={"connector": args.connector, "connected": bool(result.get("connected"))}, warnings=_warn(boot))


def cmd_connector_sync(boot, args) -> Result:
    require_person("Reading an account now")
    result = call(boot, "POST", f"/sources/connectors/{args.connector}/sync", timeout=600)
    status = result.get("status")
    if status == "ok":
        text = f"{result.get('new', 0)} new, {result.get('seen', 0)} read."
    elif status == "skipped":
        text = f"Skipped: {result.get('reason')}"
    else:
        text = f"The sync failed: {result.get('error')}"
    return Result(text=text, data=result, warnings=_warn(boot))


def refuse_harness_folder(path: Path) -> None:
    """The rail: transcripts under ~/.claude are read only by the Stop hook's capture — never imported, by either
    import path, file or folder."""
    claude_root = Path(os.path.realpath(os.path.expanduser("~/.claude")))
    real = Path(os.path.realpath(path))
    if real == claude_root or claude_root in real.parents:
        raise Refusal("refused", "Files under ~/.claude are captured by Cicada's own hook, never imported. "
                                 "Nothing was read.")


def _readable_file(raw: str) -> Path:
    path = Path(os.path.expanduser(raw))
    if not path.is_file():
        raise UsageError(f"no file at {raw}")
    refuse_harness_folder(path)
    return path


def chat_export(path: Path) -> bytes | None:
    """The file's bytes when the intake's own chat reader finds conversations in it (``intake.parse_export``, the
    order the backend's sniff uses: a chat export first, a platform's save lists otherwise), else None. A folder
    is never a chat export here: the intake takes one file."""
    if not path.is_file():
        return None
    from api.routers import intake

    from fastapi import HTTPException

    content = path.read_bytes()
    try:
        parsed = intake.parse_export(content, path.name)
    except HTTPException as exc:
        if exc.detail in intake.FINAL_REFUSALS:
            # A page the intake refuses for good (the ChatGPT chat.html viewer; Takeout activity of a product other
            # than Gemini): the backend's sniff never offers it to the platform reader either, so neither does this.
            raise Refusal("refused", str(exc.detail)) from None
        return None
    except Exception:  # noqa: BLE001 - not a chat export (the reader's refusal is the platform reader's to give)
        return None
    return content if parsed.episodes else None


def import_chat_export(boot, args, path: Path, content: bytes) -> Result:
    """`cicada import`'s chat branch: a ChatGPT / Claude / Gemini export goes to the backend's intake, the app's
    path (`/intake/sniff` for --preview, `/intake/import`, then `/intake/jobs/{id}` until it is done)."""
    payload = (path.name, content)
    if args.preview:
        sniff = call(boot, "POST", "/intake/sniff", upload=("file", *payload), timeout=300)
        counts = sniff.get("delta") or {}
        text = (f"{sniff.get('vendor') or sniff.get('kind') or 'unknown'}: {counts.get('new', 0)} new, "
                f"{counts.get('grown', 0)} grown, {counts.get('unchanged', 0)} already here"
                if sniff.get("recognized") else "Cicada does not recognise this file as a conversation export.")
        return Result(text=text, data=sniff, warnings=_warn(boot))
    result = call(boot, "POST", "/intake/import", upload=("file", *payload), timeout=600)
    job = result.get("job") if isinstance(result.get("job"), dict) else None
    if job and not args.no_wait:
        deadline = time.monotonic() + JOB_WAIT_MAX_S
        status = {}
        while time.monotonic() < deadline:
            status = call(boot, "GET", f"/intake/jobs/{quote(str(job.get('id')), safe='')}")
            if status.get("done"):
                break
            time.sleep(JOB_POLL_S)
        result = {**result, "jobStatus": status}
        if status.get("error"):
            raise Refusal("backend_error", f"The import stopped: {status['error']}", _warn(boot))
        if not status.get("done"):
            raise Refusal("backend_timeout", f"The import is still running in the app's backend (job {job.get('id')})"
                                             f": {status.get('staged', 0)} of {status.get('total', '?')} staged so far. "
                                             "It keeps going; Sleep reads what it stages.", _warn(boot))
        text = (f"Imported: {status.get('created', 0)} new, {status.get('updated', 0)} updated, "
                f"{status.get('skipped', 0)} already here.")
    elif job:
        text = f"Importing in the background (job {job.get('id')}); Sleep reads them next."
    else:
        text = (f"Imported: {result.get('episodesStaged', 0)} new, {result.get('episodesUpdated', 0)} updated, "
                f"{result.get('duplicatesSkipped', 0)} already here.")
    return Result(text=text, data=result, warnings=_warn(boot))


# --- settings and engines -----------------------------------------------------------------------------------

def cmd_settings_owner(boot, args) -> Result:
    owner = call(boot, "GET", "/settings/owner")
    if args.name is None and args.handle is None and args.email is None:
        return Result(text=f"You are: {owner.get('name') or '(not set)'}", data=owner, warnings=_warn(boot))
    require_person("Setting who you are")
    name = args.name if args.name is not None else owner.get("name") or ""
    if not name.strip():
        raise UsageError("--name is required the first time")
    body = {"name": name, "handle": args.handle if args.handle is not None else owner.get("handle"),
            "email": args.email if args.email is not None else owner.get("email")}
    saved = call(boot, "PUT", "/settings/owner", body=body)
    return Result(text=f"You are: {saved.get('name')}", data=saved, warnings=_warn(boot))


def _engine_state(c: dict) -> str:
    """One engine's readiness in words (owner decision 2, 2026-10-16): a key card with no key says so, never
    "available"; a plan says whether it is signed in on the machine Sleep runs on."""
    billing = c.get("billing")
    if billing == "subscription":
        if c.get("connected"):
            plan = c.get("planLabel") or c.get("plan")
            return "signed in" + (f" ({plan})" if plan else "")
        return "not signed in" if c.get("available") else "not installed"
    if billing == "free":
        return "running" if c.get("connected") else ("not running" if c.get("available") else "not installed")
    return "key set" if c.get("connected") else "no key"


def _preview_line(label: str, preview: dict | None) -> str | None:
    if not isinstance(preview, dict):
        return None
    return f"{label}: {preview.get('engine', '?')} · {preview.get('model', '?')}"


def cmd_engine_list(boot, args) -> Result:
    data = call(boot, "GET", "/connections")
    rows = data.get("connections", []) if isinstance(data, dict) else []
    lines = [f"{c.get('id')}  {c.get('label')}  {_engine_state(c)}" for c in rows if isinstance(c, dict)]
    out = dict(data) if isinstance(data, dict) else {"connections": rows}
    try:
        engine = call(boot, "GET", "/sleep/engine")
        opts = call(boot, "GET", "/sleep/run-options")
        sched = call(boot, "GET", "/sleep/schedule")
    except Refusal:
        engine, opts, sched = {}, {}, {}
    preview = engine.get("preview") if isinstance(engine, dict) else None
    preview = preview if isinstance(preview, dict) else {}
    extra = [line for line in (_preview_line("Sleep you start", preview.get("manual")),
                               _preview_line("Scheduled Sleep", preview.get("scheduled"))) if line]
    if opts:
        extra.append("Scheduled runs may use your plan: "
                      + ("on" if opts.get("scheduledUsePlan") else "off (`cicada sleep schedule --use-plan on`)"))
    if sched and sched.get("mode") not in (None, "manual"):
        warning = _schedule_warning(sched)
        if warning:
            extra.append(f"Warning: {warning}")
    out.update({"preview": preview, "scheduledUsePlan": bool(opts.get("scheduledUsePlan")) if opts else None,
                "scheduleWarning": sched.get("warningCode") if sched else None})
    text = "\n".join([*lines, *([""] if lines and extra else []), *extra])
    return Result(text=text or "No engines.", data=out, warnings=_warn(boot))


#: Each plan's own sign-in, run in the person's terminal on the machine Sleep runs on (ruling 4b). Only flags the CLIs'
#: own help lists: `claude auth login --claudeai` (Claude Code 2.1, the subscription — its default) and `codex login
#: --device-auth` (Codex CLI 0.16x, the headless device code, in Cicada's own CODEX_HOME through `scrubbed_env`).
@dataclass(frozen=True)
class PlanSignIn:
    binary: str
    product: str
    status: tuple[str, ...]
    login: tuple[str, ...]
    intro: str
    engine_mode: str
    alt: str


PLAN_SIGN_INS = {
    "claude-plan": PlanSignIn(
        binary="claude", product="Claude Code", status=("auth", "status", "--json"), login=("auth", "login", "--claudeai"),
        intro=("Claude Code will sign in to your Claude plan on this machine. It prints a link: open it on any device, "
               "sign in, and if it shows a code, paste the code back here. Claude Code keeps the sign-in where it keeps "
               "its own; Cicada never sees or stores the token."),
        engine_mode="agent",
        alt=("If the sign-in cannot finish on this machine, `claude setup-token` on any machine where it works prints a "
             "long-lived token; set it as CLAUDE_CODE_OAUTH_TOKEN in the backend's own environment (on Linux: "
             "`systemctl --user edit cicada-backend.service`, then an `Environment=` line under `[Service]`). Cicada "
             "never asks for it, stores it or prints it.")),
    "chatgpt-plan": PlanSignIn(
        binary="codex", product="the Codex CLI", status=("login", "status"), login=("login", "--device-auth"),
        intro=("The Codex CLI will sign in to your ChatGPT plan for Cicada on this machine. It prints a link and a "
               "one-time code: open the link on any device, sign in, and enter the code. The sign-in is kept in "
               "Cicada's own Codex folder, apart from Codex in your terminal; Cicada never sees or stores the token."),
        engine_mode="codex",
        alt=("If the sign-in cannot finish, run `cicada engine connect chatgpt-plan` again from a terminal on this "
             "machine.")),
}
PLAN_AUTH_METHODS = ("claude.ai", "oauth_token")
#: Kept for callers that name the Claude texts directly.
CONNECT_INTRO = PLAN_SIGN_INS["claude-plan"].intro
CONNECT_HEADLESS_ALT = PLAN_SIGN_INS["claude-plan"].alt


def _connect_next(plan: PlanSignIn) -> str:
    return (f"Runs you start can read with it once Sleep reads with your plan (`cicada sleep engine --mode "
            f"{plan.engine_mode}`). Scheduled runs use it only when you say so: `cicada sleep schedule --use-plan on`.")


def _plan_binary(name: str) -> str | None:
    import shutil

    return shutil.which(name)


def _claude_binary() -> str | None:
    return _plan_binary("claude")


def _interactive() -> bool:
    import sys

    return sys.stdin.isatty()


def _signed_in(plan: PlanSignIn, binary: str) -> bool | None:
    """The plan CLI's own answer: True for a plan sign-in, False for none (or an API key, which is not a plan), None
    when it could not be asked. Claude Code answers JSON; the Codex CLI answers with its exit code and a sentence."""
    import subprocess

    from api.services.connections.base import scrubbed_env

    try:
        done = subprocess.run([binary, *plan.status], capture_output=True, text=True, timeout=20,
                              env=scrubbed_env(plan.binary), stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    if plan.binary == "codex":
        said = f"{done.stdout}\n{done.stderr}".lower()
        return done.returncode == 0 and "api key" not in said
    try:
        info = json.loads(done.stdout.strip() or "{}")
    except ValueError:
        return None
    return bool(info.get("loggedIn")) and info.get("authMethod") in (None, *PLAN_AUTH_METHODS)


def _claude_signed_in(binary: str) -> bool | None:
    return _signed_in(PLAN_SIGN_INS["claude-plan"], binary)


def _run_sign_in(plan: PlanSignIn, binary: str) -> int:
    """The plan CLI's sign-in in this terminal: its own prompts, its own link, its own storage. The child gets
    Cicada's scrubbed environment, so a provider key in this shell cannot turn the sign-in into a metered one (and a
    `codex` child signs in to Cicada's own Codex home)."""
    import subprocess

    from api.services.connections.base import scrubbed_env

    try:
        return subprocess.run([binary, *plan.login], env=scrubbed_env(plan.binary)).returncode
    except (OSError, subprocess.SubprocessError):
        return 1


def cmd_engine_connect(boot, args) -> Result:
    """Ruling 4b (owner, 2026-10-16): "Just have to set them up somehow" — a plan on a server, signed in by its own
    CLI in the person's own terminal ("Yeah chat too": the ChatGPT plan as well). Only plans are connected here; a key
    goes in Settings → Intelligence → Plans & keys or `~/.cicada/secrets.env`."""
    import sys

    plan = PLAN_SIGN_INS.get(args.connection)
    if plan is None:
        raise UsageError("`claude-plan` or `chatgpt-plan` is connected from here; an API key goes in Settings → Plans "
                         "& keys or ~/.cicada/secrets.env")
    require_person("Signing in to your plan")
    if getattr(boot, "client", False):
        raise Refusal("on_server", "Your memory and its Sleep run on the server, so the plan is signed in there: run "
                                   f"`cicada engine connect {args.connection}` in a terminal on the server. Nothing "
                                   "was changed.")
    binary = _plan_binary(plan.binary)
    if binary is None:
        raise Refusal("refused", f"{plan.product[0].upper() + plan.product[1:]} is not installed on this machine, and "
                                 f"it is what signs in to your plan. Install it, then run `cicada engine connect "
                                 f"{args.connection}` again. Nothing was changed.")
    lines: list[str] = []
    if _signed_in(plan, binary):
        lines.append("Your plan is already signed in on this machine.")
    else:
        if getattr(args, "json", False) or getattr(args, "format", None) == "json":
            raise Refusal("refused", f"Signing in shows {plan.product}'s own prompts, which --json would hide: run "
                                     f"`cicada engine connect {args.connection}` without it. Nothing was changed.")
        if not _interactive():
            raise Refusal("refused", f"Signing in needs your own terminal: run `cicada engine connect "
                                     f"{args.connection}` in a terminal on this machine. Nothing was changed. "
                                     + plan.alt)
        sys.stderr.write(plan.intro + "\n\n")
        sys.stderr.flush()
        _run_sign_in(plan, binary)
        if not _signed_in(plan, binary):
            raise Refusal("refused", f"{plan.product[0].upper() + plan.product[1:]} did not finish signing in, so "
                                     f"nothing changed. Run `cicada engine connect {args.connection}` again. "
                                     + plan.alt)
        lines.append("Your plan is signed in on this machine.")
    status = call(boot, "GET", f"/connections/{args.connection}", query={"fresh": "true"})
    if not status.get("connected"):
        lines.append("Cicada's backend does not see the sign-in yet: it runs as another user or with another home. "
                     + plan.alt)
    lines.append(_connect_next(plan))
    return Result(text="\n".join(lines), data={"connection": args.connection,
                                               "connected": bool(status.get("connected")),
                                               "plan": status.get("plan")}, warnings=_warn(boot))


# --- pictures ------------------------------------------------------------------------------------------------

def _picture_text(entity_id: str, payload: dict) -> str:
    return f"{entity_id}: picture from {payload.get('pictureSource') or 'nothing (a monogram)'}."


def cmd_picture_set(boot, args) -> Result:
    require_person("Choosing a page's picture")
    path = _readable_file(args.file)
    payload = call(boot, "POST", f"/entities/{quote(args.entity_id, safe='')}/picture",
                   upload=("file", path.name, path.read_bytes()))
    return Result(text=_picture_text(args.entity_id, payload), data=payload, warnings=_warn(boot))


def cmd_picture_initials(boot, args) -> Result:
    require_person("Choosing a page's picture")
    payload = call(boot, "POST", f"/entities/{quote(args.entity_id, safe='')}/picture/initials")
    return Result(text=_picture_text(args.entity_id, payload), data=payload, warnings=_warn(boot))


def cmd_picture_clear(boot, args) -> Result:
    require_person("Clearing a page's picture")
    payload = call(boot, "DELETE", f"/entities/{quote(args.entity_id, safe='')}/picture")
    return Result(text=_picture_text(args.entity_id, payload), data=payload, warnings=_warn(boot))


# --- banks -----------------------------------------------------------------------------------------------------

def _bank_lines(listing: dict) -> list[str]:
    out = []
    for b in listing.get("banks", []):
        flags = [w for w, on in (("active", b.get("active")), ("demo", b.get("demo"))) if on]
        out.append(f"{b.get('name')}  {b.get('entity_count', b.get('entityCount', 0))} page(s), "
                   f"{b.get('episode_count', b.get('episodeCount', 0))} conversation(s)"
                   + (f"  [{', '.join(flags)}]" if flags else ""))
    return out


def cmd_bank_list(boot, args) -> Result:
    from api.services import bank_registry

    if getattr(boot, "client", False):
        listing = call(boot, "GET", "/banks")       # G181 phase 2: the banks are on the server
    else:
        listing = bank_registry.list_banks(Path(boot.root))
    return Result(text="\n".join(_bank_lines(listing)), data=listing, warnings=_warn(boot))


def cmd_bank_use(boot, args) -> Result:
    require_person("Switching the active memory")
    listing = call(boot, "POST", f"/banks/{quote(args.bank_name, safe='')}/activate", bank_header=False, timeout=600)
    return Result(text=f"Now using '{listing.get('active')}'.", data=listing, warnings=_warn(boot))


def cmd_bank_create(boot, args) -> Result:
    listing = call(boot, "POST", "/banks", body={"name": args.bank_name, "description": args.description},
                   bank_header=False)
    return Result(text="\n".join(_bank_lines(listing)), data=listing, warnings=_warn(boot))


def cmd_bank_rename(boot, args) -> Result:
    require_person("Renaming a memory")
    listing = call(boot, "POST", f"/banks/{quote(args.bank_name, safe='')}/rename", body={"newName": args.new_name},
                   bank_header=False)
    return Result(text="\n".join(_bank_lines(listing)), data=listing, warnings=_warn(boot))


def cmd_bank_delete(boot, args) -> Result:
    require_person("Moving a memory to the trash")
    listing = call(boot, "DELETE", f"/banks/{quote(args.bank_name, safe='')}", bank_header=False)
    return Result(text=f"Moved '{args.bank_name}' to {listing.get('trashedTo', 'the trash')} (nothing erased).",
                  data=listing, warnings=_warn(boot))


# --- a read mirror the CLI now holds ------------------------------------------------------------------------

def cmd_timeline(boot, args) -> Result:
    from api.services import mcp_tools

    from api.services import cli_map

    if getattr(boot, "client", False):
        # G181 phase 2: the bank is on the server.
        return Result(text=str(door(boot, "cicada_timeline", {"since": args.since})), data=None, warnings=_warn(boot))
    path = boot.pin.path
    ctx = mcp_tools.ToolContext(memory_path=lambda: path, session_id="", harness="unknown", read_surface="cli",
                                available=cli_map.exposed_tools())
    return Result(text=str(mcp_tools.timeline(ctx, args.since)), data=None, warnings=_warn(boot))


# --- skills (the Skills page, 2026-10-15) -------------------------------------------------------------------

def _wait_job(boot, job: dict | None, what: str) -> dict:
    if not job:
        return {}
    deadline = time.monotonic() + JOB_WAIT_MAX_S
    status = job
    while time.monotonic() < deadline and status.get("state") == "running":
        time.sleep(JOB_POLL_S)
        status = call(boot, "GET", f"/skills/jobs/{quote(str(job.get('id')), safe='')}")
    if status.get("state") == "failed":
        raise Refusal("refused", f"{what} stopped: {status.get('message') or 'it failed'}", _warn(boot))
    if status.get("state") == "running":
        raise Refusal("backend_timeout", f"{what} is still running in the app's backend.", _warn(boot))
    return status


def cmd_skills_check(boot, args) -> Result:
    require_person("Checking skills for updates")
    data = call(boot, "POST", "/skills/check", body={}, timeout=120)
    results = data.get("results") or {}
    lines = [f"{name}: update available ({r.get('latest')})" + (f" — {r['link']}" if r.get("link") else "")
             for name, r in sorted(results.items()) if isinstance(r, dict) and r.get("state") == "available"]
    return Result(text="\n".join(lines) or "Every skill Cicada can check is up to date.", data=data,
                  warnings=_warn(boot))


def cmd_skills_add(boot, args) -> Result:
    require_person("Adding a skill")
    shown = call(boot, "POST", "/skills/preview", body={"source": args.source, "choose": args.choose}, timeout=120)
    if shown.get("choices"):
        names = ", ".join(c.get("path") or c.get("name") for c in shown["choices"])
        return Result(text=f"That repository holds several skills; pick one with --choose: {names}", data=shown,
                      warnings=_warn(boot))
    repo = shown.get("repo") or {}
    lines = [f"{shown.get('name')} — {shown.get('description')}",
             f"From {repo.get('repo')} at {str(repo.get('commit') or '')[:7]}"
             + (f" ({repo.get('licence')})" if repo.get("licence") else ""),
             f"{len(shown.get('files') or [])} file(s)" + (f"; scripts: {', '.join(shown['scripts'])}"
                                                          if shown.get("scripts") else "")]
    if not args.yes:
        lines.append("Nothing installed. Run again with --yes (and --agent …) to install it, pinned to this commit.")
        return Result(text="\n".join(lines), data=shown, warnings=_warn(boot))
    agents = args.agent or shown.get("agents") or ["claude-code"]
    done = call(boot, "POST", "/skills/install", body={"planId": shown.get("planId"), "agents": agents})
    lines.append(f"Installed for {', '.join(done.get('agents') or agents)}.")
    return Result(text="\n".join(lines), data=done, warnings=_warn(boot))


def cmd_skills_install(boot, args) -> Result:
    require_person("Installing a suggested skill")
    result = call(boot, "POST", "/skills/install", body={"suggestion": args.suggestion, "agents": args.agent or []},
                  timeout=300)
    if isinstance(result.get("job"), dict):
        result = {**result, "jobStatus": _wait_job(boot, result["job"], f"Installing {args.suggestion}")}
    return Result(text=f"Installed {args.suggestion}.", data=result, warnings=_warn(boot))


def cmd_skills_update(boot, args) -> Result:
    require_person("Updating a skill")
    result = call(boot, "POST", f"/skills/{quote(args.skill, safe='')}/update", body={})
    status = _wait_job(boot, result.get("job"), f"Updating {args.skill}")
    return Result(text=f"Updated {args.skill}.", data=status, warnings=_warn(boot))


def cmd_skills_update_all(boot, args) -> Result:
    require_person("Updating skills")
    result = call(boot, "POST", "/skills/update-all", body={})
    status = _wait_job(boot, result.get("job"), "Updating skills")
    done = (status.get("result") or {}).get("updated") or []
    failed = (status.get("result") or {}).get("failed") or {}
    lines = [f"Updated: {', '.join(done)}" if done else "Nothing to update."]
    lines += [f"{name}: {why}" for name, why in failed.items()]
    return Result(text="\n".join(lines), data=status, warnings=_warn(boot))


def _toggle(boot, args, on: bool) -> Result:
    require_person("Turning a skill on or off")
    result = call(boot, "PUT", f"/skills/{quote(args.skill, safe='')}/agents/{quote(args.agent, safe='')}",
                  body={"on": on})
    return Result(text=f"{args.skill} is {'on' if on else 'off'} for {args.agent}.", data=result, warnings=_warn(boot))


def cmd_skills_on(boot, args) -> Result:
    return _toggle(boot, args, True)


def cmd_skills_off(boot, args) -> Result:
    return _toggle(boot, args, False)


def cmd_skills_refresh(boot, args) -> Result:
    require_person("Refreshing a skill's text")
    result = call(boot, "POST", f"/skills/{quote(args.skill, safe='')}/refresh", body={}, timeout=60)
    return Result(text=f"{args.skill}'s skill text now matches the installed tool.", data=result, warnings=_warn(boot))


def cmd_skills_remove(boot, args) -> Result:
    require_person("Removing a skill")
    result = call(boot, "DELETE", f"/skills/{quote(args.skill, safe='')}")
    return Result(text=f"Removed {args.skill}.", data=result, warnings=_warn(boot))


def cmd_skills_publish(boot, args) -> Result:
    require_person("Publishing a skill")
    if not args.agent:
        raise UsageError("name the agents to publish it to with --agent (e.g. --agent claude-code)")
    result = call(boot, "POST", f"/skills/drafts/{quote(args.skill, safe='')}/publish", body={"agents": args.agent})
    return Result(text=f"Published {args.skill} to {', '.join(result.get('agents') or args.agent)}.", data=result,
                  warnings=_warn(boot))


# --- the person's devices (G181 phase 2, owner ruling 1) ------------------------------------------------------------

def _device_line(d: dict) -> str:
    state = "active" if d.get("active") else f"revoked {d.get('revokedAt') or ''}".rstrip()
    used = f", last used {d['lastUsedAt']}" if d.get("lastUsedAt") else ""
    return f"{d.get('id')}  {d.get('name')}  ({state}{used})"


def cmd_device_add(boot, args) -> Result:
    require_person("Issuing a device token")
    answer = call(boot, "POST", "/devices", body={"name": args.device_name}, bank_header=False)
    device, token = answer.get("device") or {}, answer.get("token") or ""
    text = "\n".join([
        f"Device '{device.get('name')}' ({device.get('id')}). Its token, shown once — Cicada keeps only its hash:",
        token,
        "On that device: put the token in ~/.cicada/device_token (mode 0600) or CICADA_API_TOKEN, and set "
        "CICADA_API_BASE to the address your own overlay gives this server. Revoke it with "
        f"`cicada device revoke {device.get('id')}`."])
    same = [i for i in answer.get("sameName") or [] if isinstance(i, str)]
    if same:
        text += (f"\nNote: another active device is already called '{device.get('name')}' ({', '.join(same)}). "
                 "Two devices may share a name, but `cicada device list` cannot then tell them apart; revoke the "
                 "one you no longer use.")
    return Result(text=text, data={"device": device, "token": token, "sameName": same}, warnings=_warn(boot))


def cmd_device_list(boot, args) -> Result:
    answer = call(boot, "GET", "/devices")
    devices = answer.get("devices") or []
    return Result(text="\n".join(_device_line(d) for d in devices) or "No devices yet (`cicada device add <name>`).",
                  data={"devices": devices}, warnings=_warn(boot))


def cmd_device_revoke(boot, args) -> Result:
    require_person("Revoking a device token")
    answer = call(boot, "DELETE", f"/devices/{quote(args.device_id, safe='')}", bank_header=False)
    device = answer.get("device") or {}
    return Result(text=f"Revoked '{device.get('name')}' ({device.get('id')}): its next request is refused.",
                  data={"device": device}, warnings=_warn(boot))


def cmd_device_pair(boot, args) -> Result:
    require_person("Making a pairing code")
    body: dict = {"url": args.url} if getattr(args, "url", None) else {}
    if getattr(args, "kind", None):
        body["kind"] = args.kind
    answer = call(boot, "POST", "/devices/pairing", body=body, bank_header=False)
    code, pairing = answer.get("code") or "", answer.get("pairing") or {}
    qr = json.dumps(answer.get("qr") or {}, separators=(",", ":"))
    text = "\n".join([
        f"Pairing code: {code}   (good until {pairing.get('expiresAt')}, once)",
        f"QR payload: {qr}",
        f"Kind: {answer.get('kind') or 'capture'} ("
        f"{'links and notes only' if (answer.get('kind') or 'capture') == 'capture' else 'every route a device may use'})",
        *([f"No address in the QR: run `{answer['reach']['serveCommand']}` yourself for your tailnet, then pair "
           "again, or pass --url."] if not (answer.get("qr") or {}).get("url")
          and (answer.get("reach") or {}).get("serveCommand") else []),
        "On the new device: scan it in the Cicada app, or post {\"code\", \"name\"} to <server>/pair. It gets its own "
        "device token; `cicada device list` shows it, `cicada device revoke <id>` ends it."])
    return Result(text=text, data=answer, warnings=_warn(boot))


def _agent_line(t: dict) -> str:
    used = f", last used {t['lastUsedAt']}" if t.get("lastUsedAt") else ""
    return (f"{t.get('id')}  {t.get('name')}  [{','.join(t.get('scopes') or [])}]  "
            f"({t.get('state')}, until {t.get('expiresAt')}{used})")


def cmd_agent_add(boot, args) -> Result:
    require_person("Making an agent token")
    body: dict = {"name": args.agent_name}
    if getattr(args, "scope", None):
        body["scopes"] = list(args.scope)
    if getattr(args, "days", None):
        body["expiresInDays"] = int(args.days)
    if getattr(args, "url", None):
        body["baseUrl"] = args.url
    answer = call(boot, "POST", "/agent-api/tokens", body=body, bank_header=False)
    agent = answer.get("agent") or {}
    text = "\n".join([
        f"Agent '{agent.get('name')}' ({agent.get('id')}), {', '.join(agent.get('scopes') or [])}, until "
        f"{agent.get('expiresAt')}. Give it this, once — Cicada keeps only the token's hash:",
        "",
        answer.get("prompt") or "",
        "",
        f"Revoke it with `cicada agent revoke {agent.get('id')}`. A cloud agent needs a public address: pass --url."])
    return Result(text=text, data=answer, warnings=_warn(boot))


def cmd_agent_list(boot, args) -> Result:
    tokens = call(boot, "GET", "/agent-api/tokens").get("tokens") or []
    return Result(text="\n".join(_agent_line(t) for t in tokens) or "No agent tokens yet (`cicada agent add <name>`).",
                  data={"tokens": tokens}, warnings=_warn(boot))


def cmd_agent_revoke(boot, args) -> Result:
    require_person("Revoking an agent token")
    answer = call(boot, "DELETE", f"/agent-api/tokens/{quote(args.agent_id, safe='')}", bank_header=False)
    agent = answer.get("agent") or {}
    return Result(text=f"Revoked '{agent.get('name')}' ({agent.get('id')}): its next request is refused.",
                  data=answer, warnings=_warn(boot))


def cmd_setup(boot, args) -> Result:
    require_person("Setting up Cicada")
    from api import cli_setup

    def send(method, path, body=None):
        return call(boot, method, path, body=body, bank_header=False) if method != "GET" else call(boot, method, path)

    interactive = sys.stdin.isatty() and sys.stderr.isatty()
    result = cli_setup.run_setup(call=send, ui=cli_setup.Ui(interactive), url=getattr(args, "url", None),
                                 pair_now=True if getattr(args, "pair", None) else None,
                                 agent_name=getattr(args, "agent", None) or None)
    result.warnings = _warn(boot) + list(result.warnings)
    return result


COMMANDS = {
    "page list": cmd_page_list, "page history": cmd_page_history, "page decay": cmd_page_decay,
    "graph": cmd_graph, "find": cmd_find,
    "coverage pictures": cmd_coverage_pictures, "coverage sources": cmd_coverage_sources,
    "inbox all": cmd_inbox_all, "inbox answer": cmd_inbox_answer,
    "sleep status": cmd_sleep_status, "sleep start": cmd_sleep_start, "sleep stop": cmd_sleep_stop,
    "sleep end": cmd_sleep_end, "sleep schedule": cmd_sleep_schedule, "sleep engine": cmd_sleep_engine,
    "sleep options": cmd_sleep_options, "sleep history": cmd_sleep_history,
    "maintenance move-watched-rows": cmd_maintenance_move_watched_rows,
    "index status": cmd_index_status, "index rebuild": cmd_index_rebuild, "index use": cmd_index_use,
    "index install": cmd_index_install,
    "projects new": cmd_projects_new,
    "feed list": cmd_feed_list, "feed add": cmd_feed_add, "feed remove": cmd_feed_remove, "feed poll": cmd_feed_poll,
    "connector list": cmd_connector_list, "connector connect": cmd_connector_connect,
    "connector disconnect": cmd_connector_disconnect, "connector sync": cmd_connector_sync,
    "settings owner": cmd_settings_owner, "engine list": cmd_engine_list, "engine connect": cmd_engine_connect,
    "picture set": cmd_picture_set, "picture initials": cmd_picture_initials, "picture clear": cmd_picture_clear,
    "bank list": cmd_bank_list, "bank use": cmd_bank_use, "bank create": cmd_bank_create,
    "bank rename": cmd_bank_rename, "bank delete": cmd_bank_delete,
    "timeline": cmd_timeline,
    "skills check": cmd_skills_check, "skills add": cmd_skills_add, "skills install": cmd_skills_install,
    "skills update": cmd_skills_update, "skills update-all": cmd_skills_update_all, "skills on": cmd_skills_on,
    "skills off": cmd_skills_off, "skills refresh": cmd_skills_refresh, "skills remove": cmd_skills_remove,
    "skills publish": cmd_skills_publish,
    "device add": cmd_device_add, "device list": cmd_device_list, "device revoke": cmd_device_revoke,
    "device pair": cmd_device_pair,
    "setup": cmd_setup,
    "agent add": cmd_agent_add, "agent list": cmd_agent_list, "agent revoke": cmd_agent_revoke,
}


def validate(command: str, args) -> None:
    """Checks that need no memory, before the bootstrap."""
    if command == "find" and not args.query.strip():
        raise UsageError("the query is empty")
    for attr in ("entity_id", "bank_name", "new_name", "url", "item_id", "file", "path"):
        value = getattr(args, attr, None)
        if isinstance(value, str) and not value.strip():
            raise UsageError(f"the {attr.replace('_', ' ')} is empty")
    if command == "sleep schedule":
        if args.at is not None:
            _hhmm(args.at)
        if args.every is not None and not 1 <= args.every <= 168:
            raise UsageError("--every takes 1 to 168 hours")
    if command == "sleep options" and args.continue_after_reset is not None:
        _on_off(args.continue_after_reset)
    if command == "sleep schedule" and getattr(args, "use_plan", None) is not None:
        _on_off(args.use_plan)
