"""Owner rule, 2026-09-30: "ollama and the rest are literally just providers. So dont assume or make
the choice for the user." Reading copy describes the step, never a provider, model or agent product as
the one doing a job. A name may appear only where it shows the person's own current choice or a recorded
fact — never in the copy scanned here.

The scan is of what an agent or a person is TOLD: the reading constants, the hand-off prompts, the hook
sentence, contract item 9 in both voices, the two reading tools' descriptions, and every non-docstring
string in the reading modules. Fixture data in other tests, the per-harness handshake prelude and the
catalog's skill names (data the person picked) are outside it, by construction."""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from _reading_fixtures import PUBLIC, WALLED, ask, enable, put_page, reading  # noqa: F401 — `reading` is a fixture
from _reading_fixtures import record
from _stdio_server import stdio_server
from api.remote import tools as remote_tools
from api.services import agent_methods, handshake, mcp_tools, reading_hosts, reading_prompt, recall_text

ROOT = Path(__file__).resolve().parents[2]
BANNED = re.compile(
    r"ollama|claude plan|chatgpt plan|your claude|haiku|\bopus\b|sonnet|gpt-|gemma|browser-harness|browser harness"
    r"|macos-harness|claude in chrome|claude code|\bcodex\b|chatgpt|\bcursor\b|gemini|openrouter|\banthropic\b|\bopenai\b",
    re.IGNORECASE)

#: Modules whose non-docstring strings are all reading copy.
MODULES = (
    "api/services/reading_prompt.py", "api/services/reading_settings.py", "api/services/reading_hosts.py",
    "api/services/reading_walls.py", "api/services/reading_queue.py", "api/services/reading_service.py",
    "api/services/reading_asks.py", "api/routers/reading.py", "api/services/agent_methods.py",
    "api/services/page_read.py", "api/services/hook_recall.py",
)


def _strings(path: str):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant):
                docstrings.add(id(body[0].value))
    for node in ast.walk(tree):
        # a host name or a path in a closed list (the vendor hosts a link is refused for) is data, not copy:
        # copy has a space in it
        if (isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings
                and " " in node.value):
            yield node.lineno, node.value


@pytest.mark.parametrize("path", MODULES)
def test_reading_modules_name_no_provider_or_product_in_any_string(path):
    hits = [(line, text) for line, text in _strings(path) if BANNED.search(text)]
    assert not hits, f"{path}: {hits}"


def _tool_text(name: str) -> list[str]:
    stdio = next(t for t in stdio_server().TOOLS if t["name"] == name)
    remote = remote_tools.REMOTE_TOOLS[name]
    out = []
    for definition in (stdio, remote):
        out.append(definition["description"])
        props = (definition.get("inputSchema") or {}).get("properties", {})
        out.extend(str(p.get("description", "")) for p in props.values())
    return out


@pytest.mark.parametrize("name", ["cicada_reading_queue", "cicada_record_read"])
def test_the_reading_tool_descriptions_are_neutral(name):
    for text in _tool_text(name):
        assert not BANNED.search(text), (name, text)


def test_prompts_notes_and_contract_item_are_neutral():
    samples = [
        reading_prompt.RULES, reading_prompt.queue_prompt(), reading_prompt.ask_prompt("https://blog.example.net/a"),
        recall_text.reading_line(1), recall_text.reading_line(3, record=False),
        handshake._READING_ITEM,
        handshake._remote_reading_item(frozenset({"cicada_reading_queue", "cicada_record_read"})),
        handshake._remote_reading_item(frozenset({"cicada_reading_queue"})),
        handshake._remote_reading_item(frozenset({"cicada_record_read"})),
        mcp_tools._READING_OFF, *reading_hosts._REFUSAL.values(), *reading_hosts.SITE_NOTES.values(),
        agent_methods.AUTO_TITLE, agent_methods.AUTO_DETAIL,
        *(v for job in agent_methods.JOBS.values() for v in (job.question, job.own_title, job.own_detail)),
        *agent_methods._PERSON.values(), *agent_methods._REPLY.values(),
        *(j.person_skill for j in agent_methods.JOBS.values() if j.person_skill),
        *(line for triple in agent_methods._LINES.values() for line in triple),
    ]
    for text in samples:
        assert text and not BANNED.search(text), text


def test_the_built_in_choices_name_no_product_whatever_the_person_chose():
    """The clause for the agent's own tools, and the method lines, are neutral; a skill's name is
    catalog data the person picked and is filled at runtime."""
    for line in (agent_methods._PERSON[agent_methods.OWN], agent_methods._REPLY[agent_methods.OWN]):
        assert not BANNED.search(line)
    templates = [agent_methods._PERSON["skill"], agent_methods._REPLY["skill"],
                 *(j.person_skill for j in agent_methods.JOBS.values() if j.person_skill),
                 *(triple[2] for triple in agent_methods._LINES.values())]
    for template in templates:
        assert not BANNED.search(template.format(name="`a-skill`", invoke="a-skill", via_arg="via"))


def test_what_the_two_reading_tools_actually_say_is_neutral(reading):  # noqa: F811
    """The scan above reads source strings; this runs the tools on a fixture bank and scans their replies,
    so a name added to the queue head or to any record outcome cannot pass. A skill the person picked is
    catalog data, so the choices scanned are the two that name none."""
    server, memory = reading
    art = "https://articles.paperfold.io/post/{}"
    put_page(memory, "w1", art.format(1), fetch_status="blocked")
    put_page(memory, "w2", art.format(2), fetch_status="blocked")
    put_page(memory, "w3", art.format(3), fetch_status="blocked")
    ask(memory, PUBLIC)
    ask(memory, WALLED)
    enable(sites=("paperfold.io",))
    replies = []
    for chosen in ("auto", "own"):
        agent_methods.set_choice("reading", chosen)
        replies.append(server.handle_tool("cicada_reading_queue", {}))
        replies.append(server.handle_tool("cicada_reading_queue", {"limit": 1}))
    replies.append(record(server, url=PUBLIC))                                      # read
    for outcome in ("needs_login", "blocked", "failed"):
        replies.append(record(server, url=WALLED, outcome=outcome))
    replies.append(record(server, url=art.format(1), outcome="needs_login"))        # a site entry
    replies.append(record(server, url=art.format(2)))                               # a site read
    replies.append(record(server, url="https://never-saved.example.net/x"))         # not on the list
    replies.append(record(server, url=PUBLIC, outcome="nonsense"))                  # bad outcome
    replies.append(record(server, url="http://localhost:9/x", outcome="failed"))    # a denied class
    for text in replies:
        assert text and not BANNED.search(text), text


def test_the_reading_queue_is_neutral_when_the_person_chose_a_skill_apart_from_its_own_name(reading):  # noqa: F811
    """The chosen skill's name is the person's own choice and may appear, once and as that choice; nothing
    else in the reply names a provider."""
    server, memory = reading
    ask(memory, PUBLIC)
    agent_methods.set_choice("reading", "browser-harness")
    out = server.handle_tool("cicada_reading_queue", {})
    assert not BANNED.search(out.replace("browser-harness", "the-skill")), out
