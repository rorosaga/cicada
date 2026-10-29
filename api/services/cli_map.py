"""The `cicada` command's names, as one table (G180, TODO ruling 21).

Every stdio MCP tool has exactly one row here: either a short grouped CLI command
(`cicada recall`, `cicada claim add`) with each schema property mapped exactly once to
a positional or a flag, or an MCP-only row. The CLI parser, `cicada --help` and
`cicada commands` are generated from this table, and `test_cli_map.py` checks it
against the stdio `TOOLS` schema (names, properties, requiredness, types), so the two
doors cannot drift apart: R12 by construction. A row the CLI does not expose yet
(`exposed=False`) is the proposed spelling; the slice that ships it confirms it.

Options that are not MCP properties (`get --from`) are `Option`s, catalogued apart from
the mapped `Arg`s so "each property exactly once" stays meaningful. There is no row
that takes a tool name: no generic dispatcher door.
"""
from __future__ import annotations

from dataclasses import dataclass

#: What a CLI argument parses to. `json`: one JSON value; `list`: a repeatable flag or
#: a positional taking one or more values; `pairs`: a repeatable `KEY=VALUE` flag that
#: becomes an object.
KINDS = ("str", "int", "float", "bool", "json", "list", "pairs")


@dataclass(frozen=True)
class Arg:
    """One MCP schema property, as the CLI spells it."""

    prop: str
    kind: str = "str"
    positional: bool = False
    #: The flag's own name when it is not ``--<prop with _ → ->`` (e.g. a repeatable
    #: ``--entity-id`` for the ``entity_ids`` array).
    flag_name: str | None = None

    @property
    def flag(self) -> str:
        return "--" + (self.flag_name or self.prop.replace("_", "-"))


@dataclass(frozen=True)
class Option:
    """A CLI-only option that maps to no MCP property."""

    flag: str
    kind: str
    help: str


@dataclass(frozen=True)
class Row:
    command: tuple[str, ...]
    tool: str | None
    summary: str
    args: tuple[Arg, ...] = ()
    options: tuple[Option, ...] = ()
    mutates: bool = False
    exposed: bool = False
    #: Set for a tool the CLI will never carry; the reason is shown in `cicada commands`.
    mcp_only: str | None = None
    #: Where the command runs: ``bank`` — in this process over the pinned bank (ruling 21); ``backend`` — through
    #: the running backend's HTTP API, because it acts on state the backend owns (`api/cli_app.py`); ``both`` —
    #: `import`, whose platform-export branch runs here and whose chat-export branch goes to the backend.
    via: str = "bank"
    #: Acts as the person (recorded as `Cicada-Author: user`, spends on their engine, or downloads on their
    #: command): refused from a shell that names an agent's session. A row that only reads unless given a flag
    #: refuses only when it would write.
    person: bool = False
    #: One of the app's commands (G180 parity): listed by `cicada commands`, kept out of the agent skill's table.
    app: bool = False
    #: The `/v1` operation's name when it is not the command spelled with underscores (G213, ruling 38): only the
    #: eleven operations shipped before `/v1` was generated from this table, frozen as they were (Hyrum).
    api_op: str | None = None

    @property
    def name(self) -> str:
        return " ".join(self.command)

    @property
    def operation(self) -> str:
        """This tool's `/v1` operation (`POST /v1/<operation>`) — served only when the tool is remote
        (`api/remote/agent_api.OPS`): ``source add`` → ``source_add``, ``inbox record-check`` →
        ``inbox_record_check``."""
        return self.api_op or "_".join(self.command).replace("-", "_")


def _p(prop: str, kind: str = "str") -> Arg:
    return Arg(prop, kind, positional=True)


def _f(prop: str, kind: str = "str", flag_name: str | None = None) -> Arg:
    return Arg(prop, kind, flag_name=flag_name)


def _app(command: tuple[str, ...], summary: str, args: tuple[Arg, ...] = (), *, via: str = "bank",
         mutates: bool = False, person: bool = False, options: tuple[Option, ...] = ()) -> Row:
    """One of the app's commands: CLI-only (no MCP tool), exposed."""
    return Row(command, None, summary, args, options=options, mutates=mutates, exposed=True, via=via,
               person=person, app=True)


