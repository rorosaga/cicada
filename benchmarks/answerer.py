"""LLM answer synthesis over retrieved context.

Identical prompt for both Condition A and Condition B, so the only thing
that differs between the two runs is the context that comes from the
retrieval layer. This keeps the comparison honest.

Synchronous on purpose — the Table 1 runner is single-threaded and
running one question at a time keeps the rate-limit math trivial and
lets a Ctrl-C interrupt land cleanly.
"""
from __future__ import annotations

import litellm


ANSWER_SYSTEM_PROMPT = """You are answering a question about the user's own life and work using only the memory excerpts provided below. Follow these rules strictly:

1. Answer concisely and directly. No preamble, no meta-commentary about the excerpts.
2. Only use information that is explicitly present in the excerpts. Do NOT invent names, dates, organizations, or facts.
3. If the excerpts do not contain enough information to answer the question, say so explicitly with a single short sentence: "I do not have enough information to answer this."
4. If multiple excerpts disagree, briefly note the disagreement rather than picking one silently.
5. If the question is about what the user should do next, base the recommendation only on what the excerpts say. Do not speculate beyond them.
"""


def synthesize_answer(
    question: str,
    context: str,
    model: str = "openai/gpt-4o-mini",
    temperature: float = 0.0,
) -> str:
    """Return a single answer string. Never raises — wraps errors inline."""
    user_prompt = (
        f"Question: {question}\n\n"
        f"Memory excerpts:\n{context}\n\n"
        f"Answer:"
    )
    try:
        response = litellm.completion(
            model=model,
            messages=[
                {"role": "system", "content": ANSWER_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
        )
        text = response.choices[0].message.content or ""
        return text.strip()
    except Exception as e:
        return f"(LLM synthesis failed: {type(e).__name__}: {e})"
