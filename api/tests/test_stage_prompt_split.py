"""The merge, contradiction and skills prompts send their fixed rules as a system message (2026-10-16 perf).

Each used to be one user message with the per-call data first, so no two calls shared a prefix an engine's prompt cache
could serve (1 %, 16 % and 0 % of those stages' prompts at owner scale). Now the rules are the system message — the
same bytes every call — and the data the user message. These tests hold the split to the prompts it replaces (frozen
below, as they stood on dev before the change): every line of the old prompt is sent, once, in its order within its
message, with one intended wording change. Since 2026-10-24 the merge asks only for the Summary and the new History
lines (perf report, item 2): its input is still the old one, byte for byte, and its rules keep every date rule.
"""
from __future__ import annotations

import asyncio
import json
from collections import Counter
from types import SimpleNamespace

from api.config import Settings
from api.services import conflict_resolver, skill_extractor

# --- the prompts as they were (dev before 2026-10-16) ---------------------------------------------------------------

OLD_SYNTHESIS = """You are updating an entity page in a personal knowledge graph.

ENTITY: {entity_name} (type: {entity_type})

EXISTING PAGE BODY:
{existing_body}

NEW INFORMATION TO INTEGRATE:
Description: {new_description}
New history entries (JSON): {new_history}
Source episode date: {source_reference_date}

DATES (when things were said, and when this is being written):
Today: {today}
The existing page was last mentioned in a conversation dated: {page_last_referenced}
The new information comes from conversation(s) dated: {source_dates}

INSTRUCTIONS:
1. Merge the new information into the existing page body. The page reads like a short wiki article about this thing as it figures in the person's life.
2. The body is markdown sections in this order: `## Summary`, `## Key Facts`, `## History`, `## Links`, `## Open Questions`. Leave out `## Related` (code rebuilds it). Keep any other section exactly as it is.
3. `## Summary`: one paragraph, 1-3 sentences, at most 600 characters: what it is, what it is to the person (built it, uses it, works with them, is deciding about it) and where it stands as of the latest dated information. Introduce the thing once: never a second sentence that says again what it is. Resolve contradictions by preferring the information with the LATER DATE above — not whichever was read last. When the new information is dated earlier than the existing page, it never replaces the page's later statements. Details belong in `## Key Facts`, not in `## Summary`.
4. `## Key Facts`: keep every existing bullet as written. Add a fact from the new information only when no existing bullet already says it, in any words; one fact per bullet, never two bullets for one fact. Never a bullet about the conversation itself ("was mentioned", "asked about").
5. `## History`: add new dated entries in chronological order. Do not duplicate existing entries. If a new fact contradicts an older fact, the Summary takes the latest dated state and the earlier fact becomes a history bullet (e.g., "2026-03-15: Previously used Postgres, switched to SQLite").
6. Preserve every wikilink ([[Entity Name]]) that appears in the existing body.
7. Preserve specific details — dates, names, numbers.
8. If the new information implies a change over time but the extraction did not provide an explicit dated history entry, you may use the source episode date as the fallback date for that change.
9. Write as of when things were said, never as of today. A statement known only from conversations dated more than 90 days before today names its month and year ("In February 2025, …") and is never presented as current. Plans, intentions and states of mind ("considering", "planning", "interested in", "wants", "hopes") always name the month and year they were stated. Keep every date already written on the page. Never write "currently", "now", "recently", "this week" or "soon".

SUMMARY LENGTH (by entity type): skill 1 sentence; person, tool, concept, location 1-2 sentences; project, company 2-3 sentences.

Output ONLY the updated markdown body. Do not include YAML frontmatter, do not wrap in code fences, do not add commentary."""

OLD_CONTRADICTION = """You are checking whether two descriptions of the same entity contain an unresolvable contradiction.

A contradiction is unresolvable when newer information alone does not make it obvious which statement is currently true. For example: two different stacks mentioned across two conversations with no date cue, or two different roles for the same person.

"Newer" means said on a later date (below), not read later: a description from an earlier conversation does not replace a later one, and two statements made months apart can both have been true at their own dates.

TODAY: {today}

ENTITY: {entity_name}

EXISTING DESCRIPTION (last mentioned in a conversation dated {existing_as_of}):
{existing_body}

NEW DESCRIPTION (from conversation(s) dated {new_as_of}):
{new_description}

Respond with JSON only:
{{
  "has_unresolvable_contradiction": true | false,
  "contradiction": "one-sentence description of the contradiction, or empty",
  "question": "ONE short question, in the user's voice, that resolves it (e.g. 'Where does the owner work now?'). Empty when there is no contradiction.",
  "options": [
    {{"label": "the existing claim, 1-4 words", "description": "one short clause saying where this came from and when"}},
    {{"label": "the new claim, 1-4 words", "description": "one short clause saying where this came from and when"}},
    {{"label": "Both are true (different contexts)", "description": "Keep both, each tagged with its context"}}
  ]
}}

If there is no contradiction, set has_unresolvable_contradiction to false, question to "", and options to []."""

