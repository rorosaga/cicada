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

    @property
    def name(self) -> str:
        return " ".join(self.command)


def _p(prop: str, kind: str = "str") -> Arg:
    return Arg(prop, kind, positional=True)


def _f(prop: str, kind: str = "str", flag_name: str | None = None) -> Arg:
    return Arg(prop, kind, flag_name=flag_name)


ROWS: tuple[Row, ...] = (
    # --- slice 1 (exposed) --------------------------------------------------------------
    Row(("recall",), "cicada_recall", "Search memory: pages, claims and conversations, fused.",
        (_p("query"),), exposed=True),
    Row(("get",), "cicada_recall_detail",
        "One page in full, or a range of its lines (--from/--count, or ENTITY:START[:END]).",
        (_p("entity_id"),),
        options=(Option("--from", "int", "First line to show (1-based)."),
                 Option("--count", "int", "How many lines to show."),
                 Option("--line-numbers", "bool", "Prefix each line with its number.")), exposed=True),
    Row(("project",), "cicada_project", "Where one project stands.",
        (_p("project"), _f("since"), _f("tz")), exposed=True),
    Row(("continue",), "cicada_continue", "Where the work in this folder stopped.",
        (_f("session"), _f("before")), exposed=True),
    Row(("save",), "cicada_save_episode", "Stage a note for the next Sleep (content `-` reads stdin).",
        (_p("content"), _f("title")), mutates=True, exposed=True),
    Row(("handshake",), "cicada_handshake", "The contract and the current state, for an agent arriving cold.",
        exposed=True),
    # --- slice 2 (proposed spellings) ----------------------------------------------
    Row(("ask",), "cicada_ask", "Answer a direct question from memory, with citations.",
        (_p("query"), _f("top_k", "int"))),
    Row(("timeline",), "cicada_timeline", "What changed in memory, day by day.", (_f("since"),)),
    Row(("hub",), "cicada_open_hub", "A topic index page.", (_p("hub"),)),
    Row(("perspective",), "cicada_get_perspective", "Beliefs about one subject, by observer.",
        (_p("subject"), _f("observer"), _f("context"), _f("history", "bool"))),
    Row(("source", "list"), "cicada_sources", "Where a page's facts can be checked.", (_p("entity_id"),)),
    Row(("source", "add"), "cicada_add_source", "Record where a fact can be checked.",
        (_p("subject"), _p("ref"), _f("predicate"), _f("access"), _f("kind"), _f("entity")), mutates=True),
    Row(("source", "change"), "cicada_change_source", "Fix or drop a source you added.",
        (_p("subject"), _p("ref"), _p("action"), _f("predicate"), _f("reason"), _f("new_ref"),
         _f("new_predicate"), _f("access"), _f("entity")), mutates=True),
    Row(("claim", "add"), "cicada_write_claim", "Write a belief with its evidence.",
        (_p("subject"), _p("predicate"), _p("object"), _f("observer"), _f("confidence", "float"),
         _f("context"), _f("source_episode"), _f("force_new_entity", "bool"), _f("sources", "json"),
         _f("evidence", "json"), _f("expected_end")), mutates=True),
    Row(("claim", "retract"), "cicada_retract_claim", "Withdraw a claim you wrote; it stays as history.",
        (_p("subject"), _p("claim_id"), _p("reason"), _f("evidence", "json")), mutates=True),
    Row(("inbox", "list"), "cicada_check_nudges", "Questions Cicada has for the person on a topic.",
        (_f("topic"), _f("entity_ids", "list", flag_name="entity-id"))),
    Row(("inbox", "resolve"), "cicada_resolve_inbox", "Record the person's own answer to a question.",
        (_p("id"), _f("option_key"), _f("answer"), _f("defer", "bool"), _f("remind_days", "int"),
         _f("skip", "bool"), _f("reject", "bool")), mutates=True),
    Row(("inbox", "record-check"), "cicada_record_check", "Report what a source check found.",
        (_p("item_id"), _p("source"), _p("outcome"), _f("option_key"), _f("proposed_value"),
         _f("quotes", "json"), _f("summary"), _f("via")), mutates=True),
    Row(("progress", "add"), "cicada_note_progress", "Record what happened in a project.",
        (_p("project"), _p("kind"), _p("summary"), _p("status"), _f("when"), _f("target"), _f("milestone"),
         _f("settles"), _f("participants", "json"), _f("evidence", "json")), mutates=True),
    Row(("backlog", "list"), "cicada_backlog", "A project's backlog.",
        (_p("project"), _f("status"), _f("item"))),
    Row(("backlog", "add"), "cicada_add_backlog_item", "File an item on a project's backlog.",
        (_p("project"), _p("title"), _p("description"), _f("triage"), _f("paid", "bool")), mutates=True),
    Row(("backlog", "note"), "cicada_add_backlog_note", "Add a finding to a backlog item.",
        (_p("item"), _p("note"), _f("status")), mutates=True),
    Row(("episodes", "pending"), "cicada_pending", "Conversations not consolidated yet, each with its revision.",
        (_f("limit", "int"),)),
    Row(("episodes", "mark"), "cicada_mark_processed", "Mark consolidated conversations, revision-checked.",
        (_p("episode_ids", "list"), _f("revisions", "pairs", flag_name="rev")), mutates=True),
    Row(("link", "save"), "cicada_save_url", "Save a link for the person.",
        (_p("url"), _f("note")), mutates=True),
    Row(("video", "record"), "cicada_record_watch", "Record a watched video: summary and short quotes.",
        (_p("url"), _p("summary"), _f("excerpts", "json"), _f("chapters", "json"), _f("basis"), _f("engine"),
         _f("duration")), mutates=True),
    Row(("video", "queue"), "cicada_video_queue", "Videos the person asked to have watched.", (_f("limit", "int"),)),
    Row(("video", "claim"), "cicada_video_claim", "Take videos from the queue to watch.",
        (_f("limit", "int"), _f("release", "json")), mutates=True),
    Row(("read", "queue"), "cicada_reading_queue", "Pages the person asked to have read.", (_f("limit", "int"),)),
    Row(("read", "record"), "cicada_record_read", "Record what a page read found.",
        (_p("url"), _p("outcome"), _f("summary"), _f("excerpts", "json"), _f("via"), _f("note"), _f("title")),
        mutates=True),
    Row(("repo",), "cicada_repo_context", "Live git context for a repository Cicada knows about.",
        (_f("entity_id"), _f("path"))),
    # --- CLI-only -------------------------------------------------------------------
    Row(("status",), None, "Which memory this command uses, and whether the app's backend agrees.", exposed=True),
    Row(("commands",), None, "Every command, and the MCP tool each one mirrors.", exposed=True),
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
        if value is None:
            continue
        rendered = value if isinstance(value, Placeholder) else shlex.quote(str(value))
        if arg.positional:
            words.append(rendered)
        else:
            flags += [arg.flag, rendered]
    if values:
        raise ValueError(f"{tool} has no argument {sorted(values)}")
    return " ".join(words + flags)


def rows() -> tuple[Row, ...]:
    return ROWS


def exposed() -> tuple[Row, ...]:
    return tuple(r for r in ROWS if r.exposed)


def by_tool() -> dict[str, Row]:
    return {r.tool: r for r in ROWS if r.tool}


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
            **({"mcp_only": r.mcp_only} if r.mcp_only else {}),
        })
    return out


__all__ = ["Arg", "KINDS", "Option", "Placeholder", "ROWS", "Row", "by_tool", "catalog", "exposed", "exposed_tools",
           "rows", "spell"]
