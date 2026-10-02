"""The one tag that tells an installed agent skill's page from a procedural memory (G166).

Both are ``type: skill`` pages: Stage 1 and Stage 4 write "procedural rule or
preference, written as an instruction" pages of that type, and the owner asked
for an installed skill (browser-harness, macos-harness, claude-video) to be a
``skill`` page in the graph too. The two are told apart by this tag, the way
``WORKING_TAGS`` marks other working pages — no new frontmatter key, no schema
change, and a hand edit that drops the tag only makes the page an ordinary
skill page. Dependency-free on purpose: ``state_dictionary`` (which must not
list an installed tool under "How to work with me") and ``skill_pages`` (the one
writer) both import it.
"""
from __future__ import annotations

AGENT_SKILL_TAG = "agent-skill"


def is_agent_skill(fm: dict | None) -> bool:
    tags = (fm or {}).get("tags")
    return isinstance(tags, (list, tuple)) and AGENT_SKILL_TAG in tags