OLD_SKILLS = """You are analyzing patterns in a personal knowledge graph to extract procedural skills and preferences.

ENTITY CHANGES THIS CYCLE:
{changes}

FREQUENTLY CO-OCCURRING ENTITIES (appeared together in 3+ conversations):
{cooccurrences}

RELATED EXISTING ENTITIES:
{existing}

Look for:
1. WORKFLOW PATTERNS — recurring sequences of actions or tools used together.
   Example: "Always checks GitHub before answering questions about projects."
2. PREFERENCE PATTERNS — consistent choices or styles across conversations.
   Example: "Prefers concise summaries over detailed explanations."
3. RELATIONSHIP PATTERNS — entities that are consistently discussed together.
   Example: "Career conversations always involve both the current employer and the field."

Output valid JSON:
{{
  "skills": [
    {{
      "name": "Descriptive Skill Name",
      "description": "1-2 sentence procedural description written as an instruction or observation",
      "evidence_entities": ["Entity A", "Entity B"],
      "confidence": 0.7
    }}
  ]
}}

Only extract skills with clear evidence from multiple conversations. Do not speculate. If there is no strong pattern, return {{"skills": []}}."""


#: The one wording change: the rule's "above" pointed at dates that now arrive after it, in the user message.
RENAMED = {"preferring the information with the LATER DATE above": "preferring the information with the LATER DATE "
                                                                  "(under DATES)"}


def _lines(text: str) -> list[str]:
    out = []
    for line in text.splitlines():
        for old, new in RENAMED.items():
            line = line.replace(old, new)
        if line.strip():
            out.append(line)
    return out


def _in_order(part: list[str], whole: list[str]) -> bool:
    it = iter(whole)
    return all(any(line == w for w in it) for line in part)


def _capture(monkeypatch, module, reply: str) -> list[list[dict]]:
    calls: list[list[dict]] = []

    async def fake_acompletion(**kw):
        calls.append(kw["messages"])
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=reply))])

    monkeypatch.setattr(module.litellm, "acompletion", fake_acompletion)
    return calls


def _assert_same_prompt(messages: list[dict], old_prompt: str) -> None:
    assert [m["role"] for m in messages] == ["system", "user"]
    system, user = _lines(messages[0]["content"]), _lines(messages[1]["content"])
    old = _lines(old_prompt)
    assert Counter(system + user) == Counter(old), "every line once, nothing added"
    assert _in_order(system, old) and _in_order(user, old), "each message keeps the old order"


SETTINGS = dict(_env_file=None, litellm_model="gpt-5.4-mini")


def _merge(name: str, body: str, desc: str, day: str):
    return conflict_resolver._synthesize_entity_update(
        entity_name=name, entity_type="company", existing_body=body, new_description=desc,
        new_history_entries=[{"date": day, "text": "Moved office."}], source_reference_date=day,
        settings=Settings(**SETTINGS), page_last_referenced="2025-02-06", source_dates_seen=[day], today="2026-10-07")


#: The merge rules every date rule of the old prompt kept word for word (perf report 2026-10-24, item 2: the merge now
#: asks only for the Summary and the new History lines, so the body-shape rules went and these stayed).
KEPT_MERGE_RULES = (
    "at most 600 characters: what it is, what it is to the person (built it, uses it, works with them, is deciding "
    "about it) and where it stands as of the latest dated information.",
    "Resolve contradictions by preferring the information with the LATER DATE (under DATES) — not whichever was read "
    "last. When the new information is dated earlier than the existing page, it never replaces the page's later "
    "statements.",
    "the earlier fact becomes a history entry (e.g., \"2026-03-15: Previously used Postgres, switched to SQLite\")",
    "Preserve specific details — dates, names, numbers.",
    "If the new information implies a change over time but the extraction did not provide an explicit dated history "
    "entry, you may use the source episode date as the fallback date for that change.",
    "Write as of when things were said, never as of today. A statement known only from conversations dated more than "
    "90 days before today names its month and year (\"In February 2025, …\") and is never presented as current. Plans, "
    "intentions and states of mind (\"considering\", \"planning\", \"interested in\", \"wants\", \"hopes\") always name "
    "the month and year they were stated. Keep every date already written on the page. Never write \"currently\", "
    "\"now\", \"recently\", \"this week\" or \"soon\".",
    "SUMMARY LENGTH (by entity type): skill 1 sentence; person, tool, concept, location 1-2 sentences; project, "
    "company 2-3 sentences.",
)


