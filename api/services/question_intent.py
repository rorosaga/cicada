"""What a question asks for, in any language, with no word list and no model call (2026-11-06, G148).

A question is compared, by the search model already on this machine, with a few example questions of each kind. The
model is multilingual, so the examples are written once. The word lists beside this in ``ask_sources`` see English and
Spanish only: on questions translated into nine other languages they found 0 of 30 requests for advice. This finds 16 to
26 of the 30 over 11 languages, and 12 false alarms over 2,456 English questions from two public benchmarks. A question
recalling a recommendation already given ("what advice did she give him?") is a question of fact, so the "other" examples
hold those; without them it was 42 false alarms, most of that shape.

A question read as advice gets more lines by meaning and ``ask_service._ADVICE_NOTE``. With no model on this machine it
says no, and the question goes on with the usual retrieval and no note.

"What has come up lately?" (owner, 2026-11-06) names no subject, so no word finds its answer: :func:`asks_lately` reads
it the same way and ``ask_sources.search`` hands over the newest conversations.
"""
from __future__ import annotations

import numpy as np
from loguru import logger

#: The mean of a kind's nearest examples counts, so one lucky example doesn't decide.
NEAREST = 3
#: How far advice must beat the other kinds: it only has to be the nearest. With the "other" examples that recall a past
#: recommendation, measured over 150 translated questions and 2,456 English ones (`mcp.md`); it is not a tuned optimum.
ADVICE_MARGIN = 0.0
#: How far "what's come up lately" must beat every other kind when the question has a subject of its own, so it costs some
#: of the window. Measured on held-out questions: `mcp.md`.
LATELY_MARGIN = 0.02

EXAMPLES: dict[str, list[str]] = {
    "advice": ["Can you recommend something for me?", "Any tips for this?", "What should I do about it?",
               "Could you suggest a few options for me?", "Do you have any advice?",
               "Give me some ideas for this weekend.", "What would you suggest I try next?",
               "I need some help choosing one, any suggestions?"],
    "count": ["How many times did I do that?", "How many of them do I have?", "What is the total I spent on it?",
              "List everything I did.", "What are all the things I bought?", "Which places have I been to?",
              "How much did I spend altogether?", "What activities has she done?", "What books has he read?",
              "What are her hobbies?", "How many days did it take in total?", "Where has she traveled?"],
    "other": ["When did I do that?", "What is my sister's name?", "Where did I go last year?",
              "What did I say about it?", "Why did he leave?", "Who told me about it?",
              "What was the name of the place?", "Did I finish it?", "What did she decide to do?",
              "Which one did I pick?", "How long ago was it?", "What is his job?",
              "What advice did she give him?", "What did he recommend to her?", "What did you suggest last time?",
              "Can you remind me what you recommended?", "What suggestion did they give?",
              "What is my preferred one?"],
    "lately": ["What has been happening lately?", "What's new?", "What have I been up to recently?",
               "Catch me up on recent things.", "What has come up a lot this week?",
               "Who have I been talking to recently?", "What's on my mind these days?",
               "Give me a recap of the last few days."],
    # A dated fact about one subject: only the "lately" question is compared with these. The advice one is not.
    "dated": ["What did she do recently?", "What did he buy last week?", "What is the latest on that project?",
              "When did I last see her?", "What has Maria been doing lately?", "What did I start recently?"],
}


def _scores(indexer, question: str) -> dict[str, float] | None:
    """Each kind's nearness to ``question``; ``None`` with no model on this machine. Never raises; never logs the text."""
    if indexer is None or not (question or "").strip():
        return None
    try:
        near = indexer.nearness(question, EXAMPLES)
    except Exception as exc:  # noqa: BLE001 — a ranking aid; its absence never fails an answer
        logger.debug(f"question intent skipped ({type(exc).__name__})")
        return None
    return {kind: float(np.sort(values)[-NEAREST:].mean()) for kind, values in near.items()}


def asks_advice(indexer, question: str) -> bool:
    """The person asks for a recommendation or advice, not a recorded fact."""
    scores = _scores(indexer, question)
    return scores is not None and scores["advice"] - max(scores["count"], scores["other"]) > ADVICE_MARGIN


def asks_lately(indexer, question: str, *, no_subject: bool = False) -> bool:
    """The person asks what has come up lately, about no subject in particular. ``no_subject``: no word of the question
    is the record's, so there is nothing to lose and being the nearest is enough."""
    scores = _scores(indexer, question)
    if scores is None:
        return False
    margin = scores["lately"] - max(v for kind, v in scores.items() if kind != "lately")
    return margin > (0.0 if no_subject else LATELY_MARGIN)
