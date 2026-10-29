"""Every non-GET route, classified for a replica (G132 phase 1 B, ruling 51a/e2). Hand-written, never a catch-all.

On a computer that keeps a copy, this computer's backend answers the app. A request that changes something is one of:

* ``forward`` — it changes the memory (or a store the home keeps): sent to the SAME route at the home, keyed once,
  naming the home's bank id; the home's answer comes back as it is. Home unreachable: 503 ``home_away``, nothing
  changed (an interactive write the person retries).
* ``capture`` — something to remember (a note, a file, a reader's posts): forwarded the same way, and when the home is
  unreachable it waits in this computer's outbox and the answer is 202 ``queued`` (capture never blocks on the
  network).
* ``refuse`` — an act that belongs to the home itself or that a copy must never do (bank lifecycle, devices, the
  remote listener, publishing, maintenance runs): 409 ``replica_read_only`` with a sentence.
* ``local`` — it writes only this computer's own state outside every bank (its engine sign-ins, its search model, its
  skills folders, its sealed activity traces, a read computed here): run here. The backstop (``replica_guard``)
  still refuses a bank write from any of them.

``test_replica_routes_inventory.py`` fails on a route missing here, on a stale entry, and on a class that is not one
of the four.
"""
from __future__ import annotations

FORWARD = "forward"
CAPTURE = "capture"
REFUSE = "refuse"
LOCAL = "local"
CLASSES = frozenset({FORWARD, CAPTURE, REFUSE, LOCAL})

