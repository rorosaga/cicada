"""The remote tool schemas (G135 R-R22): what a connector's app is told it can call.

Its own table, not the stdio `TOOLS`, because the audiences differ. The stdio
descriptions cross-reference tools a remote connection may not hold
(`cicada_pending` in the evidence schema, `cicada_recall_detail` in recall's),
and G75 R12 makes a description that names an absent tool a bug. Here a
description names another tool only when both share a scope, or when it is
`cicada_handshake` (always present). `test_remote_tools.py` proves that for all
63 non-empty scope sets. Every tool but the handshake takes `conversation`
(R-R24). `cicada_resolve_inbox` has no free-text `answer`, and
`cicada_write_claim`'s observer is `agent | external` (R-R22, R-R23).

The annotations are what ChatGPT's confirmation UX reads. Reads are read-only.
No tool is destructive: nothing deletes or edits in place.
`cicada_retract_claim` closes a claim this connection wrote and keeps it, with
the reason, as history (G140 Q-R5): its validity changes, its words never do.
`cicada_save_url` is open-world, because it may fetch the page's title.
`cicada_record_watch` is open-world for the same reason: a link that is not
saved yet is saved first, through `cicada_save_url`'s own path (G140 Q-R8).
Cicada never fetches the video itself.
"""
from __future__ import annotations

from api.remote import catalog

_CONVERSATION = {"type": "string", "description": "The handle cicada_handshake returned for this conversation."}
_STRING = {"type": "string"}


def _tool(name: str, description: str, properties: dict | None = None, required: tuple[str, ...] = (), *,
          read_only: bool, idempotent: bool = False, open_world: bool = False) -> dict:
    props = {k: dict(v) for k, v in (properties or {}).items()}
    if name != "cicada_handshake":
        props["conversation"] = dict(_CONVERSATION)
    schema: dict = {"type": "object", "properties": props}
    if required:
        schema["required"] = list(required)
    return {
        "name": name,
        "description": description,
        "inputSchema": schema,
        "annotations": {"read_only_hint": read_only, "destructive_hint": False,
                        "idempotent_hint": idempotent or read_only, "open_world_hint": open_world},
    }


