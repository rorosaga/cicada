"""The spending limit: a run on a key stops at the figure the person set (ROR-102; ruling 63 (g)).

The owner, 2026-11-04: "from cicada you can put a limit on spending." It amends ruling 4's "no limit Cicada sets".

* **A soft stop, the reserve's own path** (``sleep_reserve``): reads stop going out, what was already read is filed, the
  rest wait. It is a pause, never a failure: ``DrainStop("reserve", …, limit="spend")``.
* **How far past the line, in words.** A call that has been sent cannot be recalled, and filing is never stopped, since
  otherwise the reads already paid for are lost. So: one read past it when reads cost about the same (a call goes out
  only when what is spent and what is out leaves room, checked after it holds its permit, ``try_admit``); if a read costs
  far more than any before it, every read then out, at most 3 on a Claude key and 10 on another; plus filing what was
  read, which a batch sized to the allowance left keeps small (``batch_size``). A conversation caught part way through
  its chunks goes back to wait, and is read again next time.
* **After the line nothing else starts** (``LINE_STAGES``): In short, the web check, link reads, the inbox's judging and
  the value match (`value_alignment`) and the fact fold (`fact_fold`) are refused per call, even on a run with nothing left to read.
* **Per run, and a Continue is a new allowance.** The figure is snapshotted when a run or a Continue starts; the
  person's click is what spends it again. A scheduled run that reaches it waits for that click. A scheduled run that
  paused on a restart, the engine or a busy bank (``sleep_paused.SCHEDULE_REPLACEABLE``) is replaced by the next one,
  with a fresh allowance, so those two together can spend the figure twice.
* **It covers a run, nothing else.** Ask, the inbox's tidy and catch-up, a click's web sweep, repairs and the quick read
  after a conversation are not limited. They are in the ledger, each at what it cost.
* **The figure is the ledger's** (``providers._emit``): what each call cost, a failed one included, at the provider's
  list price. A charged call whose cost cannot be read stops the run, like a model with no price (fail closed).
* **A model with no known price stops the run: never tokens counted, never a guess.** A limit in dollars cannot hold on
  a price nobody knows, and a run that spends past it silently is the one thing this exists to prevent. Told before the
  first read when the model is known up front, else at the first call that reports no price.
* **A run may read on two models** (ruling 80, ``light_reads``): the person's own, and the lightest model of the same key for
  old bulk saves, in batches of their own after every other save. Each call is added at its own model's price (the ledger's
  figure), both models need a known price before the run starts, and a line reached with only such saves left ends the run
  rather than pausing it. The first lighter batch is sized by what the dearer model cost each, so it never holds more than
  the allowance buys; it is then sized by its own.
* **A part of the figure is the question steps' (2026-11-27, `QUESTIONS_SHARE`).** While reading, the line is the figure
  less that part and less the dearest call so far (so the last read stays out of it), so a night that would have read to the
  figure stops a little sooner; the tail's question steps (the
  same-name review, the two joins, the second look at open questions, the described landing, the which-one reader) then
  spend the rest, each call admitted or refused against the whole figure (`end_reading`, `QUESTIONS_SCOPE`). The part is
  kept only while those steps have something to read: when the reading line is reached and they have none
  (`release_reserve`), reading goes on to the whole figure. The bound is unchanged: the figure plus the one call a line
  may be passed by.
* **Metered engines only.** A plan's limits are the plan's, and a local model costs nothing.
"""
from __future__ import annotations

import contextlib
import threading
import time
from typing import Callable

from api.services import engine_errors

