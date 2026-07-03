import importlib

mcp = importlib.import_module("mcp.server")


def test_recall_description_has_grounding_and_detail_guidance():
    # Build the tools list the server advertises and find cicada_recall.
    # main() defines `tools`; expose it via a module-level TOOLS for testing.
    tools = {t["name"]: t for t in mcp.TOOLS}
    desc = tools["cicada_recall"]["description"].lower()
    assert "recall_detail" in desc            # tells model to read full page
    assert "only" in desc and "tool" in desc  # grounding: state only facts from tools


def test_ask_description_prefers_tool_for_factual_questions():
    tools = {t["name"]: t for t in mcp.TOOLS}
    desc = tools["cicada_ask"]["description"].lower()
    assert "prefer this tool for direct factual questions" in desc