def test_the_merge_prompt_keeps_its_input_and_asks_only_for_the_kept_parts(monkeypatch):
    from api.services import owner_identity

    monkeypatch.setattr(owner_identity, "owner_name", lambda *a, **k: "Owner Example")
    calls = _capture(monkeypatch, conflict_resolver, json.dumps({"summary": "Merged.", "history": []}))
    asyncio.run(_merge("Alpha Co", "## Summary\nAlpha Co runs a programme.", "Alpha Co moved office.", "2026-09-30"))
    asyncio.run(_merge("Beta Tool", "## Summary\nBeta Tool parses files.", "Beta Tool is faster.", "2026-08-01"))
    for messages, (name, body, desc, day) in zip(calls, [
            ("Alpha Co", "## Summary\nAlpha Co runs a programme.", "Alpha Co moved office.", "2026-09-30"),
            ("Beta Tool", "## Summary\nBeta Tool parses files.", "Beta Tool is faster.", "2026-08-01")]):
        old = OLD_SYNTHESIS.format(
            entity_name=name, entity_type="company", existing_body=body, new_description=desc,
            new_history=json.dumps([{"date": day, "text": "Moved office."}]), source_reference_date=day,
            today="2026-10-07", page_last_referenced="2025-02-06", source_dates=day)
        old_input = old[old.index("ENTITY:"):old.index("INSTRUCTIONS:")].strip()
        old_input += conflict_resolver._owner_line("Owner Example")
        assert [m["role"] for m in messages] == ["system", "user"]
        assert messages[1]["content"] == old_input, "the page and its new information are sent as before"
        assert messages[0]["content"] == conflict_resolver._SYNTHESIS_RULES
    assert calls[0][0] == calls[1][0], "the rules are byte-identical across calls: cacheable"
    rules = conflict_resolver._SYNTHESIS_RULES
    for kept in KEPT_MERGE_RULES:
        assert kept in rules, kept
    assert "Output ONLY the updated markdown body" not in rules
    assert rules.rstrip().endswith('{"summary": "the new summary paragraph", "history": ["YYYY-MM-DD: what happened"]}')


def test_the_contradiction_prompt_is_the_old_prompt_in_two_messages(monkeypatch):
    calls = _capture(monkeypatch, conflict_resolver, json.dumps({"has_unresolvable_contradiction": False}))
    for name in ("Alpha Co", "Beta Tool"):
        asyncio.run(conflict_resolver._detect_contradiction(
            entity_name=name, existing_body=f"{name} is old.", new_description=f"{name} is new.",
            settings=Settings(**SETTINGS), existing_as_of="2026-09-30", new_as_of=["2025-02-04"], today="2026-10-07"))
    for messages, name in zip(calls, ("Alpha Co", "Beta Tool")):
        old = OLD_CONTRADICTION.format(entity_name=name, existing_body=f"{name} is old.",
                                       new_description=f"{name} is new.", today="2026-10-07",
                                       existing_as_of="2026-09-30", new_as_of="2025-02-04")
        _assert_same_prompt(messages, old)
    assert calls[0][0] == calls[1][0]


def test_the_skills_prompt_is_the_old_prompt_in_two_messages(monkeypatch):
    calls = _capture(monkeypatch, skill_extractor, json.dumps({"skills": []}))
    changes = [{"id": "alpha-co", "action": "update",
                "entity": {"name": "Alpha Co", "type": "company", "description": "Alpha Co moved office."}}]
    asyncio.run(skill_extractor.detect_patterns(changes, [], Settings(**SETTINGS),
                                                {"ep1": ["Alpha Co", "Beta Tool"]}))
    [messages] = calls
    old = OLD_SKILLS.format(changes=skill_extractor._format_changes(changes),
                            cooccurrences=skill_extractor._format_cooccurrences({}),
                            existing=skill_extractor._format_existing([], changes))
    _assert_same_prompt(messages, old)
    assert messages[0]["content"] == skill_extractor.SKILL_DETECTION_RULES