REMOTE_TOOLS: dict[str, dict] = {t["name"]: t for t in (
    _tool("cicada_handshake",
          "Start here. Returns this conversation's handle and the contract for what this connection may do. "
          "Call it once at the start of every conversation, then pass the handle as `conversation` on every "
          "other call.", read_only=True),
    _tool("cicada_recall",
          "Search the person's memory for a topic, person, project or idea. Returns short summaries of the best "
          "matches, plus any pending questions about them. State only what the results say.",
          {"query": {"type": "string", "description": "What to look for."}}, ("query",), read_only=True),
    _tool("cicada_open_hub",
          "Open a topic or type index (for example 'people', 'tools' or 'projects') and list its pages with "
          "one-line summaries.",
          {"hub": {"type": "string", "description": "The hub id, for example 'projects'."}}, ("hub",),
          read_only=True),
    _tool("cicada_recall_detail",
          "Return one page of the person's memory in full, by id or by name.",
          {"entity_id": {"type": "string", "description": "The page id or name, for example 'alpha-project'."}},
          ("entity_id",), read_only=True),
    _tool("cicada_get_perspective",
          "Return the facts currently believed about one subject — optionally only one observer's view "
          "('agent', 'owner' or 'external:<name>') or one context (for example 'work'). Each fact says who "
          "holds it and how sure Cicada is.",
          {"subject": {"type": "string", "description": "The subject's id or name."},
           "observer": {"type": "string", "description": "Optional: only this observer's view."},
           "context": {"type": "string", "description": "Optional: only this context."},
           "history": {"type": "boolean", "description": "Optional: also list earlier facts — replaced, withdrawn or ended — newest first."}},
          ("subject",), read_only=True),
    _tool("cicada_check_nudges",
          "List the questions Cicada has for the person — something fading, two facts that disagree, a name "
          "that could be two people. Pass the ids a search returned as `entity_ids` to see only what matters "
          "now.",
          {"topic": {"type": "string", "description": "Optional topic to filter by."},
           "entity_ids": {"type": "array", "items": dict(_STRING),
                          "description": "Optional page ids; only questions about them are listed."}},
          read_only=True),
    _tool("cicada_save_episode",
          "Save a note from this conversation — a decision, a plan, a fact worth keeping — for Cicada's "
          "nightly consolidation. Returns the episode id to cite as evidence.",
          {"content": {"type": "string", "description": "What to keep, in plain words."},
           "title": {"type": "string", "description": "A short title."}},
          ("content",), read_only=False, idempotent=True),
    _tool("cicada_write_claim",
          "Record one fact as subject – predicate – object, marked as coming from this app. Use observer "
          "'agent' when you inferred it and 'external' when someone other than the person said it; a remote "
          "app cannot record the person's own words as theirs. Quote the exact words you relied on in "
          "`evidence`, citing an episode cicada_save_episode returned.",
          {"subject": {"type": "string", "description": "The page the fact is about."},
           "predicate": {"type": "string", "description": "The relation, for example 'uses'."},
           "object": {"type": "string", "description": "The value or the other page."},
           "observer": {"type": "string", "enum": ["agent", "external"],
                        "description": "Who holds this belief. Defaults to 'agent'."},
           "confidence": {"type": "number", "description": "Optional, 0.0–1.0 (default 0.7)."},
           "context": {"type": "string", "description": "Optional facet, for example 'work'."},
           "source_episode": {"type": "string",
                              "description": "Optional episode id this fact came from, for example one "
                                             "cicada_save_episode returned."},
           "force_new_entity": {"type": "boolean",
                                "description": "Only after an 'ambiguous subject' reply, to make a new page."},
           "sources": {"type": "array", "items": dict(_STRING),
                       "description": "Optional places to check this fact (a URL, or plain words)."},
           "evidence": {"type": "array", "description": "Where the fact comes from.",
                        "items": {"type": "object", "required": ["episode", "quote"], "properties": {
                            "episode": {"type": "string",
                                        "description": "The episode id cicada_save_episode returned."},
                            "quote": {"type": "string",
                                      "description": "The exact words, copied verbatim (at most 240 characters)."},
                        }}},
           # G140 Q-R6: the same stated end the stdio server takes.
           "expected_end": {"type": "string",
                            "description": "Optional: the date this fact stops being true, if the person said "
                                           "(YYYY-MM-DD)."}},
          ("subject", "predicate", "object"), read_only=False, idempotent=True),
    _tool("cicada_retract_claim",
          "Withdraw a fact this connection recorded earlier with cicada_write_claim and now knows is wrong. "
          "The fact stays in history with your reason; nothing is deleted. Only facts this connection wrote "
          "can be withdrawn.",
          {"subject": {"type": "string", "description": "The page the fact is on."},
           "claim_id": {"type": "string", "description": "The claim id cicada_write_claim returned."},
           "reason": {"type": "string", "description": "Why it is wrong, in one sentence."},
           "evidence": {"type": "array", "description": "Optional: the person's exact words showing it is wrong.",
                        "items": {"type": "object", "required": ["episode", "quote"], "properties": {
                            "episode": {"type": "string",
                                        "description": "The episode id cicada_save_episode returned."},
                            "quote": {"type": "string",
                                      "description": "The exact words, copied verbatim (at most 240 characters)."},
                        }}}},
          ("subject", "claim_id", "reason"), read_only=False, idempotent=True),
    _tool("cicada_save_url",
          "Save a link — an article, a video, a paper — to the person's memory, with an optional note on why. "
          "Cicada reads the page's title only when the page is on the public internet.",
          {"url": {"type": "string", "description": "The http(s) link."},
           "note": {"type": "string", "description": "Optional: why it matters."}},
          ("url",), read_only=False, idempotent=True, open_world=True),
    _tool("cicada_record_watch",
          "After you watch a video the person saved, record what it covers: a short summary and up to 12 "
          "short quotes with the time each is said. Cicada keeps these quotes as the video's words, never "
          "the whole transcript, and never downloads the video itself. The reply names the episode to cite "
          "in cicada_write_claim.",
          {"url": {"type": "string", "description": "The video's link as saved."},
           "summary": {"type": "string", "description": "What the video covers, one paragraph."},
           "excerpts": {"type": "array", "description": "Optional: up to 12 short quotes with their time.",
                        "items": {"type": "object", "required": ["t", "quote"], "properties": {
                            "t": {"type": "string", "description": "When it is said, e.g. '12:34'."},
                            "quote": {"type": "string", "description": "The words, verbatim (at most 240 characters)."},
                        }}},
           "chapters": {"type": "array", "description": "Optional: the video's chapters.",
                        "items": {"type": "object", "required": ["t", "title"], "properties": {
                            "t": {"type": "string"}, "title": {"type": "string"}}}}},
          ("url", "summary"), read_only=False, idempotent=True, open_world=True),
    _tool("cicada_sources",
          "Return the conversation excerpts a page was built from, word for word (at most three, each cut at "
          "1,000 characters).",
          {"entity_id": {"type": "string", "description": "The page id."}}, ("entity_id",), read_only=True),
    _tool("cicada_timeline",
          "What changed in the person's memory recently, day by day: what was captured, the pages Cicada "
          "created or updated overnight, pages that faded, facts that reached their stated end, and what "
          "agents wrote. Ids and counts only — open a page with cicada_recall_detail.",
          {"since": {"type": "string", "description": "Optional: a date (YYYY-MM-DD) or a number of days "
                                                      "back. Default 7, at most 90."}},
          read_only=True),
    _tool("cicada_project",
          "Where one of the person's projects stands: what is under way, what is next, what went quiet, what "
          "happened (dated, from whose words), and the people, tools, documents and sub-projects around it. "
          "Read-only. Use when the person asks how a project is going, what happened on it, or what's next.",
          {"project": {"type": "string", "description": "A project's id or name."},
           "since": {"type": "string", "description": "Optional: YYYY-MM-DD, or a number of days back. Default 90."},
           "tz": {"type": "string", "description": "Optional: the person's IANA timezone, for relative dates."}},
          ("project",), read_only=True),
    # G141 §5.2: the same schema the stdio server declares; observer is always
    # this app (never the person), so the schema carries no observer at all.
    _tool("cicada_note_progress",
          "Record something that happened in one of the person's projects, something under way, or a milestone "
          "they planned — dated, with who and what took part. Quote the person's words in evidence. For a "
          "standing fact (a spec, who works where) use cicada_write_claim instead.",
          {"project": {"type": "string", "description": "The project page (id or name). Use the person's own "
                                                        "page for something outside any project."},
           "kind": {"type": "string", "enum": ["happened", "milestone"]},
           "summary": {"type": "string", "description": "One sentence, third person, naming each participant "
                                                        "exactly as the person did. No relative time words."},
           "status": {"type": "string", "enum": ["ongoing", "done", "dropped", "planned", "missed"]},
           "when": {"type": "string", "description": "Optional: YYYY-MM-DD, or the person's own words "
                                                     "('yesterday'), resolved against the cited episode."},
           "target": {"type": "string", "description": "Milestone only: the planned date, YYYY-MM-DD."},
           "milestone": {"type": "string", "description": "Milestone only: an existing milestone's name or slug, "
                                                          "to move it or mark it done."},
           "settles": {"type": "string", "description": "Optional: the claim id of an ongoing item this finishes "
                                                        "or stops."},
           "participants": {"type": "array", "items": {"type": "object", "required": ["name", "role"], "properties": {
               "name": {"type": "string"},
               "role": {"type": "string", "enum": ["owner", "from", "with", "for", "about", "used", "document",
                                                   "project"]},
               "url": {"type": "string"}}}},
           "evidence": {"type": "array", "items": {"type": "object", "required": ["episode", "quote"], "properties": {
               "episode": {"type": "string"}, "quote": {"type": "string"}}}}},
          ("project", "kind", "summary", "status"), read_only=False),
    _tool("cicada_resolve_inbox",
          "Record the person's own answer to one of Cicada's questions: the option_key they chose, defer=true "
          "to ask again later, reject=true when two names are NOT the same, or skip=true when they did not "
          "answer (nothing is written). Only with an answer the person actually gave.",
          {"id": {"type": "string", "description": "The question id, for example 'inbox-001'."},
           "option_key": {"type": "string", "description": "The key of the option the person chose."},
           "defer": {"type": "boolean", "description": "Ask again later."},
           "remind_days": {"type": "integer", "description": "With defer: days until asked again."},
           "skip": {"type": "boolean", "description": "Unanswered: nothing is written."},
           "reject": {"type": "boolean", "description": "For a possible duplicate: they are different."}},
          ("id",), read_only=False),
    _tool("cicada_ask",
          "Ask Cicada a direct question about the person. It answers from memory with citations and says what "
          "it doesn't know. It uses the person's own AI plan, so it is limited each day.",
          {"query": {"type": "string", "description": "The question."},
           "top_k": {"type": "integer", "description": "How many pages to read (default 6)."}},
          ("query",), read_only=True),
)}


def tool_defs_for(scopes) -> list[dict]:
    names = catalog.tool_names_for(scopes)
    return [definition for name, definition in REMOTE_TOOLS.items() if name in names]