ROUTES: dict[str, str] = {
    # --- the agent API, devices, the remote listener, publishing: the home's own -----------------------------------
    "DELETE /agent-api/tokens/{token_id}": REFUSE,
    "POST /agent-api/tokens": REFUSE,
    "DELETE /devices/pairing/{pairing_id}": REFUSE,
    "DELETE /devices/{device_id}": REFUSE,
    "POST /devices": REFUSE,
    "POST /devices/me/key": REFUSE,
    "POST /devices/pairing": REFUSE,
    "POST /devices/reach/serve": REFUSE,
    "POST /pair": REFUSE,
    "DELETE /remote/connectors/{connector_id}": REFUSE,
    "POST /remote/connectors": REFUSE,
    "POST /remote/connectors/{connector_id}/rotate": REFUSE,
    "POST /remote/oauth/approve": REFUSE,
    "POST /remote/oauth/match": REFUSE,
    "POST /remote/oauth/requests/deny-all": REFUSE,
    "POST /remote/oauth/requests/{ref}/deny": REFUSE,
    "PUT /remote/settings": REFUSE,
    "POST /v1/{op}": REFUSE,
    "PUT /sync/publish": REFUSE,
    "POST /sync/publish/from-here": REFUSE,
    # This computer's own copy: set up, stop, copy again — the person's acts here.
    "PUT /sync/replica": LOCAL,
    "DELETE /sync/replica": LOCAL,
    "POST /sync/replica/recopy": LOCAL,
    "POST /sync/replica/restart": LOCAL,
    # --- bank lifecycle: a copy holds one memory and never makes, renames or imports another --------------------------
    "DELETE /banks/{name}": REFUSE,
    "POST /banks": REFUSE,
    "POST /banks/demo": REFUSE,
    "POST /banks/leave-demo": REFUSE,
    "POST /banks/{name}/activate": REFUSE,
    "POST /banks/{name}/duplicate": REFUSE,
    "POST /banks/{name}/import": REFUSE,
    "POST /banks/{name}/rename": REFUSE,
    # --- maintenance runs belong to the home (they rewrite many pages) ------------------------------------------------
    "POST /maintenance/dedup-sweep": REFUSE,
    "POST /maintenance/enrich-links": REFUSE,
    "POST /maintenance/link-sources": REFUSE,
    "POST /maintenance/verify-sites": REFUSE,
    "POST /maintenance/watched-rows": REFUSE,
    "POST /maintenance/search-index/rebuild": LOCAL,      # the copy's own derived words index
    # --- this computer's engine sign-ins, search model, skills folders and settings outside every bank --------------
    "DELETE /connections/{connection_id}/key": LOCAL,
    "POST /connections/{connection_id}/login": LOCAL,
    "POST /connections/{connection_id}/logout": LOCAL,
    "PUT /connections/{connection_id}/key": LOCAL,
    "PUT /connections/{connection_id}/prefs": LOCAL,
    "POST /embeddings/choice": LOCAL,
    "POST /embeddings/install": LOCAL,
    "DELETE /skills/drafts/{name}": LOCAL,
    "DELETE /skills/{name}": LOCAL,
    "POST /skills/check": LOCAL,
    "POST /skills/drafts/{name}/publish": LOCAL,
    "POST /skills/install": LOCAL,
    "POST /skills/onboarding": LOCAL,
    "POST /skills/preview": LOCAL,
    "POST /skills/requests/{request_id}/dismiss": LOCAL,
    "POST /skills/update-all": LOCAL,
    "POST /skills/{name}/refresh": LOCAL,
    "POST /skills/{name}/update": LOCAL,
    "PUT /skills/kinds": LOCAL,
    "PUT /skills/{name}/agents/{agent}": LOCAL,
    "PUT /settings/editors": LOCAL,
    "POST /agent-requests": LOCAL,                        # per device, labelled with the device (coordinator call 6)
    # --- reads computed here (an answer, a preview, a search) — they write nothing -------------------------------------
    "POST /ask": LOCAL,
    "POST /intake/sniff": LOCAL,
    "POST /design/search": LOCAL,
    "POST /inbox/catchup/turn": LOCAL,
    "POST /sources/linkedin-connections/preview": LOCAL,
    "POST /sources/messages/conversations": LOCAL,
    "POST /sources/whatsapp/conversations": LOCAL,
    "POST /sources/saved-why/suggest": LOCAL,
    "POST /sources/sync-bookmarks/fresh": LOCAL,
    "POST /sources/traces/search": LOCAL,
    "POST /conversations/{conversation_id}/resume": LOCAL,
    "POST /entities/{entity_id}/read": LOCAL,             # this viewer's "read" mark, outside every bank
    "POST /entities/{entity_id}/repos/observed": LOCAL,   # this computer's own repositories, a cache outside banks
    "PUT /sources/messages/photos": LOCAL,                # ticked chats' photos read here, kept outside every bank
    "POST /capture/hook-context": LOCAL,                  # this computer's continuity index ($CICADA_HOME)
    # --- the sealed activity traces live on the computer that captured them (ruling 38) -------------------------------
    "POST /sources/traces/delete": LOCAL,
    "POST /sources/traces/forget": LOCAL,
    "POST /sources/traces/frames": LOCAL,
    "POST /sources/traces/off": LOCAL,
    "POST /sources/traces/on": LOCAL,
    "POST /sources/traces/pause": LOCAL,
    "POST /sources/traces/wipe": LOCAL,
    "PUT /sources/traces/settings": LOCAL,
    # --- capture: queued here while the home is away --------------------------------------------------------------------
    "POST /capture/agent-memory": CAPTURE,
    "POST /capture/file": CAPTURE,
    "POST /capture/local-source/wispr-flow": CAPTURE,
    "POST /capture/note": CAPTURE,
    "POST /capture/session": CAPTURE,
    "POST /capture/telegram": CAPTURE,
    "POST /capture/turn": CAPTURE,
    "POST /capture/transcript": REFUSE,   # names a file on this computer; the hooks send the session itself instead
    "POST /sources/save": CAPTURE,
    "POST /sources/upload": CAPTURE,
    "POST /sources/calendar-local/sync": CAPTURE,
    "POST /sources/contacts-local/sync": CAPTURE,
    "POST /sources/folders/{folder_id}/sync": CAPTURE,
    "POST /sources/messages/sync": CAPTURE,
    "POST /sources/reminders-local/sync": CAPTURE,
    "POST /sources/sync-bookmarks": CAPTURE,
    "POST /sources/sync-notes": CAPTURE,
    "POST /sources/sync-safari-tabs": CAPTURE,
    "POST /sources/tab-groups/sync": CAPTURE,
    "POST /sources/traces/sync": CAPTURE,
    "POST /sources/watch-history/sync": CAPTURE,
    "POST /sources/whatsapp/sync": CAPTURE,
    "POST /files/media": CAPTURE,
    "POST /files/{file_id}/frames": CAPTURE,
    # --- everything else changes the memory or a store the home keeps: forwarded ----------------------------------------
    "DELETE /design/{ref_id}": FORWARD,
    "DELETE /entities/{entity_id}/coordinates": FORWARD,
    "DELETE /entities/{entity_id}/picture": FORWARD,
    "DELETE /entities/{entity_id}/sources/{index}": FORWARD,
    "DELETE /files/{file_id}": FORWARD,
    "DELETE /reading/asks/{url_hash}": FORWARD,
    "DELETE /sources/calendars": FORWARD,
    "DELETE /sources/connectors/{connector_id}/credentials": REFUSE,   # the home's sign-ins
    "DELETE /sources/contacts-local/waiting": FORWARD,
    "DELETE /sources/feeds": FORWARD,
    "DELETE /sources/folders/{folder_id}": FORWARD,
    "DELETE /sources/linkedin-connections": FORWARD,
    "DELETE /videos/queue/{key}": FORWARD,
    "PATCH /backlog/{project_id}/{item_id}": FORWARD,
    "PATCH /design/{ref_id}": FORWARD,
    "PATCH /entities/{entity_id}/repos": FORWARD,
    "PATCH /projects/{project_id}": FORWARD,
    "PATCH /projects/{project_id}/milestones/{slug}": FORWARD,
    "POST /agent-methods/skills/{skill}/page": FORWARD,
    "POST /backlog/{project_id}/{item_id}/notes": FORWARD,
    "POST /clarifications/{clarification_id}": FORWARD,
    "POST /conversations/upload": FORWARD,
    "POST /design": FORWARD,
    "POST /entities/{entity_id}/edits": FORWARD,
    "POST /entities/{entity_id}/history/{commit_hash}/undo": FORWARD,
    "POST /entities/{entity_id}/merge": FORWARD,
    "POST /entities/{entity_id}/picture": FORWARD,
    "POST /entities/{entity_id}/picture/initials": FORWARD,
    "POST /entities/{entity_id}/picture/pdf": FORWARD,
    "POST /entities/{entity_id}/sources": FORWARD,
    "POST /entities/{entity_id}/sources/change": FORWARD,
    "POST /entities/{entity_id}/sources/refresh": FORWARD,
    "POST /entities/{entity_id}/split": FORWARD,
    "POST /entities/{entity_id}/web-context": FORWARD,
    "POST /explore/batches": FORWARD,
    "POST /explore/look": FORWARD,
    "POST /explore/queue/{key}/retry": FORWARD,
    "POST /explore/stop": FORWARD,
    "POST /inbox/catchup/record": FORWARD,
    "POST /inbox/settled/{item_id}/undo": FORWARD,
    "POST /inbox/tidy": FORWARD,
    "POST /inbox/tidy/apply": FORWARD,
    "POST /inbox/web-check": FORWARD,
    "POST /inbox/{item_id}/resolve": FORWARD,
    "POST /intake/import": FORWARD,
    "POST /nudges/{nudge_id}/resolve": FORWARD,
    "POST /projects": FORWARD,
    "POST /projects/{project_id}/accept": FORWARD,
    "POST /projects/{project_id}/backlog": FORWARD,
    "POST /projects/{project_id}/backlog/import": FORWARD,
    "POST /projects/{project_id}/conversations": FORWARD,
    "POST /projects/{project_id}/dismiss": FORWARD,
    "POST /projects/{project_id}/happenings": FORWARD,
    "POST /projects/{project_id}/influences": FORWARD,
    "POST /projects/{project_id}/influences/withdraw": FORWARD,
    "POST /projects/{project_id}/milestones": FORWARD,
    "POST /projects/{project_id}/pages": FORWARD,
    "POST /projects/{project_id}/threads/{claim_id}": FORWARD,
    "POST /projects/{project_id}/withdraw": FORWARD,
    "POST /reading/asks": FORWARD,
    "PUT /reading/settings": FORWARD,
    # Sleep runs only on the home (ruling 4 untouched): "Sleep now" and its controls are the home's.
    "POST /sleep/cancel": FORWARD,
    "POST /sleep/engine/models/refresh": FORWARD,
    "POST /sleep/parked/retry": FORWARD,
    "POST /sleep/run/end": FORWARD,
    "POST /sleep/trigger": FORWARD,
    "PUT /sleep/engine": FORWARD,
    "PUT /sleep/run-options": FORWARD,
    "PUT /sleep/schedule": FORWARD,
    "POST /sources/bookmarks/remove": FORWARD,
    "POST /sources/calendars": FORWARD,
    "POST /sources/connectors/{connector_id}/authorize": REFUSE,   # the home's sign-ins
    "POST /sources/connectors/{connector_id}/sync": FORWARD,
    "POST /sources/feeds": FORWARD,
    "POST /sources/folders": FORWARD,
    "POST /sources/linkedin-connections/import": FORWARD,
    "POST /sources/poll-calendars": FORWARD,
    "POST /sources/poll-feeds": FORWARD,
    "POST /sources/rss": FORWARD,
    "POST /sources/saved-why": FORWARD,
    "POST /sources/telegram/code": REFUSE,          # Telegram's session lives on the home (ruling 47a)
    "POST /sources/telegram/connect": REFUSE,
    "POST /sources/telegram/disconnect": REFUSE,
    "POST /sources/telegram/password": REFUSE,
    "POST /sources/telegram/qr": REFUSE,
    "POST /sources/traces/remove-from-memory": FORWARD,
    "POST /sources/traces/remove-from-memory/undo": FORWARD,
    "POST /tools/call": LOCAL,                       # the tool door itself sends writes to the home (cli_map)
    "POST /videos/queue/{key}/retry": FORWARD,
    "POST /videos/run/handoff": FORWARD,
    "PUT /agent-methods": FORWARD,
    "PUT /capture/agent-memory/settings": FORWARD,
    "PUT /capture/local-source/wispr-flow/settings": FORWARD,
    "PUT /design/{ref_id}/entity": FORWARD,
    "PUT /entities/{entity_id}/coordinates": FORWARD,
    "PUT /entities/{entity_id}/decay": FORWARD,
    "PUT /memory/decay-tuning": FORWARD,
    "PUT /settings/owner": FORWARD,
    "PUT /sources/connectors/{connector_id}/credentials": REFUSE,   # never sent across: the home's sign-ins
    "PUT /sources/folders/{folder_id}": FORWARD,
    "PUT /sources/messages/settings": FORWARD,
    "PUT /sources/saved-why": FORWARD,
    "PUT /sources/telegram/settings": FORWARD,
    "PUT /sources/whatsapp/settings": FORWARD,
    "PUT /videos/queue/{key}": FORWARD,
}

#: GETs a replica answers from the home (Sleep's own status — §3a: the home's run, not this copy's idle one).
GET_FROM_HOME = frozenset({"GET /sleep/status"})


def classify(method: str, path_template: str) -> str | None:
    return ROUTES.get(f"{method.upper()} {path_template}")