ROWS: tuple[Row, ...] = (
    # --- slice 1 (exposed) --------------------------------------------------------------
    Row(("recall",), "cicada_recall", "Search memory: pages, claims and conversations, fused.",
        (_p("query"),), exposed=True),
    Row(("get",), "cicada_recall_detail",
        "One page in full (a long one in parts: --start), or a range of its lines (--from/--count, or "
        "ENTITY:START[:END]).",
        (_p("entity_id"), _f("start", "int"), _f("include", "list")),
        options=(Option("--from", "int", "First line to show (1-based)."),
                 Option("--count", "int", "How many lines to show."),
                 Option("--line-numbers", "bool", "Prefix each line with its number.")), exposed=True, api_op="page"),
    Row(("project",), "cicada_project", "Where one project stands.",
        (_p("project"), _f("since"), _f("tz")), exposed=True),
    Row(("continue",), "cicada_continue", "Where the work in this folder stopped.",
        (_f("session"), _f("before")), exposed=True),
    Row(("save",), "cicada_save_episode", "Stage a note for the next Sleep (content `-` reads stdin).",
        (_p("content"), _f("title")), mutates=True, exposed=True, api_op="save_note"),
    Row(("handshake",), "cicada_handshake", "The contract and the current state, for an agent arriving cold.",
        exposed=True),
    # --- slice 2 (proposed spellings) ----------------------------------------------
    Row(("ask",), "cicada_ask", "Answer a direct question from memory, with citations.",
        (_p("query"), _f("top_k", "int"))),
    Row(("timeline",), "cicada_timeline", "What changed in memory, day by day.", (_f("since"),), exposed=True),
    Row(("hub",), "cicada_open_hub", "A topic index page.", (_p("hub"),)),
    Row(("perspective",), "cicada_get_perspective", "Beliefs about one subject, by observer.",
        (_p("subject"), _f("observer"), _f("context"), _f("history", "bool"))),
    Row(("source", "list"), "cicada_sources", "Where a page's facts can be checked.", (_p("entity_id"),)),
    Row(("source", "add"), "cicada_add_source", "Record where a fact can be checked.",
        (_p("subject"), _p("ref"), _f("predicate"), _f("access"), _f("kind"), _f("entity"), _f("inferred", "bool"),
         _f("evidence", "json")), mutates=True),
    Row(("source", "change"), "cicada_change_source", "Fix or drop a source you added.",
        (_p("subject"), _p("ref"), _p("action"), _f("predicate"), _f("reason"), _f("new_ref"),
         _f("new_predicate"), _f("access"), _f("entity")), mutates=True),
    Row(("claim", "add"), "cicada_write_claim", "Write a belief with its evidence.",
        (_p("subject"), _p("predicate"), _p("object"), _f("observer"), _f("confidence", "float"),
         _f("context"), _f("source_episode"), _f("force_new_entity", "bool"), _f("sources", "json"),
         _f("evidence", "json"), _f("expected_end")), mutates=True, api_op="write_claim"),
    Row(("claim", "retract"), "cicada_retract_claim", "Withdraw a claim you wrote; it stays as history.",
        (_p("subject"), _p("claim_id"), _p("reason"), _f("evidence", "json")), mutates=True,
        api_op="retract_claim"),
    # G198: a page's words or aliases, with a reason that becomes the commit message (a proposal when not trusted).
    Row(("page", "edit"), "cicada_edit_page", "Fix a page's words or aliases, with your reason.",
        (_p("subject"), _p("reason"), _f("edits", "json"), _f("section"), _f("text"),
         _f("add_aliases", "list", flag_name="add-alias"), _f("remove_aliases", "list", flag_name="remove-alias"),
         _f("evidence", "json"), _f("resolves", "json"), _f("name"), _f("description")), mutates=True),
    Row(("inbox", "list"), "cicada_check_nudges", "Questions Cicada has for the person on a topic.",
        (_f("mode"), _f("topic"), _f("entity_ids", "list", flag_name="entity-id")), api_op="inbox"),
    Row(("inbox", "resolve"), "cicada_resolve_inbox", "Record the person's own answer to a question.",
        (_p("id"), _f("option_key"), _f("answer"), _f("defer", "bool"), _f("remind_days", "int"),
         _f("skip", "bool"), _f("reject", "bool"), _f("quote")), mutates=True, api_op="resolve_inbox"),
    Row(("inbox", "record-check"), "cicada_record_check", "Report what a source check found.",
        (_p("item_id"), _p("source"), _p("outcome"), _f("option_key"), _f("proposed_value"),
         _f("quotes", "json"), _f("summary"), _f("via")), mutates=True),
    Row(("progress", "add"), "cicada_note_progress", "Record what happened in a project.",
        (_p("project"), _p("kind"), _p("summary"), _p("status"), _f("when"), _f("target"), _f("milestone"),
         _f("settles"), _f("participants", "json"), _f("evidence", "json")), mutates=True),
    # Ruling 45 (2026-10-27): proposed spellings, not exposed — `project` is the read's own command, so these live under
    # `projects`; the person's own shell starts one with `projects new` (an app command, below).
    Row(("projects", "create"), "cicada_create_project", "Start a project the person asked for.",
        (_p("project"), _f("description"), _f("evidence", "json"), _f("repo")), mutates=True),
    Row(("projects", "link"), "cicada_link_conversation", "Tie a conversation to a project, or untie one you tied.",
        (_p("project"), _p("reason"), _f("episode"), _f("session"), _f("remove", "bool")), mutates=True),
    Row(("projects", "tie-page"), "cicada_link_entity", "Tie a page to a project, or take back a tie you made.",
        (_p("project"), _p("entity"), _p("reason"), _f("remove", "bool")), mutates=True),
    Row(("projects", "influence"), "cicada_add_influence", "Record something that fed a project: a link or a thing.",
        (_p("project"), _f("what"), _f("url"), _f("how"), _f("evidence", "json")), mutates=True),
    Row(("backlog", "list"), "cicada_backlog", "A project's backlog.",
        (_p("project"), _f("status"), _f("item"))),
    Row(("backlog", "add"), "cicada_add_backlog_item", "File an item on a project's backlog.",
        (_p("project"), _p("title"), _p("description"), _f("triage"), _f("paid", "bool")), mutates=True),
    Row(("backlog", "note"), "cicada_add_backlog_note", "Add a finding to a backlog item.",
        (_p("item"), _p("note"), _f("status")), mutates=True),
    Row(("design", "save"), "cicada_save_design", "Save a look the person likes: a screenshot, its link, the note.",
        (_p("note"), _f("url"), _f("image_path"), _f("image_base64"), _f("title"), _f("snippets", "json"),
         _f("tags", "list", flag_name="tag"), _f("region", "json"), _f("tokens", "json"), _f("subject")),
        mutates=True),
    Row(("design", "search"), "cicada_design_search", "The person's saved looks, by words or by a picture.",
        (_f("query"), _f("image_path"), _f("image_base64"), _f("limit", "int"))),
    # The Skills page (2026-10-15): an agent reads, asks and drafts; installing is the person's (`skills add`).
    Row(("skills", "list"), "cicada_skills", "Agent skills on this Mac, per agent, with updates and requests.",
        exposed=True),
    Row(("skills", "propose"), "cicada_propose_skill",
        "Ask the person to install or update a skill (on/off/refresh apply at once if you're trusted).",
        (_p("action"), _p("reason"), _f("source"), _f("skill"), _f("agents", "list", flag_name="agent")),
        mutates=True, exposed=True),
    Row(("skills", "create"), "cicada_create_skill", "Draft a skill for a workflow; held until the person publishes it.",
        (_p("skill"), _p("description"), _p("body"), _f("reason")), mutates=True, exposed=True),
    Row(("episodes", "pending"), "cicada_pending", "Conversations not consolidated yet, each with its revision.",
        (_f("limit", "int"),)),
    Row(("episodes", "mark"), "cicada_mark_processed", "Mark consolidated conversations, revision-checked.",
        (_p("episode_ids", "list"), _f("revisions", "pairs", flag_name="rev")), mutates=True),
    Row(("link", "save"), "cicada_save_url", "Save a link for the person.",
        (_p("url"), _f("note")), mutates=True, api_op="save_url"),
    Row(("video", "record"), "cicada_record_watch", "Record a watched video: summary and short quotes.",
        (_p("url"), _p("summary"), _f("excerpts", "json"), _f("chapters", "json"), _f("basis"), _f("engine"),
         _f("duration"), _f("lease_token")), mutates=True),
    Row(("video", "queue"), "cicada_video_queue", "Videos the person asked to have watched.", (_f("limit", "int"),)),
    Row(("video", "claim"), "cicada_video_claim", "Take videos from the queue to watch.",
        (_f("limit", "int"), _f("release", "json")), mutates=True),
    # G166 exploring (2026-10-14): proposed spellings, not exposed yet; the start is never a CLI door (D5, ruling 21a).
    Row(("explore", "queue"), "cicada_explore_queue", "Saved sites the person asked to have explored.",
        (_f("limit", "int"),)),
    Row(("explore", "claim"), "cicada_explore_claim", "Take a saved site to explore, or hand one back.",
        (_f("limit", "int"), _f("release", "json")), mutates=True),
    Row(("explore", "record"), "cicada_record_capture", "Record what a site's capture saw.",
        (_p("url"), _p("lease_token"), _p("outcome"), _f("captured_at"), _f("final_url"), _f("http_status", "int"),
         _f("shots", "json"), _f("page", "json"), _f("signed_in", "bool"), _f("account_visible", "bool"),
         _f("consent_overlay", "bool"), _f("consent_box", "json"), _f("next_pages", "json"), _f("loads", "int"),
         _f("via"), _f("last_modified"), _f("loaded_at"), _f("pages", "json"), _f("found", "json"),
         _f("robots", "json"), _f("section", "json"), _f("design", "json")), mutates=True),
    Row(("explore", "map"), "cicada_site_map", "The pages found and opened on an explored site.", (_f("site"),)),
    Row(("explore", "start"), "cicada_explore_start", "Start exploring the person's saved sites.",
        (_f("scope"), _f("origins", "list", flag_name="origin"), _f("look", "list")), mutates=True,
        mcp_only="a run starts only from the person's own request in a conversation, or their click (D5); never from "
                 "a shell"),
    # G61, ruling 26: proposed spellings, not exposed yet.
    Row(("source", "refresh-claim"), "cicada_refresh_claim", "Take a tracked source due a re-check, or hand one back.",
        (_f("limit", "int"), _f("release", "json")), mutates=True),
    Row(("source", "refresh-record"), "cicada_record_refresh", "Record what a tracked source says now.",
        (_p("entity_id"), _p("source"), _p("lease_token"), _p("outcome"), _f("predicate"), _f("value"),
         _f("ended", "json"), _f("quotes", "json"), _f("captured_at"), _f("summary"), _f("via")), mutates=True),
    Row(("read", "queue"), "cicada_reading_queue", "Pages the person asked to have read.", (_f("limit", "int"),)),
    # G71 (2026-10-16): a proposed spelling, not exposed — the agent reads the lists in the person's browser.
    Row(("read", "youtube"), "cicada_record_youtube_list", "Record what the person's YouTube list showed.",
        (_p("list"), _p("outcome"), _f("videos", "json"), _f("via")), mutates=True),
    # G206 (2026-10-22): a proposed spelling, not exposed — the agent reads the lists in the person's browser.
    Row(("read", "saved"), "cicada_record_saved_list", "Record what the person's saved list on a site showed.",
        (_p("platform"), _p("outcome"), _f("items", "json"), _f("via")), mutates=True),
    # 2026-10-16 (the linkedin-people skill): a proposed spelling, not exposed — the agent reads in the person's browser.
    Row(("read", "profile"), "cicada_record_profile", "Record what one person's LinkedIn profile shows now.",
        (_p("entity_id"), _p("url"), _p("outcome"), _f("company"), _f("position"), _f("quotes", "json"),
         _f("summary"), _f("via")), mutates=True),
    Row(("read", "record"), "cicada_record_read", "Record what a page read found.",
        (_p("url"), _p("outcome"), _f("summary"), _f("excerpts", "json"), _f("via"), _f("note"), _f("title"),
         _f("facts", "json")),
        mutates=True),
    Row(("repo",), "cicada_repo_context", "Live git context for a repository Cicada knows about.",
        (_f("entity_id"), _f("path"))),
    # --- CLI-only -------------------------------------------------------------------
    Row(("status",), None, "Which memory this command uses, and whether the app's backend agrees.", exposed=True),
    Row(("commands",), None, "Every command, and the MCP tool each one mirrors.", exposed=True),
    # One import for both kinds of export (G71 platform saves, read here; G180 chat exports, the backend's intake).
    Row(("import",), None,
        "Bring in a data export: what the person saved on a platform (a .zip, a folder or one file), or a chat "
        "export (through the app's backend).",
        (Arg("path", positional=True),),
        options=(Option("--preview", "bool", "Say what the export holds; write nothing."),
                 Option("--include-history", "bool", "Also read watch and browsing history (not saves)."),
                 Option("--no-wait", "bool", "A chat export: return once the backend has queued it.")),
        mutates=True, exposed=True, via="both", person=True, app=True),
    # --- the app's commands (G180 parity; `api/cli_app.py`) -------------------------
    # Pages and the graph.
    _app(("page", "list"), "Every page, with its type and status.", (_f("type"), _f("status"))),
    _app(("page", "history"), "A page's change history, newest first.", (_p("entity_id"), _f("limit", "int"))),
    _app(("page", "decay"), "Set how a page fades (durable, active, volatile or evergreen).",
         (_p("entity_id"), _p("decay_class")), via="backend", mutates=True, person=True),
    _app(("graph",), "The graph at a glance: pages by type and status, and the links between them."),
    _app(("find",), "Find pages, beliefs, conversations, sources and questions, as the app's search does.",
         (_p("query"), _f("kind", "list"), _f("limit", "int"))),
    # Coverage (vision items 1-2, 2026-10-28): counts and enums only; --ids adds a few page ids per bucket.
    _app(("coverage", "pictures"), "How many pages show a picture, by type and rung, and why the rest do not.",
         (_f("ids", "bool"), _f("archived", "bool"))),
    _app(("coverage", "sources"), "Which write paths put the sources on pages, and which pages have none.",
         (_f("ids", "bool"), _f("archived", "bool"))),
    # The inbox.
    _app(("inbox", "all"), "Every open inbox question, of every kind, with its choices.", (_f("kind", "list"),)),
    _app(("inbox", "answer"), "Answer an inbox question as the person: --option, --answer, --defer or --reject.",
         (_p("item_id"), _f("option"), _f("answer"), _f("defer", "bool"), _f("days", "int"), _f("reject", "bool")),
         via="backend", mutates=True, person=True),
    # Sleep.
    _app(("sleep", "status"), "Whether Sleep is running, paused or idle, and how much is waiting.", via="backend"),
    _app(("sleep", "start"), "Start Sleep: read everything waiting (--continue resumes a paused run).",
         (_f("continue_run", "bool", flag_name="continue"),), via="backend", mutates=True, person=True),
    _app(("sleep", "stop"), "Stop the running Sleep at its next safe point; nothing filed is lost.",
         via="backend", mutates=True),
    _app(("sleep", "end"), "End a paused run; everything waiting stays queued.", via="backend", mutates=True),
    _app(("sleep", "schedule"), "When Sleep runs on its own; --mode manual|daily|interval, --at HH:MM, --every HOURS; "
                                "--use-plan on|off lets scheduled runs use your plan.",
         (_f("mode"), _f("at"), _f("every", "int"), _f("use_plan")), via="backend", mutates=True, person=True),
    _app(("sleep", "engine"), "Which engine and model Sleep reads with; --mode and --model change it.",
         (_f("mode"), _f("model")), via="backend", mutates=True, person=True),
    _app(("sleep", "options"), "How Sleep reads: batch size, continue after a plan reset, the reserve.",
         (_f("batch_size", "int"), _f("continue_after_reset"), _f("reserve")), via="backend", mutates=True,
         person=True),
    _app(("sleep", "history"), "Past Sleep runs, newest first.", (_f("limit", "int"),)),
    # The search index and model.
    _app(("index", "status"), "The word index and the search model: state, re-embedding, downloads.", via="backend"),
    _app(("index", "rebuild"), "Rebuild the word index now.", via="backend", mutates=True),
    _app(("index", "use"), "Use another installed search model (`default` for the default); re-embeds in the "
                           "background.", (_p("model"),), via="backend", mutates=True, person=True),
    _app(("index", "install"), "Download a search model (only ever on the person's command).", (_f("model"),),
         via="backend", mutates=True, person=True),
    # Projects (ruling 45): the person's own, from their own shell.
    _app(("projects", "new"), "Start a project of your own: a name and a description.",
         (_p("project"), _f("description")), via="backend", mutates=True, person=True),
    # Sources and imports.
    _app(("feed", "list"), "The RSS/Atom feeds this memory follows."),
    _app(("feed", "add"), "Follow an RSS/Atom feed.", (_p("url"), _f("tag", "list")), via="backend", mutates=True),
    _app(("feed", "remove"), "Stop following a feed.", (_p("url"),), via="backend", mutates=True),
    _app(("feed", "poll"), "Fetch every followed feed now.", via="backend", mutates=True, person=True),
    # Ruling 47 tier 2 (and the saved-content connectors): the person's own accounts, by their own token.
    _app(("connector", "list"), "The accounts Cicada can read with your own token (Readwise, Notion, …): what each "
                                "reads, whether it is connected, its last sync.", via="backend"),
    _app(("connector", "connect"), "Connect one with your own token, read from standard input (never an argument); "
                                   "Cicada checks it with the service before saving it.", (_p("connector"),),
         via="backend", mutates=True, person=True),
    _app(("connector", "disconnect"), "Disconnect one: Cicada forgets its token.", (_p("connector"),), via="backend",
         mutates=True, person=True),
    _app(("connector", "sync"), "Read one now (your click: no gate, but never while Sleep holds your memory).",
         (_p("connector"),), via="backend", mutates=True, person=True),
    # Settings and engines.
    _app(("settings", "owner"), "Who the person is (--name, --handle, --email change it).",
         (_f("name"), _f("handle"), _f("email")), via="backend", mutates=True, person=True),
    _app(("engine", "list"), "The engines and plans Cicada can read with, whether each is ready, and what runs "
                             "Sleep you start and scheduled Sleep.", via="backend"),
    # Ruling 4b (owner, 2026-10-16): sign in to a plan on THIS machine through its own CLI's sign-in.
    _app(("engine", "connect"), "Sign in to your plan on this machine: claude-plan or chatgpt-plan (the plan's own "
                                "sign-in; Cicada never sees the token).", (_p("connection"),), via="backend",
         mutates=True, person=True),
    # Pictures.
    _app(("picture", "set"), "Use an image file as a page's picture.", (_p("entity_id"), _p("file")), via="backend",
         mutates=True, person=True),
    _app(("picture", "initials"), "Use initials as a page's picture.", (_p("entity_id"),), via="backend",
         mutates=True, person=True),
    _app(("picture", "clear"), "Go back to the detected picture.", (_p("entity_id"),), via="backend", mutates=True,
         person=True),
    # Banks.
    _app(("bank", "list"), "Every memory bank, its size, and which one is active."),
    _app(("bank", "use"), "Switch the active memory bank.", (_p("bank_name"),), via="backend", mutates=True, person=True),
    _app(("bank", "create"), "Create an empty memory bank.", (_p("bank_name"), _f("description")), via="backend",
         mutates=True),
    _app(("bank", "rename"), "Rename a memory bank.", (_p("bank_name"), _p("new_name")), via="backend", mutates=True,
         person=True),
    _app(("bank", "delete"), "Move a memory bank to the trash (nothing erased).", (_p("bank_name"),), via="backend",
         mutates=True, person=True),
    # Skills (2026-10-15): the person's side of the Skills page. Installing third-party code is never an agent's.
    _app(("skills", "check"), "Ask upstream whether an installed skill has a newer version.", via="backend",
         mutates=True, person=True),
    _app(("skills", "add"), "Show a skill from GitHub (a link, owner/repo or an `npx skills add` line); --yes "
                            "installs it, pinned to the commit shown.",
         (_p("source"), _f("agent", "list"), _f("choose"), _f("yes", "bool")), via="backend", mutates=True,
         person=True),
    _app(("skills", "install"), "Install one of Cicada's suggested skills, at its reviewed version.",
         (_p("suggestion"), _f("agent", "list")), via="backend", mutates=True, person=True),
    _app(("skills", "update"), "Update an installed skill to upstream's newest, pinned to that commit.",
         (_p("skill"),), via="backend", mutates=True, person=True),
    _app(("skills", "update-all"), "Install every update the last check found.", via="backend", mutates=True,
         person=True),
    _app(("skills", "on"), "Give an agent a skill another agent already has.", (_p("skill"), _p("agent")),
         via="backend", mutates=True, person=True),
    _app(("skills", "off"), "Take a skill away from one agent (Cicada keeps a copy).", (_p("skill"), _p("agent")),
         via="backend", mutates=True, person=True),
    _app(("skills", "refresh"), "Rewrite a tool skill's text from the tool installed now.", (_p("skill"),),
         via="backend", mutates=True, person=True),
    _app(("skills", "remove"), "Remove a skill from every agent (what Cicada didn't write is kept aside).",
         (_p("skill"),), via="backend", mutates=True, person=True),
    _app(("skills", "publish"), "Publish a skill an agent drafted to the agents you name.",
         (_p("skill"), _f("agent", "list")), via="backend", mutates=True, person=True),
    # G181 phase 2 (owner ruling 1, 2026-10-16): the person's other devices, each with its own token. Run on the
    # server: only its own token may issue or revoke one, never a device's.
    _app(("device", "add"), "Issue a token for another of your devices (shown once; only its hash is kept).",
         (_p("device_name"),), via="backend", mutates=True, person=True),
    _app(("device", "list"), "Your devices, and whether each one's token still works.", via="backend"),
    _app(("device", "revoke"), "Revoke a device's token at once.", (_p("device_id"),), via="backend", mutates=True,
         person=True),
    # G212 (2026-10-22): a one-time code a new device trades once for its own token (`POST /pair`).
    _app(("device", "pair"), "Show a one-time code (and its QR payload) a new device trades for its own token "
         "(--kind capture for a phone, the default; full for a computer).",
         (_f("url"), _f("kind")), via="backend", mutates=True, person=True),
    # G213 (2026-10-22): a token for an agent that speaks HTTP, not MCP, and the paragraph to give it.
    _app(("agent", "add"), "Make a token for a personal agent on the HTTP agent API, and the paragraph to give it.",
         (_p("agent_name"), _f("scope", "list"), _f("days", "int"), _f("url")), via="backend", mutates=True,
         person=True),
    # G213 (owner 2026-10-22): look at this machine, then confirm each step — agents, a device, an agent's token.
    _app(("setup",), "Find what is on this machine and connect it, one confirmed step at a time.",
         (_f("url"), _f("pair", "bool"), _f("agent")), via="backend", mutates=True, person=True),
    _app(("agent", "list"), "The agents holding an agent-API token, and whether each still works.", via="backend"),
    _app(("agent", "revoke"), "Revoke an agent's token at once.", (_p("agent_id"),), via="backend", mutates=True,
         person=True),
)


