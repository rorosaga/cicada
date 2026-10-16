"""The tool door (G181 phase 2): one MCP tool call — or one `cicada` command's tool mirror — from another of the
person's machines, run here, where the bank is.

A client (``CICADA_API_BASE`` set) never touches a local bank: its stdio MCP server and its `cicada` command send each
call to ``POST /tools/call`` (``api/routers/tools.py``), and this module runs the SAME body a stdio process on this
machine would (``mcp_tools``, ``agentic_write``, ``local_tools``, ``handshake``) under a ``ToolContext`` built from the
request — one body per tool. The tool names are ``cli_map``'s (every stdio tool has one row there; the CLI↔MCP table
stays the source), and a row's ``mutates`` says which calls are writes.

**A device counts as local (owner ruling 3, 2026-10-16).** The call runs as a local stdio call would: not a remote
connector (``connector_id`` stays None, so ``is_remote`` is False), so a harness on the person's G198 trust list
(Claude Code by default) edits a page at once, exactly as on the same machine, and an agent's claims keep G71's
derivation, never ``remote:``. The server knows the call came through a per-device token because the auth dependency
looked the bearer up in ``device_tokens`` and put the device on ``request.state`` — nothing the client says can claim
it — and the device's id rides into the provenance (``device:`` on what it writes). The G135 remote connector is a
different listener with different tokens and stays off the trust list; the ``agent`` author stays off it too.

What differs from a local stdio call, and why:

* **No caller paths.** ``local_files=False``: a picture, screenshot or specimen path names a file on the CLIENT's
  machine, and the backend never opens a path a request names. The client reads its files and sends base64
  (``tool_client.inline_files``).
* **Sleep is asked in-process** (``write_admission.holding``), never over loopback; bodies still take the bank's write
  admission around their own writes, as on one machine.
* **Per-session state round-trips.** What a stdio process keeps in globals — the inbox ids skipped this session, the
  once-per-conversation now-view, the revisions ``cicada_pending`` listed — arrives with the call and goes back
  updated.
* **The repo context's git probe stays with the repository.** For ``cicada_repo_context`` the door answers only the
  page's declared repos (``data``); the client probes git where the repository is.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import quote

from api.services import bank_binding, cli_map, mcp_tools, write_admission

SURFACES = ("mcp", "cli")
MAX_SKIPPED = 500
MAX_LISTED = 2000
#: One write at a time in this door (R-R28's reason): bodies are thread-safe across processes by their file locks, but
#: two concurrent saves in one process gain nothing from racing each other's admission and git lock.
_WRITE_LOCK = threading.Lock()


class DoorError(ValueError):
    """The call is not one the door runs (an unknown tool, a refused surface). ``status`` is the HTTP answer."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


@dataclass
class Caller:
    session_id: str = ""
    harness: str = "unknown"
    project_dir: str | None = None
    client_name: str | None = None
    client_version: str | None = None


@dataclass
class SessionState:
    skipped_inbox_ids: set[str] = field(default_factory=set)
    state_hint_sent: bool = False
    listed_revisions: dict[str, str] = field(default_factory=dict)

    def wire(self) -> dict:
        return {"skipped_inbox_ids": sorted(self.skipped_inbox_ids)[:MAX_SKIPPED],
                "state_hint_sent": self.state_hint_sent,
                "listed_revisions": dict(list(self.listed_revisions.items())[-MAX_LISTED:])}


def _s(a: dict, key: str, default="") -> str:
    return str(a.get(key) or default)


