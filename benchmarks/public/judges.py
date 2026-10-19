"""The published judging protocols, verbatim, plus LoCoMo's token F1 (standard library only).

- **LoCoMo — the "J" score** (LLM-as-a-Judge, Mem0's paper appendix A, arXiv:2504.19413): the one Mem0, Zep, Letta
  and most 2025–26 LoCoMo numbers report. Binary CORRECT/WRONG, deliberately generous ("as long as it touches on the
  same topic"). Category 5 (adversarial) is excluded by every published J number — 444 of its 446 items have no
  ``answer`` — so this harness scores it separately, with LoCoMo's own rule (the answer says the thing is not
  mentioned / no information), never folded into the headline.
- **LoCoMo — token F1** (``snap-research/locomo`` ``task_eval/evaluation.py``): the original metric, reported beside
  J. Porter stemming when ``nltk`` is importable, else none — the report names which.
- **LongMemEval** (``xiaowu0162/LongMemEval`` ``src/evaluation/evaluate_qa.py``): one yes/no prompt per question type
  and one for abstention; ``'yes' in reply.lower()`` is the label, as in the original script.

The prompts are copied character for character; only the judge model differs from the papers (it runs on the
person's plan). The report always names the judge model.
"""
from __future__ import annotations

import json
import re
import string
from collections import Counter

# --------------------------------------------------------------------------------------------------------------- #
# Mem0's LLM-as-a-Judge (LoCoMo J)
# --------------------------------------------------------------------------------------------------------------- #

MEM0_JUDGE_PROMPT = """Your task is to label an answer to a question as "CORRECT" or "WRONG".
You will be given the following data:
(1) a question (posed by one user to another user),
(2) a ‘gold’ (ground truth) answer,
(3) a generated answer
which you will score as CORRECT/WRONG.

The point of the question is to ask about something one user should know about the other user based on their prior conversations.
The gold answer will usually be a concise and short answer that includes the referenced topic, for example:

Question: Do you remember what I got the last time I went to Hawaii?

Gold answer: A shell necklace

The generated answer might be much longer, but you should be generous with your grading - as long as it touches on the same topic as the gold answer, it should be counted as CORRECT.

For time related questions, the gold answer will be a specific date, month, year, etc. The generated answer might be much longer or use relative time references (like ‘last Tuesday’ or ‘next month’), but you should be generous with your grading - as long as it refers to the same date or time period as the gold answer, it should be counted as CORRECT. Even if the format differs (e.g., ‘May 7th’ vs ‘7 May’), consider it CORRECT if it’s the same date.

Now it’s time for the real question:

Question: {question}

Gold answer: {gold_answer}

Generated answer: {generated_answer}

First, provide a short (one sentence) explanation of your reasoning, then finish with CORRECT or WRONG.
Do NOT include both CORRECT and WRONG in your response, or it will break the evaluation script.

Just return the label CORRECT or WRONG in a json format with the key as "label"."""


def mem0_prompt(question: str, gold: str, generated: str) -> str:
    return MEM0_JUDGE_PROMPT.format(question=question, gold_answer=gold, generated_answer=generated)


def parse_mem0(reply: str) -> bool | None:
    """The label from the judge's reply: the JSON ``label`` when present, else the one word it used."""
    text = str(reply or "")
    for match in re.finditer(r"\{[^{}]*\}", text):
        try:
            label = str(json.loads(match.group(0)).get("label", "")).strip().upper()
        except (ValueError, AttributeError):
            continue
        if label in ("CORRECT", "WRONG"):
            return label == "CORRECT"
    upper = text.upper()
    # Whole words: "The answer is incorrect." must never read as CORRECT.
    has_c, has_w = bool(re.search(r"\bCORRECT\b", upper)), bool(re.search(r"\bWRONG\b", upper))
    if has_c != has_w:
        return has_c
    return None


# --------------------------------------------------------------------------------------------------------------- #
# LongMemEval's per-type judge prompts (evaluate_qa.py, get_anscheck_prompt)
# --------------------------------------------------------------------------------------------------------------- #

_LME_BASE = ("I will give you a question, a correct answer, and a response from a model. Please answer yes if the "
             "response contains the correct answer. Otherwise, answer no. If the response is equivalent to the correct "
             "answer or contains all the intermediate steps to get the correct answer, you should also answer yes. If "
             "the response only contains a subset of the information required by the answer, answer no. ")
