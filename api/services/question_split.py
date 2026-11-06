"""Re-judging a question that piled up (question audit A7; owner yes 2026-11-06).

`inbox_generator.merge_options_into` used to fold every later contradiction on a page into the one open question, so a
single question can hold answers about unrelated things. This asks the judge which answers really disagree with which,
and validates the reply. It only proposes: nothing here writes, and the person sees every split before it is applied.
"""

from __future__ import annotations

from pathlib import Path

from api.services import inbox_questions, inbox_tend

VERDICTS = frozenset({"contradiction", "both_true", "same_thing", "alone"})


def real_options(fm: dict) -> list[dict]:
    return [o for o in inbox_questions.normalize_options(fm.get("options"))
            if str(o.get("key")) not in inbox_tend._GENERIC_KEYS and str(o.get("label") or "").strip()]


def is_piled_up(fm: dict) -> bool:
    """A description question holding more than one contradiction's answers."""
    return (str(fm.get("kind") or "") == "conflict" and str(fm.get("predicate") or "description") == "description"
            and len(real_options(fm)) > 2)


def _prompt(memory_path: Path, fm: dict, options: list[dict]) -> str:
    page = inbox_tend._page(memory_path, str(fm.get("entity_id") or ""))
    lines = []
    for o in options:
        pair = f" (raised together with {o.get('raised_with')})" if o.get("raised_with") else ""
        lines.append(f"- {o['key']}{pair}: {o['label']} [{' '.join(str(o.get('description') or '').split())[:300]}]")
    return (
        "A person's memory asked one question, but later readings folded separate disagreements into it, so its "
        "answers are about different things. Sort every answer into groups by what it is actually about.\n\n"
        "Each group gets one verdict:\n"
        "- contradiction: these answers cannot both hold, and only the person can say which does. At least two answers.\n"
        "- both_true: these answers can all hold at once (different facts, different times, a part and its whole).\n"
        "- same_thing: these answers say the same fact in different words.\n"
        "- alone: one answer with nothing here disagreeing with it.\n\n"
        "Answers raised together were read as opposites once, which may have been wrong: judge what they say. Be strict "
        "about contradiction: when two answers could plainly both be true, it is both_true. Every answer key goes in "
        "exactly one group. For a contradiction, write the question a person with no other context can answer, addressed "
        "to them as \"you\", naming what it is about, in plain words, and give each answer a short label a person "
        "would say. Write in the language of the answers.\n\n"
        'Reply JSON {"groups":[{"about":"<a few words>","verdict":"<verdict>","keys":["<key>"],'
        '"question":"<for a contradiction, else null>","labels":{"<key>":"<short label>"},"why":"<one short line>"}]}\n\n'
        f"Subject: {fm.get('entity_name') or fm.get('entity_id')}\n"
        f"The question asked: {fm.get('question') or fm.get('title') or ''}\n"
        "Answers:\n" + "\n".join(lines) + "\n\n"
        f"What the page says now:\n{inbox_tend._page_text(page)}"
    )


def check(reply: dict, options: list[dict]) -> list[dict] | None:
    """The reply's groups when every answer is in exactly one and each group is well formed; otherwise None."""
    groups = reply.get("groups") if isinstance(reply, dict) else None
    if not isinstance(groups, list) or not groups:
        return None
    keys = [str(o["key"]) for o in options]
    seen: list[str] = []
    out = []
    for g in groups:
        if not isinstance(g, dict) or g.get("verdict") not in VERDICTS or not isinstance(g.get("keys"), list):
            return None
        members = [str(k) for k in g["keys"]]
        seen += members
        if g["verdict"] == "contradiction" and (len(members) < 2 or not str(g.get("question") or "").strip()):
            return None
        if g["verdict"] == "alone" and len(members) != 1:
            return None
        out.append({**g, "keys": members})
    return out if sorted(seen) == sorted(keys) else None


async def propose(memory_path: Path, fm: dict, llm_fn) -> tuple[list[dict] | None, str | None]:
    """``(groups or None, model)``. None: the judge's reply did not sort every answer, and the question stays as it is."""
    options = real_options(fm)
    reply, model = await inbox_tend._ask(llm_fn, _prompt(memory_path, fm, options))
    return check(reply, options), model
