"""The one line that installs each plan's command-line tool, and the sentences that name it.

A stranger's Mac has no Node, so ``npm i -g`` was a dead end (QA 2026-11-06). Both vendors ship a standalone
installer that needs nothing else and puts the tool in ``~/.local/bin`` — a folder ``base._CLI_FALLBACK_DIRS``
already looks in, so the backend finds the tool without a restart. Lines read from each vendor's own docs on
2026-11-06 (Claude Code's setup page; the Codex README's Quickstart). Every surface — the connection rows, the
engine cards, a Sleep pre-flight, an engine error — reads these constants and nothing else, so the app and the
engines never disagree; a changed line is changed here.
"""
from __future__ import annotations

CLAUDE_INSTALL_COMMAND = "curl -fsSL https://claude.ai/install.sh | bash"
CODEX_INSTALL_COMMAND = "curl -fsSL https://chatgpt.com/codex/install.sh | sh"

#: What a row says when the tool is missing (the app draws ``*_INSTALL_COMMAND`` apart, in a copyable box).
CLAUDE_MISSING = "Claude Code is not installed on this Mac."
CODEX_MISSING = "Codex is not installed on this Mac."

#: The whole fix in one sentence, for the places that draw no command of their own (the CLI, a Sleep pre-flight,
#: an engine error).
CLAUDE_INSTALL_SENTENCE = (
    f"{CLAUDE_MISSING} Run `{CLAUDE_INSTALL_COMMAND}` in Terminal, then run `claude` once to sign in."
)
CODEX_INSTALL_SENTENCE = (
    f"{CODEX_MISSING} Run `{CODEX_INSTALL_COMMAND}` in Terminal, then sign in with ChatGPT on "
    "Settings → Intelligence → Plans & keys."
)