# The stdio server's `handle_tool`, argument for argument, for every body that lives in `mcp_tools`.
DISPATCH: dict[str, Callable[[mcp_tools.ToolContext, dict], str]] = {
    "cicada_recall": lambda c, a: mcp_tools.recall(c, _s(a, "query")),
    "cicada_recall_detail": lambda c, a: mcp_tools.recall_detail(c, _s(a, "entity_id"),
                                                                 start=mcp_tools.line_number(a.get("start"))),
    "cicada_save_episode": lambda c, a: mcp_tools.save_episode(c, _s(a, "content"), a.get("title")),
    "cicada_check_nudges": lambda c, a: mcp_tools.check_nudges(c, a.get("topic"), a.get("entity_ids"), a.get("mode")),
    "cicada_timeline": lambda c, a: mcp_tools.timeline(c, a.get("since")),
    "cicada_project": lambda c, a: mcp_tools.project(c, _s(a, "project"), a.get("since"), a.get("tz")),
    "cicada_note_progress": lambda c, a: mcp_tools.note_progress(
        c, _s(a, "project"), _s(a, "kind"), _s(a, "summary"), _s(a, "status"), when=a.get("when"),
        target=a.get("target"), milestone=a.get("milestone"), settles=a.get("settles"),
        participants=a.get("participants"), evidence=a.get("evidence")),
    "cicada_backlog": lambda c, a: mcp_tools.backlog(c, _s(a, "project"), a.get("status"), a.get("item")),
    "cicada_add_backlog_item": lambda c, a: mcp_tools.add_backlog_item(
        c, _s(a, "project"), _s(a, "title"), _s(a, "description"), a.get("triage"), a.get("paid")),
    "cicada_add_backlog_note": lambda c, a: mcp_tools.add_backlog_note(c, _s(a, "item"), _s(a, "note"),
                                                                       a.get("status")),
    "cicada_save_design": lambda c, a: mcp_tools.save_design(
        c, a.get("url"), a.get("note"), a.get("image_path"), a.get("image_base64"), a.get("title"),
        a.get("snippets"), a.get("tags"), a.get("region"), a.get("tokens")),
    "cicada_design_search": lambda c, a: mcp_tools.design_search(c, a.get("query"), a.get("image_path"),
                                                                 a.get("image_base64"), a.get("limit", 8)),
    "cicada_skills": lambda c, a: mcp_tools.skills(c),
    "cicada_propose_skill": lambda c, a: mcp_tools.propose_skill(c, a.get("action"), a.get("source"), a.get("skill"),
                                                                 a.get("agents"), a.get("reason")),
    "cicada_create_skill": lambda c, a: mcp_tools.create_skill(c, a.get("skill"), a.get("description"),
                                                               a.get("body"), a.get("reason")),
    "cicada_open_hub": lambda c, a: mcp_tools.open_hub(c, _s(a, "hub")),
    "cicada_ask": lambda c, a: mcp_tools.ask(c, _s(a, "query"), a.get("top_k", 6)),
    "cicada_get_perspective": lambda c, a: mcp_tools.get_perspective(
        c, _s(a, "subject"), a.get("observer"), a.get("context"), bool(a.get("history", False))),
    "cicada_save_url": lambda c, a: mcp_tools.save_url(c, _s(a, "url"), a.get("note")),
    "cicada_record_watch": lambda c, a: mcp_tools.record_watch(
        c, _s(a, "url"), _s(a, "summary"), a.get("excerpts"), a.get("chapters"), a.get("basis"), a.get("engine"),
        a.get("duration")),
    "cicada_video_queue": lambda c, a: mcp_tools.video_queue_list(c, a.get("limit")),
    "cicada_video_claim": lambda c, a: mcp_tools.video_claim(c, a.get("limit"), a.get("release")),
    "cicada_explore_queue": lambda c, a: mcp_tools.explore_queue_list(c, a.get("limit")),
    "cicada_explore_claim": lambda c, a: mcp_tools.explore_claim(c, a.get("limit"), a.get("release")),
    "cicada_record_capture": lambda c, a: mcp_tools.record_capture(
        c, _s(a, "url"), _s(a, "lease_token"), _s(a, "outcome"), a.get("captured_at"), a.get("final_url"),
        a.get("http_status"), a.get("shots"), a.get("page"), a.get("signed_in"),
        bool(a.get("account_visible", False)), bool(a.get("consent_overlay", False)), a.get("consent_box"),
        a.get("next_pages"), a.get("loads"), a.get("via"), a.get("last_modified"), a.get("loaded_at"),
        a.get("pages"), a.get("found"), a.get("robots"), a.get("section"), a.get("design")),
    "cicada_site_map": lambda c, a: mcp_tools.site_map_read(c, a.get("site")),
    "cicada_explore_start": lambda c, a: mcp_tools.explore_start(c, a.get("scope"), a.get("origins"),
                                                                 a.get("look")),
    "cicada_record_check": lambda c, a: mcp_tools.record_check(
        c, _s(a, "item_id"), _s(a, "source"), _s(a, "outcome"), a.get("option_key"), a.get("proposed_value"),
        a.get("quotes"), a.get("summary"), a.get("via")),
    "cicada_refresh_claim": lambda c, a: mcp_tools.refresh_claim(c, a.get("limit"), a.get("release")),
    "cicada_record_refresh": lambda c, a: mcp_tools.record_refresh(
        c, _s(a, "entity_id"), _s(a, "source"), _s(a, "lease_token"), _s(a, "outcome"), a.get("value"),
        a.get("ended"), a.get("quotes"), a.get("captured_at"), a.get("predicate"), a.get("summary"), a.get("via")),
    "cicada_record_profile": lambda c, a: mcp_tools.record_profile(
        c, _s(a, "entity_id"), _s(a, "url"), _s(a, "outcome"), a.get("company"), a.get("position"), a.get("quotes"),
        a.get("summary"), a.get("via")),
    "cicada_record_youtube_list": lambda c, a: mcp_tools.record_youtube_list(c, _s(a, "list"), _s(a, "outcome"),
                                                                             a.get("videos"), a.get("via")),
    "cicada_reading_queue": lambda c, a: mcp_tools.reading_queue(c, a.get("limit")),
    "cicada_record_read": lambda c, a: mcp_tools.record_read(
        c, _s(a, "url"), _s(a, "outcome"), a.get("summary"), a.get("excerpts"), a.get("via"), a.get("note"),
        a.get("title")),
    "cicada_sources": lambda c, a: mcp_tools.sources(c, _s(a, "entity_id")),
    "cicada_write_claim": lambda c, a: mcp_tools.write_claim(
        c, _s(a, "subject"), _s(a, "predicate"), _s(a, "object"), a.get("observer", "agent"), a.get("confidence"),
        a.get("context"), a.get("source_episode"), bool(a.get("force_new_entity", False)), a.get("sources"),
        a.get("evidence"), expected_end=a.get("expected_end")),
    "cicada_retract_claim": lambda c, a: mcp_tools.retract_claim(c, _s(a, "subject"), _s(a, "claim_id"),
                                                                 _s(a, "reason"), a.get("evidence")),
    "cicada_add_source": lambda c, a: mcp_tools.add_source(c, _s(a, "subject"), _s(a, "ref"), a.get("predicate"),
                                                           a.get("access"), a.get("kind"), a.get("entity")),
    "cicada_change_source": lambda c, a: mcp_tools.change_source(
        c, _s(a, "subject"), _s(a, "ref"), a.get("predicate"), _s(a, "action"), a.get("reason"), a.get("new_ref"),
        a.get("new_predicate"), a.get("access"), a.get("entity")),
    "cicada_edit_page": lambda c, a: mcp_tools.edit_page(
        c, _s(a, "subject"), _s(a, "reason"), a.get("edits"), a.get("section"), a.get("text"), a.get("add_aliases"),
        a.get("remove_aliases"), a.get("evidence"), a.get("resolves")),
    "cicada_resolve_inbox": lambda c, a: mcp_tools.resolve_inbox(
        c, _s(a, "id"), a.get("option_key"), a.get("answer"), bool(a.get("defer", False)), a.get("remind_days"),
        skip=bool(a.get("skip", False)), reject=bool(a.get("reject", False)), quote=a.get("quote")),
}
#: Bodies outside `mcp_tools`, run below with what they need.
SPECIAL = frozenset({"cicada_handshake", "cicada_continue", "cicada_pending", "cicada_mark_processed",
                     "cicada_repo_context"})