LME_TEMPLATES = {
    "default": _LME_BASE + "\n\nQuestion: {}\n\nCorrect Answer: {}\n\nModel Response: {}\n\nIs the model response "
                           "correct? Answer yes or no only.",
    "temporal-reasoning": _LME_BASE + "In addition, do not penalize off-by-one errors for the number of days. If the "
                          "question asks for the number of days/weeks/months, etc., and the model makes off-by-one "
                          "errors (e.g., predicting 19 days when the answer is 18), the model's response is still "
                          "correct. \n\nQuestion: {}\n\nCorrect Answer: {}\n\nModel Response: {}\n\nIs the model "
                          "response correct? Answer yes or no only.",
    "knowledge-update": "I will give you a question, a correct answer, and a response from a model. Please answer yes "
                        "if the response contains the correct answer. Otherwise, answer no. If the response contains "
                        "some previous information along with an updated answer, the response should be considered as "
                        "correct as long as the updated answer is the required answer.\n\nQuestion: {}\n\nCorrect "
                        "Answer: {}\n\nModel Response: {}\n\nIs the model response correct? Answer yes or no only.",
    "single-session-preference": "I will give you a question, a rubric for desired personalized response, and a "
                                 "response from a model. Please answer yes if the response satisfies the desired "
                                 "response. Otherwise, answer no. The model does not need to reflect all the points in "
                                 "the rubric. The response is correct as long as it recalls and utilizes the user's "
                                 "personal information correctly.\n\nQuestion: {}\n\nRubric: {}\n\nModel Response: {}"
                                 "\n\nIs the model response correct? Answer yes or no only.",
    "abstention": "I will give you an unanswerable question, an explanation, and a response from a model. Please answer "
                  "yes if the model correctly identifies the question as unanswerable. The model could say that the "
                  "information is incomplete, or some other information is given but the asked information is not."
                  "\n\nQuestion: {}\n\nExplanation: {}\n\nModel Response: {}\n\nDoes the model correctly identify the "
                  "question as unanswerable? Answer yes or no only.",
}
_LME_DEFAULT_TYPES = ("single-session-user", "single-session-assistant", "multi-session")


def lme_prompt(task: str, question: str, answer: str, response: str, *, abstention: bool) -> str:
    if abstention:
        key = "abstention"
    elif task in _LME_DEFAULT_TYPES:
        key = "default"
    elif task in LME_TEMPLATES:
        key = task
    else:
        raise ValueError(f"no LongMemEval judge prompt for question type {task!r}")
    return LME_TEMPLATES[key].format(question, answer, response)


def parse_lme(reply: str) -> bool:
    """The original script's rule, unchanged: ``'yes' in reply.lower()``."""
    return "yes" in str(reply or "").lower()


# --------------------------------------------------------------------------------------------------------------- #
# LoCoMo's token F1 (task_eval/evaluation.py)
# --------------------------------------------------------------------------------------------------------------- #

try:  # the original stems with nltk's Porter stemmer; the venv may not have it
    from nltk.stem import PorterStemmer as _Porter  # type: ignore

    _stem = _Porter().stem
    STEMMER = "porter"
except Exception:  # noqa: BLE001
    def _stem(word: str) -> str:
        return word

    STEMMER = "none"


def _normalize(s: str) -> str:
    s = str(s).replace(",", "").lower()
    s = "".join(ch for ch in s if ch not in set(string.punctuation))
    s = re.sub(r"\b(a|an|the|and)\b", " ", s)
    return " ".join(s.split())


def f1_score(prediction: str, truth: str) -> float:
    pred = [_stem(w) for w in _normalize(prediction).split()]
    gold = [_stem(w) for w in _normalize(truth).split()]
    same = sum((Counter(pred) & Counter(gold)).values())
    if same == 0:
        return 0.0
    precision, recall = same / len(pred), same / len(gold)
    return 2 * precision * recall / (precision + recall)


def locomo_f1(prediction: str, answer: str, category_id: int) -> float:
    """LoCoMo's per-category F1 rule, as ``eval_question_answering`` applies it."""
    answer = str(answer)
    if category_id == 3:
        answer = answer.split(";")[0].strip()
    if category_id in (2, 3, 4):
        return f1_score(prediction, answer)
    if category_id == 1:
        preds = [p.strip() for p in str(prediction).split(",")]
        golds = [g.strip() for g in answer.split(",")]
        return sum(max(f1_score(p, g) for p in preds) for g in golds) / len(golds)
    if category_id == 5:
        low = str(prediction).lower()
        return 1.0 if ("no information available" in low or "not mentioned" in low) else 0.0
    raise ValueError(f"unknown LoCoMo category {category_id}")