class Placeholder(str):
    """A value to show as ``<name>`` in a spelled command, unquoted (``cicada get <entity-id>``)."""

    def __new__(cls, name: str):
        return super().__new__(cls, f"<{name}>")


def spell(tool: str, **values) -> str:
    """The command line that does what ``tool(**values)`` does, built from this table: positionals in
    order, then flags, every concrete value shell-quoted so the line runs exactly as printed. A
    generated reply spells its actions with this, never by hand (R12 by construction)."""
    import shlex

    row = by_tool()[tool]
    words = ["cicada", *row.command]
    flags: list[str] = []
    for arg in row.args:
        value = values.pop(arg.prop, None)
        if value is None or (arg.kind == "bool" and value is False):
            continue
        if arg.kind == "bool" and value is True and not arg.positional:
            flags.append(arg.flag)        # a store_true flag takes no value (`--skip`, never `--skip True`)
            continue
        rendered = value if isinstance(value, Placeholder) else shlex.quote(str(value))
        if arg.positional:
            words.append(rendered)
        else:
            flags += [arg.flag, rendered]
    if values:
        raise ValueError(f"{tool} has no argument {sorted(values)}")
    return " ".join(words + flags)


#: Where a release app's launcher lives when `cicada` is not on PATH (the app rewrites it on every launch).
FALLBACK = '"${CICADA_HOME:-$HOME/.cicada}/bin/cicada"'
SKILL_BEGIN = "<!-- cicada-cli:begin (generated from api/services/cli_map.py: edit the table, not this block) -->"
SKILL_END = "<!-- cicada-cli:end -->"


