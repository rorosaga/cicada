"""R-PJ18 / R-PJB13: the app's writes are the person's, and only the app can say so."""
import inspect
import re
from pathlib import Path

from _stdio_server import stdio_server
from api.remote import tools as remote_tools
from api.services import claim_reconciler, mcp_tools

REPO = Path(__file__).resolve().parents[2]
SETS_ORIGIN = re.compile(r"""origin\s*=\s*["']companion_app["']""")


def test_companion_app_is_a_human_origin():
    assert claim_reconciler._HUMAN_ORIGINS == {"manual_edit", "clarification", "companion_app"}


def test_only_the_projects_router_and_the_demo_set_it():
    hits = sorted(p.relative_to(REPO).as_posix() for root in ("api", "mcp") for p in (REPO / root).rglob("*.py")
                  if ".venv" not in p.parts and "tests" not in p.parts
                  and SETS_ORIGIN.search(p.read_text(encoding="utf-8")))
    assert hits == ["api/routers/projects.py", "api/services/demo_bank.py"], hits


def test_no_mcp_tool_takes_an_origin():
    for t in stdio_server().TOOLS:
        assert "origin" not in t["inputSchema"].get("properties", {}), t["name"]
    for name, t in remote_tools.REMOTE_TOOLS.items():
        assert "origin" not in t["inputSchema"]["properties"], name
    for name, fn in inspect.getmembers(mcp_tools, inspect.isfunction):
        if not name.startswith("_") and fn.__module__ == mcp_tools.__name__:
            assert "origin" not in inspect.signature(fn).parameters, name


def test_an_agent_done_on_the_persons_milestone_coexists_with_a_divergence(tmp_path):
    from datetime import date

    from _synthetic_bank import _bank
    from api.services import markdown_parser, owner_identity, progress
    from api.services.claims import parse_claims

    memory = _bank(tmp_path, git=False)
    owner = owner_identity.resolve_observer(memory, None)
    day = date(2026, 9, 23)
    progress.set_milestone(memory, subject="alpha-project", name="First grasp", target="2026-10-01",
                           observer=owner, origin="companion_app", authored_by="user", date_basis="person", today=day)
    before = {p.name for p in (memory / "inbox").glob("inbox-*.md")}
    out = progress.advance(memory, subject="alpha-project", slug="first-grasp", status="done", observer="agent",
                           origin="mcp", authored_by="claude-code", date_basis="written", today=day)
    heads = [c for c in parse_claims(markdown_parser.parse(memory / "entities" / "alpha-project.md").body)
             if c.predicate == "milestone" and c.valid_to is None]
    assert {(c.status, c.origin) for c in heads} == {("planned", "companion_app"), ("done", "mcp")}
    new = [p for p in (memory / "inbox").glob("inbox-*.md") if p.name not in before]
    assert len(new) == 1 and markdown_parser.parse(new[0]).frontmatter["kind"] == "divergence"
    assert any(p.startswith("inbox/") for p in out["paths"])