def tools() -> frozenset[str]:
    """Every tool the door runs: the CLI↔MCP table's tools (`cli_map`), each with a body here."""
    return frozenset(cli_map.by_tool())


def _self_post(backend_url: str, headers: Callable[[], dict]) -> Callable[[str, dict], dict]:
    def post(path: str, payload: dict) -> dict:
        return mcp_tools._loopback_post(f"{backend_url}{path}", payload, headers())
    return post


def context(*, memory_path: Path, bank_name: str | None, caller: Caller, state: SessionState, surface: str,
            device_id: str | None, backend_url: str, headers: Callable[[], dict],
            post: Callable[[str, dict], dict] | None = None) -> mcp_tools.ToolContext:
    """The ToolContext a stdio process on this machine would build for this caller, pinned to one bank."""
    def pinned_headers() -> dict:
        out = dict(headers())
        if bank_name is not None:
            out[bank_binding.HEADER] = quote(bank_name, safe="")
        return out

    return mcp_tools.ToolContext(
        memory_path=lambda: memory_path, session_id=caller.session_id, harness=caller.harness or "unknown",
        project_dir=caller.project_dir, client_name=caller.client_name, client_version=caller.client_version,
        skipped_inbox_ids=state.skipped_inbox_ids, state_hint_sent=state.state_hint_sent,
        post=post or _self_post(backend_url, pinned_headers), headers=pinned_headers, backend_url=backend_url,
        read_surface="cli" if surface == "cli" else "mcp",
        available=cli_map.exposed_tools() if surface == "cli" else None,
        local_files=False, sleep_probe=write_admission.holding, sleep_holding=write_admission.holding,
        device_id=device_id)