def _usage(row: Row) -> str:
    words = ["cicada", *row.command]
    for arg in row.args:
        if arg.positional:
            name = f"<{arg.prop.replace('_', '-')}>"
            words.append(f'"{name}"' if arg.prop in ("query", "content") else name)
    return " ".join(words)


def _options(row: Row) -> list[str]:
    return [a.flag for a in row.args if not a.positional] + [o.flag for o in row.options]


def skill_block() -> str:
    """The portable skill's command-line section (SKILL.md), generated from this table so it can never name a
    command or flag the CLI lacks (R12 by construction). Provider-neutral; no machine's paths."""
    rows = [r for r in exposed() if not r.app]
    lines = [
        "Agents that can run shell commands can use `cicada` instead of the MCP tools: the same memory and bank,",
        "read and written by the same code. `cicada --help` lists the commands (`--help` after any command explains",
        "it).",
        "",
        f"- **Where it is:** `cicada` on PATH; if that is not found, {FALLBACK} (the Cicada app keeps that",
        "  launcher current).",
        "- **Start:** `cicada handshake` when no Cicada primer reached you; `cicada continue` for where the work in",
        "  this folder stopped.",
        "",
        "| Command | What it does |",
        "|---|---|",
    ]
    lines += [f"| `{_usage(r)}` | {r.summary.replace('|', '/')} |" for r in rows]
    opts = [f"{r.name}: " + ", ".join(f"`{f}`" for f in _options(r)) for r in rows if _options(r)]
    lines += [
        "",
        "- **Options:** " + "; ".join(opts) + ". `get` also takes `<entity-id>:<start>[:<end>]`; `save` reads the",
        "  text from stdin when it is `-`.",
        "- **`--json`** (before or after the command) prints one envelope: `{schema, command, ok, code, bank, data,",
        "  text, warnings, version}`. `text` is what the matching MCP tool says; `data` is the structured part.",
        "- **Exit codes:** 0 ok (a duplicate save is ok too) · 1 refused (`not_found`, `empty_graph`) · 2 usage ·",
        "  3 bank or memory-folder mismatch, nothing written · 4 demo bank · 5 this shell may not use the memory",
        "  folder (use the MCP tools there) · 6 the app's backend is not running (only for commands that act on",
        "  it) · 70 internal.",
        "- **Grouping:** what you save is grouped by your harness's session id. If your harness gives none, set",
        "  `CICADA_SESSION_ID` and `CICADA_SESSION_HARNESS`; without them a note is saved ungrouped, never under a",
        "  made-up id.",
        "- **Not in the command line yet:** questions, claims, sources, progress and the backlog. Use the MCP tools",
        "  for those when they are connected.",
        "- **The app's commands** (Sleep, banks, the search model, feeds, pictures, settings) are listed by",
        "  `cicada commands`. Those that act as the person refuse from an agent's shell.",
        "",
    ]
    return "\n".join(lines)


