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
import time
import uuid
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
    token = (environ.get("CICADA_API_TOKEN") or "").strip()
    if not token:
        try:
            token = (runtime_layout.cicada_home(environ) / "api_token").read_text(encoding="utf-8").strip()
        except OSError:
            token = ""
    return {"Authorization": f"Bearer {token}"} if token else {}


def _opener():
    import urllib.request

    return urllib.request.build_opener(urllib.request.ProxyHandler({}))   # loopback never goes through a proxy


def probe_backend(url: str, root, timeout: float) -> dict:
    """Ask a running backend which memory root it serves. ``backend_down`` only on a refused
    connection; a timeout, an error answer or no root in it is ``unverified``, never "no backend"."""
    import socket
    import urllib.error

    try:
        with _opener().open(f"{url}/healthz", timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError:
        return {"state": "unverified"}
    except urllib.error.URLError as exc:
        return {"state": "backend_down" if isinstance(exc.reason, ConnectionRefusedError) else "unverified"}
    except ConnectionRefusedError:
        return {"state": "backend_down"}
    except (TimeoutError, socket.timeout, OSError, ValueError):
        return {"state": "unverified"}
    reported = body.get("memoryRoot") if isinstance(body, dict) else None
    if not isinstance(reported, str) or not reported.strip():
        return {"state": "unverified"}
    same = os.path.realpath(os.path.expanduser(reported)) == os.path.realpath(root)
    out = {"state": "confirmed" if same else "mismatch"}
    if isinstance(body.get("version"), str):
        out["version"] = body["version"]
    return out


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
        boot.probe = probe_backend(boot.backend_url, boot.root, CONFIRM_TIMEOUT_S)
    state = boot.probe.get("state")
    if state == "confirmed":
        return
    if state == "backend_down":
        raise Refusal("backend_down", DOWN_TEXT)
    if state == "mismatch":
        raise Refusal("root_mismatch", MISMATCH_TEXT, _warn(boot))
    raise Refusal("root_unverified", UNVERIFIED_TEXT, _warn(boot) or ["root_unverified"])


DOWN_TEXT = ("The app's backend is not running, and this command acts on it. Open Cicada (or start its backend) "
             "and try again. Nothing was changed.")


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
        raise Refusal("backend_down", DOWN_TEXT)
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
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with _opener().open(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        _raise_for(exc, _warn(boot))
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, ConnectionRefusedError):
            raise Refusal("backend_down", DOWN_TEXT) from None
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            raise Refusal("backend_timeout", "The app's backend did not answer in time; it may still be working "
                                             "on it. Check with `cicada sleep status` or the app.") from None
        raise Refusal("backend_down", DOWN_TEXT) from None
    except ConnectionRefusedError:
        raise Refusal("backend_down", DOWN_TEXT) from None
    except (TimeoutError, socket.timeout):
        raise Refusal("backend_timeout", "The app's backend did not answer in time; it may still be working on "
                                         "it. Check with `cicada sleep status` or the app.") from None
    if not raw:
        return {}
    try:
        return json.loads(raw.decode("utf-8"))
    except ValueError:
        raise Refusal("backend_error", "The app's backend answered something that is not JSON.") from None


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
    if status == 409 and code == "bank_mismatch":
        raise Refusal("bank_mismatch", "The active memory changed before this was sent. Nothing was changed.", w)
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


def cmd_find(boot, args) -> Result:
    """The app's find (`GET /search`'s body, in process): every kind unless --kind narrows it."""
    from api.services import search_service

    kinds = (search_service.parse_kinds(",".join(args.kind), None) if args.kind else list(search_service.KINDS))
    resp = search_service.search(Path(boot.pin.path), args.query, kinds=kinds, mode="hybrid",
                                 per_kind=min(args.limit or 8, search_service.MAX_PER_KIND))
    data = _dump(resp)
    lines = [f"[{hit.get('kind')}] {hit.get('id')}  {hit.get('name') or ''}".rstrip()
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

def cmd_sleep_status(boot, args) -> Result:
    st = call(boot, "GET", "/sleep/status")
    status = st.get("status", "unknown")
    lines = [f"Sleep: {status}" + (" (writing to your pages)" if st.get("writing") else "")]
    if status == "running":
        lines.append(f"  stage {st.get('stage', 0)} of {st.get('totalStages', 5)}"
                     + (f": {st['progress']}" if st.get("progress") else ""))
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


def cmd_sleep_schedule(boot, args) -> Result:
    cfg = call(boot, "GET", "/sleep/schedule")
    if args.mode is None and args.at is None and args.every is None:
        return Result(text=_schedule_text(cfg), data=cfg, warnings=_warn(boot))
    require_person("Changing when Sleep runs")
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
    return Result(text=_schedule_text(saved), data=saved, warnings=_warn(boot))


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


def cmd_feed_remove(boot, args) -> Result:
    result = call(boot, "DELETE", "/sources/feeds", body={"url": args.url})
    return Result(text=f"Unsubscribed from {args.url}.", data=result, warnings=_warn(boot))


def cmd_feed_poll(boot, args) -> Result:
    require_person("Fetching every feed now")
    result = call(boot, "POST", "/sources/poll-feeds", timeout=300)
    return Result(text=json.dumps(result, ensure_ascii=False), data=result, warnings=_warn(boot))


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


def cmd_engine_list(boot, args) -> Result:
    data = call(boot, "GET", "/connections")
    rows = data.get("connections", []) if isinstance(data, dict) else []
    lines = [f"{c.get('id')}  {c.get('label')}  "
             f"{'connected' if c.get('connected') else ('available' if c.get('available') else 'not set up')}"
             for c in rows if isinstance(c, dict)]
    return Result(text="\n".join(lines) or "No engines.", data=data, warnings=_warn(boot))


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

    path = boot.pin.path
    ctx = mcp_tools.ToolContext(memory_path=lambda: path, session_id="", harness="unknown", read_surface="cli",
                                available=cli_map.exposed_tools())
    return Result(text=str(mcp_tools.timeline(ctx, args.since)), data=None, warnings=_warn(boot))


COMMANDS = {
    "page list": cmd_page_list, "page history": cmd_page_history, "page decay": cmd_page_decay,
    "graph": cmd_graph, "find": cmd_find,
    "inbox all": cmd_inbox_all, "inbox answer": cmd_inbox_answer,
    "sleep status": cmd_sleep_status, "sleep start": cmd_sleep_start, "sleep stop": cmd_sleep_stop,
    "sleep end": cmd_sleep_end, "sleep schedule": cmd_sleep_schedule, "sleep engine": cmd_sleep_engine,
    "sleep options": cmd_sleep_options, "sleep history": cmd_sleep_history,
    "index status": cmd_index_status, "index rebuild": cmd_index_rebuild, "index use": cmd_index_use,
    "index install": cmd_index_install,
    "feed list": cmd_feed_list, "feed add": cmd_feed_add, "feed remove": cmd_feed_remove, "feed poll": cmd_feed_poll,
    "settings owner": cmd_settings_owner, "engine list": cmd_engine_list,
    "picture set": cmd_picture_set, "picture initials": cmd_picture_initials, "picture clear": cmd_picture_clear,
    "bank list": cmd_bank_list, "bank use": cmd_bank_use, "bank create": cmd_bank_create,
    "bank rename": cmd_bank_rename, "bank delete": cmd_bank_delete,
    "timeline": cmd_timeline,
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