#: What a machine that never chose reads. Hand-edited nonsense reads as this too: never a reason to spend more.
DEFAULT_USD = 5.0
CHOICES = (1, 5, 10, 20, 50)
MAX_USD = 100_000.0
LIMIT = "spend"
#: Each fits the Sleep page's sentence (``SentenceLine.maxTail``) and names no figure (ruling 12).
SENTENCE = "Spending limit reached; what was read is kept. Continue spends up to it again."
NO_PRICE_SENTENCE = "No price known for this model, so the limit can't hold. Change either to go on."
#: The calls refused past the line. Everything else in a batch files what was already read.
LINE_STAGES = frozenset({"extraction", "enrichment", "in_short", "media_read", "inbox_tend", "web_check", "web_context",
                         "value_match", "fact_fold", "revision_pair"})
#: What one read may write at most (``anthropic_engine.DEFAULT_MAX_TOKENS``): the first batch's price, before any is known.
READ_OUTPUT_TOKENS = 64_000
POLL_S = 0.05
#: The part of a run's figure kept back from reading for the tail's question steps (measured, TODO ruling 63 (g)).
QUESTIONS_SHARE = 0.15
#: A call made under a scope ending so (``sleep_cycle._question_line``) is held to the run's figure whatever its stage label:
#: the question steps' calls carry the labels the batches' own filing uses, which are never refused.
QUESTIONS_SCOPE = "-questions"


class SpendGuard:
    """What a run has cost against the person's figure, safe across the provider seam's threads."""

    def __init__(self, limit_usd: float, *, read_cap_usd: float | None = None):
        self.limit_usd = float(limit_usd)
        self.spent_usd = 0.0
        self.no_price = False
        self.read_cap_usd = read_cap_usd
        self.reserve_usd = 0.0            # the question steps' part of the figure, while reading goes on (``end_reading``)
        self.reserve_check: Callable[[], bool] | None = None   # do they have anything to read? (None: assume so)
        self._reading = True
        self._asked = False
        self._ask_lock = threading.Lock()
        self._lock = threading.Lock()
        self._out = 0                     # calls sent and not yet answered
        self._dearest: float | None = None
        self._per_conversation: float | None = None
        self._spent_at_filing = 0.0

    def observe(self, cost_usd: float | None) -> None:
        with self._lock:
            if cost_usd is None:
                self.no_price = True
            else:
                self.spent_usd += float(cost_usd)
                self._dearest = max(self._dearest or 0.0, float(cost_usd))

    def _line(self) -> float:
        """The figure a call is held to now: after reading, all of it. While the drain reads and a part is kept back, less that
        part and less the dearest call so far, so the last read never crosses into the question steps' part (the line a read
        may pass by one call is the whole figure's, which they hold to after)."""
        if not self._reading:
            return self.limit_usd
        return self.limit_usd - self.reserve_usd - (self._dearest or 0.0 if self.reserve_usd > 0 else 0.0)

    def end_reading(self) -> None:
        """The drain has stopped reading: the line becomes the whole figure, for the tail's calls."""
        with self._lock:
            self._reading = False

    def _ask_reserve(self) -> None:
        """Reading has used its own part of the figure while a part is kept back: do the question steps have anything to
        read? Asked once, by their engine-free filters, outside ``_lock`` (they read files); with nothing, the part is given
        back and reading goes on to the whole figure. Whoever reaches the line first asks, the others wait for the answer."""
        with self._ask_lock:
            with self._lock:
                if (self._asked or not self._reading or self.reserve_usd <= 0 or self.no_price
                        or self.spent_usd < self._line()):
                    return
            try:
                work = True if self.reserve_check is None else bool(self.reserve_check())
            except Exception:  # noqa: BLE001 - a filter that cannot answer is no work, never a reason to hold reading back
                work = False
            with self._lock:
                self._asked = True
                if not work:
                    self.reserve_usd = 0.0

    def release_reserve(self) -> None:
        """The question steps have nothing to read: reading may use the whole figure."""
        with self._lock:
            self.reserve_usd = 0.0

    @property
    def reserving(self) -> bool:
        with self._lock:
            return self._reading and self.reserve_usd > 0

    def try_admit(self) -> bool:
        """May one more call go out now? ``True`` holds its place until ``release``; ``False`` means wait, since what is
        spent and what is out leave no room to say yet (the run's first call goes alone, to learn the price). Past the
        line it raises: the call is never sent."""
        self._ask_reserve()
        with self._lock:
            line = self._line()
            if self.no_price or self.spent_usd >= line:
                raise engine_errors.SpendLimitReached(self.sentence)
            if self._out and (self._dearest is None or self.spent_usd + self._out * self._dearest >= line):
                return False
            self._out += 1
            return True

    def release(self) -> None:
        with self._lock:
            self._out -= 1

    def note_filed(self, conversations: int) -> None:
        """A batch filed these: what they cost each, read and filing together, sizes the next batch."""
        if conversations <= 0:
            return
        with self._lock:
            self._per_conversation = (self.spent_usd - self._spent_at_filing) / conversations
            self._spent_at_filing = self.spent_usd

    def batch_size(self, size: int) -> int:
        """How many conversations the allowance left buys, at what the last batch's cost each, or before any is known at
        the most one read can write. Never more than the person's batch, never none (the line is what stops a run)."""
        with self._lock:
            each, left = self._per_conversation or self.read_cap_usd, self._line() - self.spent_usd
        return min(size, max(1, int(left / each))) if each else size

    def observe_snapshot(self, snap) -> None:
        """A plan window's snapshot: nothing to a key (``ReserveGuard``'s other half)."""

    def is_reached(self) -> bool:
        self._ask_reserve()
        with self._lock:
            return self.no_price or self.spent_usd >= self._line()

    def stop_values(self) -> tuple[int | None, str]:
        return None, LIMIT

    @property
    def sentence(self) -> str:
        return NO_PRICE_SENTENCE if self.no_price else SENTENCE