def write_skill_block(path) -> None:
    """Rewrite the generated block between the markers in ``path`` (SKILL.md)."""
    from pathlib import Path

    p = Path(path)
    text = p.read_text(encoding="utf-8")
    start = text.index(SKILL_BEGIN) + len(SKILL_BEGIN) + 1
    end = text.index(SKILL_END)
    p.write_text(text[:start] + skill_block() + text[end:], encoding="utf-8")


def rows() -> tuple[Row, ...]:
    return ROWS


def exposed() -> tuple[Row, ...]:
    return tuple(r for r in ROWS if r.exposed)


def by_name() -> dict[str, Row]:
    return {r.name: r for r in ROWS}


def by_tool() -> dict[str, Row]:
    return {r.tool: r for r in ROWS if r.tool}


def read_only_tools() -> frozenset[str]:
    """**The one list of tools that only read** — every row whose tool changes nothing (``mutates=False``). The stdio
    server's ``readOnlyHint`` comes from here (``mcp/server.py``), and ``test_tool_annotations`` holds the remote
    catalog's ``READ_TOOLS`` / ``WRITE_TOOLS`` and the remote definitions to it, so no door marks a write read-only.
    A cache outside every bank (a primer, a derived index), an ids-only ledger row or this process's own memory is
    not a write; the bank, the inbox, a queue lease or the person's agent folders are (2026-10-23: Codex asked for
    approval on every ``cicada_continue`` because only the remote list was annotated)."""
    return frozenset(r.tool for r in ROWS if r.tool and not r.mutates)


def exposed_tools() -> frozenset[str]:
    """The MCP tools a CLI caller holds — `ToolContext.available` for the CLI, so a reply
    never names an action the command line does not have."""
    return frozenset(r.tool for r in exposed() if r.tool)


def catalog() -> list[dict]:
    """`cicada commands`' data: one entry per row, exposed or not."""
    out = []
    for r in ROWS:
        out.append({
            "command": r.name,
            "mirrors": r.tool,
            "exposed": r.exposed,
            "mutates": r.mutates,
            "summary": r.summary,
            "args": [{"property": a.prop, "kind": a.kind,
                      **({"positional": True} if a.positional else {"flag": a.flag})} for a in r.args],
            "options": [{"flag": o.flag, "kind": o.kind, "help": o.help} for o in r.options],
            "via": r.via,
            "person": r.person,
            **({"mcp_only": r.mcp_only} if r.mcp_only else {}),
        })
    return out


__all__ = ["Arg", "KINDS", "Option", "Placeholder", "ROWS", "Row", "by_name", "by_tool", "catalog", "exposed", "exposed_tools",
           "rows", "skill_block", "spell", "write_skill_block"]
