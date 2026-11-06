"""What a question asks for, in any language, with no word list and no model call (2026-11-06, G148).

A question is compared, by the search model already on this machine, with a few example questions of each kind. The
model is multilingual, so the examples are written once. The word lists beside this in ``ask_sources`` see English and
Spanish only: on questions translated into nine other languages they found 0 of 30 requests for advice. Over 11
languages this finds 19 to 26 of the 30, and 42 false alarms over 2,456 English questions from two public benchmarks.

Only retrieval leans on it, and a false alarm costs a few more lines in a prompt. What the question means for the answer
is the answering model's to judge (rule 13 of ``ASK_SYSTEM_PROMPT``). With no model on this machine it says no: the
answer's rule still holds, with the usual retrieval.
"""
from __future__ import annotations

import numpy as np
from loguru import logger

#: The mean of a kind's nearest examples counts, so one lucky example doesn't decide.
NEAREST = 3
#: How far advice must beat the other kinds. 0.02 was chosen on the translated sample; it is not a tuned optimum.
ADVICE_MARGIN = 0.02

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
              "Which one did I pick?", "How long ago was it?", "What is his job?"],
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
