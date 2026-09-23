"""A demo bank is synthetic, and capture never writes a real conversation into it.

G117's demo bank (``demo_bank.populate``, ``POST /banks/demo``) exists so a new
person — and the README's screenshots (G90) — can try Cicada on made-up people
and projects. Every capture writer writes into the ACTIVE bank, so on
2026-09-23, while the demo was open for screenshots, a real Claude Code
session's Stop hook wrote that session INTO the demo bank and its words reached
demo content. The file was quarantined by hand; this module is the rule that
makes it impossible (G141 capture-side track, R-CS10..R-CS17).

One question, answered from the bank directory alone, so any writer that holds
only a bank path — the stdio MCP server, the Telegram webhook, a folder sync —
can ask it with one small read:

* ``<bank>/_bank.yaml`` saying ``kind: demo`` — written FIRST by
  ``demo_bank.populate`` and committed in the bank, so it travels with a
  duplicate, a rename, an export or a hand copy (R-CS10);
* for a demo bank generated before that file existed, the generator's own
  commit identity (:data:`GENERATOR_EMAIL`) in ``<bank>/.git/config`` — what
  ``demo_bank._commit_history`` has written since G117 — so an existing demo
  bank is recognised with no migration and no write.

Never the bank's NAME: a person may call a real bank "demo". Pure — pathlib,
re and yaml; ``bank_registry`` imports this module, never the reverse. A
malformed manifest reads as "not demo": a hand-made file must never block a
real bank's capture, and the git identity still catches every generated demo.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

MANIFEST = "_bank.yaml"
DEMO_KIND = "demo"
#: The demo generator's commit identity — its one trace in a bank made before
#: the manifest. `demo_bank._commit_history` spells it through this constant.
GENERATOR_EMAIL = "demo@cicada.example"
_GENERATOR_EMAIL_RE = re.compile(r"^\s*email\s*=\s*" + re.escape(GENERATOR_EMAIL) + r"\s*$", re.MULTILINE)

#: The 409 detail every HTTP capture route answers with (R-CS15), shown as-is in
#: the app's panels — so it is written for the person.
REFUSAL = ("Cicada has its demo memory open. It only holds made-up examples, so nothing real is saved "
           "into it. Switch back to your own memory, then try again.")
#: What an MCP write tool answers (R-CS13) — an agent relays it, so it says
#: what to tell the person.
AGENT_REFUSAL = ("Not saved: Cicada has its demo memory open, and the demo only holds made-up examples. "
                 "Tell the person to switch back to their own memory in Cicada, then save this again.")
#: Telegram's chat reply (R-CS14).
TELEGRAM_ACK = "Not saved — Cicada has its demo memory open. Switch back to your own memory and send it again."
#: The Stop hook's 409 when no real bank can be chosen (R-CS12). The hook logs it.
HOOK_REFUSAL = ("The demo memory is open and Cicada couldn't tell which of your own memories to save this "
                "session into, so nothing was saved. Switch back to your memory in Cicada — the next reply "
                "saves the whole session.")

_MANIFEST_TEXT = (
    "# Written by Cicada's demo generator (api/services/demo_bank.py). This bank holds only\n"
    "# made-up examples, so every capture writer refuses it (api/services/demo_guard.py).\n"
    f"kind: {DEMO_KIND}\n"
)


def manifest_path(bank_path: Path) -> Path:
    return Path(bank_path) / MANIFEST


def write_manifest(bank_path: Path) -> Path:
    """Mark ``bank_path`` as a demo bank. Only ``demo_bank.populate`` calls it."""
    path = manifest_path(bank_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_MANIFEST_TEXT, encoding="utf-8")
    return path


def is_demo(bank_path: Path | None) -> bool:
    """True when ``bank_path`` is a demo bank (R-CS10). Never raises."""
    if bank_path is None:
        return False
    bank = Path(bank_path)
    try:
        data = yaml.safe_load(manifest_path(bank).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        data = None
    if isinstance(data, dict) and data.get("kind") == DEMO_KIND:
        return True
    try:
        config = (bank / ".git" / "config").read_text(encoding="utf-8", errors="replace")
    except OSError:  # no git, or `.git` is a worktree/submodule file — not a generated demo
        return False
    return bool(_GENERATOR_EMAIL_RE.search(config))
