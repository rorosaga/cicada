"""Direct saved-content API connectors (G71 §2).

G69's route matrix names exactly two platforms that expose a *personal saved
index* through a sanctioned API: Pinterest v5 and Reddit. X (Twitter)
bookmarks joined as a third (Task 14). Everything else in Cicada's import
story is an export-file parser living in ``media_ingestor`` — aggregators
were evaluated and rejected (they cannot reach these surfaces, and every
hosted one proxies tokens through its own cloud).

House rules, meant to hold for every adapter added to this package:

* credentials live ONLY in ``$CICADA_HOME/secrets.env`` (0600) via
  ``connections.secrets`` — never in a bank, never in git, never in a log line,
  an error string, or an HTTP response;
* every HTTP call goes through an injected ``http_fn``, so the test suite has
  zero network and the default transport is the only code path that does;
* the default transport, for an UNATTENDED background call only (the
  Sleep-tail poll), is additionally gated on ``CICADA_ALLOW_CONNECTOR_FETCH`` —
  opt-OUT, mirroring ``CICADA_ALLOW_LOGO_FETCH`` (on by default, ``=off``
  disables it). A user-initiated call — ``sync_now``, or an OAuth adapter's
  ``authorize_url``/``exchange_code`` — is never gated by it (final-review H2:
  the gate exists to stop an unattended poll from reaching an unconfigured
  install's network, not to block a user who just clicked something);
* ``sync()`` never raises: a failure is recorded through
  ``sync_state.record_error`` and surfaces per-channel on ``GET /sources/channels``;
  a background poll the gate skipped is likewise recorded, through
  ``sync_state.record_skip`` — never silently, and never as an error;
* nothing new is invented downstream — a connector emits ``RawItem``s into
  ``media_ingestor.ingest_batch`` and the Sleep pipeline absorbs them unchanged.

``ADAPTERS`` (Task 15 §1) is the single roster every consumer of "which
connectors exist" iterates, rather than re-declaring the same three-item list
(the audit found five separate declarations: two dicts in the router, a tuple
in the Sleep poll, a dict literal in ``sources.py``, and the noun/order table
in ``channel_registry.py``). Every module in ``ADAPTERS`` MUST expose:

    CHANNEL_ID: str              the dict key it is registered under
    LABEL: str                   human-readable name for the setup panel
    FIELDS: tuple[dict, ...]     credential fields the setup panel collects
    LOGIN_MODE: str              "oauth" | "credentials"
    CHANNEL_NOUN: str            the unit the Capture page row counts
                                 ("pin", "saved item", "bookmark")
    SECRET_NAMES: tuple[str, ...]  every secrets.env key this adapter can
                                 ever write — FIELDS' names plus any derived
                                 token (an access/refresh token, a resolved
                                 user id) — the surface ``forget()`` sweeps
    is_connected() -> bool
    credential_fields() -> list[dict]
    forget() -> None
    async def sync(memory_path, *, http_fn=None, allow_fetch=None) -> dict
                                 NEVER raises.

An OAuth adapter (``LOGIN_MODE == "oauth"``) additionally exposes:

    authorize_url(state, *, base_url) -> str
    async def exchange_code(code, *, state="", http_fn=None, base_url) -> None

A PKCE adapter (X today) keeps its ``code_verifier`` entirely internal,
minted in ``authorize_url`` and consumed in ``exchange_code``, both keyed by
``state`` — the router never sees or stores it.
"""

from __future__ import annotations

from types import ModuleType

from api.services.connectors import pinterest, reddit, x

ADAPTERS: dict[str, ModuleType] = {
    pinterest.CHANNEL_ID: pinterest,
    reddit.CHANNEL_ID: reddit,
    x.CHANNEL_ID: x,
}
