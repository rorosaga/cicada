"""Why a metered engine refused Sleep's calls, in the person's words.

A provider that refuses a call says why in its exception text — "Key limit exceeded
(total limit)", "Incorrect API key", "No endpoints found for <model>", "Rate limit
exceeded". Sleep used to bury that under one generic sentence ("check the model id,
and that the key still has credit"), so a key that had simply reached its own
spending cap read like a misconfiguration. This module turns the provider's words
into one of four causes and says the fix for each.

Only class names and text: stdlib imports, no provider SDK, never the exception text
itself on the wire (it can carry a URL or an account id). Copy is provider-neutral —
"the provider", "the API key" — per the owner's 2026-09-30 rule.
"""
from __future__ import annotations

import re

#: The causes this module can name (a closed set). ``None`` is "the provider did not say".
CAUSES = ("spending_limit", "auth", "model_not_found", "rate_limited")

# Order matters: a spending cap is often sent as a 429 or a 403 and its text can say "limit
# exceeded", so it is tested before auth and the rate limit.
_SPENDING = re.compile(
    r"key limit exceeded|total limit|spend(?:ing)? limit|budget (?:has been )?exceeded|exceeded (?:your|the) budget"
    r"|insufficient[ _](?:credits?|funds|quota|balance)|credit balance|out of credits?|not enough credits?"
    r"|requires more credits|exceeded your current quota|billing|payment required|\b402\b",
    re.I)
_AUTH = re.compile(
    r"invalid[ _-]?(?:x-)?api[ _-]?key|incorrect api key|api key not valid|no api key|missing api key"
    r"|no auth credentials|authentication|unauthori[sz]ed|\b401\b|key (?:was )?(?:revoked|disabled|expired)",
    re.I)
_MODEL = re.compile(
    r"model[ _]not[ _]found|no endpoints found|not a valid model|unknown model|invalid model"
    r"|model\b[^.]{0,80}\bdoes not exist|does not exist[^.]{0,40}\bmodel",
    re.I)
_RATE = re.compile(r"rate[ _-]?limit|too many requests|\b429\b", re.I)

_CLASS_CAUSE = {
    "AuthenticationError": "auth", "PermissionDeniedError": "auth",
    "NotFoundError": "model_not_found", "EngineModelNotFound": "model_not_found",
    "RateLimitError": "rate_limited",
}


def classify(exc: BaseException | str | None) -> str | None:
    """The cause a provider's refusal names, or ``None`` when it names none of ``CAUSES``.

    The text is read first (a spending cap arrives as a 403 or a 429 on some providers), then
    the exception's class — litellm's and the OpenAI SDK's names, matched by name so this
    module never imports either."""
    if exc is None:
        return None
    text = exc if isinstance(exc, str) else f"{type(exc).__name__}: {exc}"
    for cause, pattern in (("spending_limit", _SPENDING), ("model_not_found", _MODEL),
                           ("auth", _AUTH), ("rate_limited", _RATE)):
        if pattern.search(text):
            return cause
    if not isinstance(exc, str):
        for klass in type(exc).__mro__:
            if klass.__name__ in _CLASS_CAUSE:
                return _CLASS_CAUSE[klass.__name__]
    return None


#: The switch's own words in Settings → Sleep (ruling 4b) — the app's ``Copy.ServerPlan.usePlanTitle``.
PLAN_SWITCH = "“Scheduled runs may use my plan” in Settings → Sleep"


def sentence(cause: str, *, plan_hint: bool = False) -> str:
    """What happened and the fix, for a cause in ``CAUSES``. ``plan_hint``: this was a scheduled run
    that ruling 4 kept off the person's plan, so their switch is a second fix (named, never flipped)."""
    if cause == "spending_limit":
        fix = "Raise the key's limit or add credit with the provider"
        if plan_hint:
            fix += f", or turn on {PLAN_SWITCH} to read on your plan instead"
        return f"The API key reached its spending limit — the provider refused every call. {fix}."
    if cause == "auth":
        return ("The provider refused the API key — it is missing, mistyped, revoked or expired. "
                "Check the key in Settings → Plans & keys.")
    if cause == "model_not_found":
        # Settings → Engines no longer edits a model id (settings defaults, owner 2026-10-22): an unknown model was set
        # outside the app's choices, so the fix is another engine there, or the model where it was set.
        return ("The provider does not know the model Sleep is set to use. "
                "Choose another engine in Settings → Engines, or change the model where it was set.")
    if cause == "rate_limited":
        fix = "Continue later, or raise the key's rate limit with the provider"
        if plan_hint:
            fix += f", or turn on {PLAN_SWITCH} to read on your plan instead"
        return f"The provider is rate-limiting the API key — too many requests. {fix}."
    raise ValueError(f"unknown cause {cause!r}")
