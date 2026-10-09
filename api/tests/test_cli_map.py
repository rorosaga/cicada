"""G180 / TODO ruling 21 — the CLI↔MCP mapping table is a tested artifact (R12 by construction).

Every stdio tool has exactly one row; every schema property is mapped exactly once with
a kind that matches its JSON type; a required property is positional; CLI-only options
are catalogued apart from mapped properties; and no row is a generic dispatcher."""
from __future__ import annotations

from _stdio_server import stdio_server
from api.services import cli_map

_TYPE_KINDS = {
    "string": {"str"},
    "integer": {"int"},
    "number": {"float"},
    "boolean": {"bool"},
    "object": {"json", "pairs"},
}


def _schemas() -> dict[str, dict]:
    return {t["name"]: t["inputSchema"] for t in stdio_server().TOOLS}


def _allowed(spec: dict) -> set[str]:
    kind = spec.get("type")
    if kind == "array":
        items = (spec.get("items") or {}).get("type")
        return {"list"} if items == "string" else {"json"}
    return _TYPE_KINDS[kind]


def test_every_stdio_tool_has_exactly_one_row():
    tools = [r.tool for r in cli_map.rows() if r.tool]
    assert sorted(tools) == sorted(_schemas())
    assert len(tools) == len(set(tools))


def test_command_names_are_unique_short_and_grouped():
    names = [r.command for r in cli_map.rows()]
    assert len(names) == len(set(names))
    for command in names:
        assert 1 <= len(command) <= 2, command
        for word in command:
            assert word == word.lower() and " " not in word and not word.startswith("cicada"), word


def test_each_schema_property_is_mapped_exactly_once_with_a_matching_kind():
    schemas = _schemas()
    for row in cli_map.rows():
        if not row.tool:
            continue
        props = schemas[row.tool].get("properties", {})
        mapped = [a.prop for a in row.args]
        assert sorted(mapped) == sorted(props), row.name
        for arg in row.args:
            assert arg.kind in cli_map.KINDS
            assert arg.kind in _allowed(props[arg.prop]), (row.name, arg.prop, arg.kind)


def test_required_properties_are_positional_and_optional_ones_are_flags():
    schemas = _schemas()
    for row in cli_map.rows():
        if not row.tool:
            continue
        required = set(schemas[row.tool].get("required", []))
        for arg in row.args:
            assert arg.positional == (arg.prop in required), (row.name, arg.prop)


def test_flags_and_options_never_collide_within_a_command():
    for row in cli_map.rows():
        flags = [a.flag for a in row.args if not a.positional] + [o.flag for o in row.options]
        assert len(flags) == len(set(flags)), row.name
        assert not {"--json", "--format", "--bank", "--help", "--version"} & set(flags), row.name


def test_cli_only_options_are_not_schema_properties():
    schemas = _schemas()
    for row in cli_map.rows():
        if row.tool:
            props = {"--" + p.replace("_", "-") for p in schemas[row.tool].get("properties", {})}
            assert not props & {o.flag for o in row.options}, row.name


def test_no_generic_dispatcher_row():
    for row in cli_map.rows():
        assert row.name not in {"call", "tool", "run", "exec", "invoke"}
        assert not any(a.prop in {"tool", "name", "arguments"} and a.positional for a in row.args), row.name


def test_slice_one_exposes_its_eight_commands_and_import_only():
    assert {r.name for r in cli_map.exposed()} == {"recall", "get", "project", "continue", "save", "handshake",
                                                   "status", "commands", "import"}
    assert cli_map.exposed_tools() == frozenset({"cicada_recall", "cicada_recall_detail", "cicada_project",
                                                 "cicada_continue", "cicada_save_episode", "cicada_handshake"})


def test_spell_renders_a_command_line_the_parser_accepts():
    import shlex

    from api import cli

    line = cli_map.spell("cicada_continue", session="ep_2026-09-03_001", before="3@abcdef012345")
    assert line == "cicada continue --session ep_2026-09-03_001 --before 3@abcdef012345"
    tricky = cli_map.spell("cicada_save_episode", content="it's $HOME; rm -rf x", title="A b")
    words = shlex.split(tricky)
    args = cli.build_parser().parse_args(words[1:])
    assert args.content == "it's $HOME; rm -rf x" and args.title == "A b"
    assert cli_map.spell("cicada_recall_detail", entity_id=cli_map.Placeholder("entity-id")) == "cicada get <entity-id>"


def test_catalog_lists_every_row_with_its_mirror():
    catalog = cli_map.catalog()
    assert len(catalog) == len(cli_map.rows())
    entry = next(c for c in catalog if c["command"] == "claim add")
    assert entry["mirrors"] == "cicada_write_claim" and entry["mutates"] and not entry["exposed"]
    assert entry["args"][0] == {"property": "subject", "kind": "str", "positional": True}