@contextlib.contextmanager
def turn(guard: SpendGuard | None):
    """Hold a place for one call from a thread, inside its permit. A guard of ``None`` is no limit."""
    if guard is None:
        yield
        return
    while not guard.try_admit():
        time.sleep(POLL_S)
    try:
        yield
    finally:
        guard.release()


def valid(value) -> bool:
    """A figure the limit can be: a positive, finite number up to ``MAX_USD``."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return 0 < float(value) <= MAX_USD


def _cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    from api.services import anthropic_models, direct_engines, price_supplement, pricing

    if direct_engines.for_model(model) is not None:
        return price_supplement.claude_cost(anthropic_models.resolve(model).model, input_tokens=input_tokens,
                                            output_tokens=output_tokens)
    return pricing.estimate_cost(model, input_tokens, output_tokens)


def guard_for(resolved, limit_usd: float | None, *, also: tuple[str, ...] = ()) -> SpendGuard | None:
    """The guard for a run on ``resolved``, or ``None`` when no limit applies: none set, or an engine that is not charged
    per use. A model whose price cannot be read at all waits for the first call to say so. ``also``: other models the run
    reads on (the lighter model of old bulk saves, ruling 80): each needs a price too, or the run stops before it starts."""
    from api.services import telemetry

    main = str(getattr(resolved, "litellm_model", "") or "")
    if not limit_usd or not main or telemetry.connection_for_model(main)[1] != "usage":
        return None
    guard = SpendGuard(limit_usd)
    guard.reserve_usd = float(limit_usd) * QUESTIONS_SHARE
    with contextlib.suppress(Exception):   # no first estimate only makes the first batch the person's own
        guard.read_cap_usd = _cost(main, 0, READ_OUTPUT_TOKENS)
    models = {main, str(getattr(resolved, "effective_consolidation_model", "") or ""),
              str(getattr(resolved, "litellm_disambiguation_model", "") or ""), *also}
    try:
        if not all(_cost(m, 1, 1) is not None for m in models if m):
            guard.observe(None)
    except Exception:  # noqa: BLE001 — a table that cannot be read leaves it to the first call's own report
        pass
    return guard