@dataclass
class Answer:
    text: str
    code: str | None = None
    data: dict | None = None
    error: str | None = None


def run(tool: str, arguments: dict, *, ctx: mcp_tools.ToolContext, state: SessionState, surface: str, options: dict,
        root: Path, bank_name: str | None) -> Answer:
    """One call. A body's exception is the stdio server's ``Error: …`` reply (``error``), never a 500."""
    if surface not in SURFACES:
        raise DoorError("unknown surface")
    if tool not in tools() or (tool not in DISPATCH and tool not in SPECIAL):
        raise DoorError(f"Unknown tool: {tool}", 404)
    row = cli_map.by_tool()[tool]
    if surface == "cli":
        if row.mcp_only:
            raise DoorError(f"{tool} is not a command-line door ({row.mcp_only}).", 403)
        if not row.exposed:
            raise DoorError(f"{tool} is not in the command line yet; use the MCP tool.", 403)
    memory_path = ctx.memory_path()
    try:
        with _WRITE_LOCK if row.mutates else _nolock():
            reply = _run(tool, dict(arguments or {}), ctx=ctx, state=state, surface=surface, options=options,
                         root=root, memory_path=memory_path, bank_name=bank_name)
    except DoorError:
        raise
    except Exception as exc:  # noqa: BLE001 - the stdio server's own `Error: {e}` reply, to the person's own agent
        return Answer(text="", error=str(exc) or type(exc).__name__)
    state.state_hint_sent = ctx.state_hint_sent
    if isinstance(reply, Answer):
        return reply
    return Answer(text=str(reply), code=getattr(reply, "code", None), data=getattr(reply, "data", None))


class _nolock:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _run(tool, args, *, ctx, state, surface, options, root, memory_path, bank_name):
    if tool in DISPATCH:
        if tool == "cicada_recall_detail" and surface == "cli" and options.get("whole") is not None:
            return mcp_tools.recall_detail(ctx, _s(args, "entity_id"), start=mcp_tools.line_number(args.get("start")),
                                           whole=bool(options.get("whole")))
        return DISPATCH[tool](ctx, args)
    if tool == "cicada_handshake":
        from api.services import handshake

        if surface == "cli":
            from api.services import state_dictionary

            names = frozenset(r.name for r in cli_map.exposed())
            tz = options.get("tz") if isinstance(options.get("tz"), str) else None
            text = handshake.build_cli(state_dictionary.read_state(memory_path), commands=names,
                                       bank=bank_name or memory_path.name, tz=tz)
            handshake.record("cli", {"variant": handshake.CLI_VARIANT}, bank=memory_path.name, harness=ctx.harness)
            return Answer(text=text, data={"tokens_est": len(text) // 4})
        delivery = options.get("delivery") if options.get("delivery") in ("initialize", "tool") else "tool"
        text, meta = handshake.load_or_build(memory_path, ctx.client_name)
        handshake.record(delivery, meta, bank=memory_path.name, harness=ctx.harness,
                         client_name=ctx.client_name or None)
        return text
    if tool == "cicada_continue":
        from api.services import local_tools

        cwd = options.get("cwd") if isinstance(options.get("cwd"), str) else None
        spelling = local_tools.cli_continue_spelling() if surface == "cli" else None
        kwargs = {"spelling": spelling} if spelling is not None else {}
        return local_tools.continue_text(memory_path, root=root, cwd=cwd or ctx.project_dir,
                                         session=args.get("session"), before=args.get("before"),
                                         identity=(ctx.harness, ctx.session_id), **kwargs)
    if tool == "cicada_pending":
        from api.services import agentic_write

        return agentic_write.pending_text(memory_path, args.get("limit"), state.listed_revisions)
    if tool == "cicada_mark_processed":
        from api.services import agentic_write

        return agentic_write.mark_processed_text(memory_path, args.get("episode_ids"), args.get("revisions"),
                                                 state.listed_revisions, ctx.harness)
    if tool == "cicada_repo_context":
        from api.services import repo_context

        entity_id = _s(args, "entity_id").strip()
        if not entity_id or args.get("path"):
            return Answer(text="The repository is on your machine: Cicada reads its git context there, by path.")
        resolved, declared, refusal = repo_context.declared_repos(memory_path, entity_id)
        if refusal is not None:
            return Answer(text=refusal)
        return Answer(text="", data={"entity": resolved, "repos": declared})
    raise DoorError(f"Unknown tool: {tool}", 404)
