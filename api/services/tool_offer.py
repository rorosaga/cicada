"""Which tools a stdio client is offered before it needs them (G148): the heavy tools that only record a job's result.

Seven tools only record what a job found (a read page, a saved list, a capture, a re-check), and they are about 30% of
the tool list. A job always starts from a tool that stays listed (``cicada_reading_queue``, ``cicada_check_nudges``,
``cicada_explore_claim``, ``cicada_refresh_claim``), and that tool's reply names the one to record with. So a recording
tool joins the list the moment Cicada's own words name it, and the client is told with
``notifications/tools/list_changed``. The list only grows during a session.

Only a client known to re-read the list is treated this way (:data:`REFRESHING_CLIENTS`). Any other client, an unknown
or unnamed one included, holds every tool from the start, so this fails open: nothing changes for it. A held-back tool
called by name still runs. Pure: no bank, no I/O.
"""
from __future__ import annotations

import re

#: ``clientInfo.name``, normalised as ``handshake.variant_for`` does, of clients that re-read ``tools/list`` on the
#: notification. Claude Code by test (2.1.319, also with ``-p``), VS Code and Gemini CLI by their source. Left out: Codex
#: (behind ``mcp_tool_list_changed``, off by default at 0.165), Claude desktop (no handler found in its bundle), Cursor
#: and OpenCode (handlers seen, the refresh not tested; each joins here once a test shows it).
REFRESHING_CLIENTS = frozenset({"claude-code", "visual-studio-code", "gemini-cli-mcp-client"})

OPENED_BY_A_REPLY = frozenset({
    "cicada_record_read", "cicada_record_check", "cicada_record_youtube_list", "cicada_record_saved_list",
    "cicada_record_substack_list", "cicada_record_refresh", "cicada_record_capture",
})

_TOOL_NAME = re.compile(r"cicada_[a-z_]+")


def refreshes(client_name: str | None) -> bool:
    """Whether this client re-reads the tool list when told, by exact name."""
    return re.sub(r"[\s_]+", "-", (client_name or "").strip().lower()) in REFRESHING_CLIENTS


def named_in(text: str) -> set[str]:
    """The tools in :data:`OPENED_BY_A_REPLY` that ``text`` names."""
    return set(_TOOL_NAME.findall(text)) & OPENED_BY_A_REPLY
