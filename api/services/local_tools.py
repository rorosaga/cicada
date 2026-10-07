"""Tool bodies that only a local caller may run: the stdio MCP server and the `cicada` command (G110, G180).

Deliberately apart from ``mcp_tools`` — the module the remote connector serves — so the remote
package cannot even import what is here (G135 R-R3; ``catalog.NEVER_REMOTE``; a test refuses any
``api/remote`` import of this module). One body per tool, two thin doors.
"""
from __future__ import annotations

from pathlib import Path

from api.services import continuity, continuity_sessions
from api.services.mcp_tools import Reply


def continue_text(memory_path: Path, *, root: Path, cwd: str | None, identity: tuple[str | None, str | None],
                  session: str | None = None, before: str | None = None,
                  spelling: continuity.Spelling = continuity.MCP) -> Reply:
    """`cicada_continue` / `cicada continue` (G110 slice 1a): where the work in this folder stopped.

    The bank is resolved ONCE by the caller and this path is passed through selection, the parse and
    the rendering (the split-brain rule). ``cwd`` is matched as an exact string. ``identity`` is the
    caller's own ``(harness, session_id)``, either part possibly unknown, and it is REQUIRED: a
    no-argument read always enters #229's current-conversation rules — an exact identity match, else
    the newest session's recorded lineage and chronology — so no door can switch them off (G180
    review). An unknown part never matches a captured session, and nothing is minted or stored for
    it. Explicit episode reads keep their ordinary history/paging behaviour."""
    session = session.strip() if isinstance(session, str) and session.strip() else None
    before = before.strip() if isinstance(before, str) and before.strip() else None
    bank_paths = continuity_sessions.bank_paths_for(root)
    ctx = continuity.assemble(memory_path, bank_paths=bank_paths, harness=None, session_id=None, cwd=cwd,
                              session=session, deadline=None, allow_full_parse=continuity.TOOL_UNREADABLE_PARSES,
                              continue_identity=(identity[0] or "unknown", identity[1] or ""))
    text = continuity.full_text(ctx, before=before, spelling=spelling)
    chosen = ctx.chosen.episode_id if ctx.chosen is not None else None
    return Reply(text, data={"episode_id": chosen, "selection": ctx.selection.kind, "complete": bool(ctx.complete)})
