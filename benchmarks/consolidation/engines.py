"""One ``--engine key|plan`` option for the replay batteries, and a count of the answers the parser could not use
(2026-11-24).

Why: almost every battery was written to read a Claude key from ``--key-file`` and build key settings, so what was
measured on a key was never measured on the signed-in plan (``claude -p``), which is the default engine for a new user.
On 2026-11-24 a judge turned out to be forced into another judge's answer shape on every plan call and nobody saw it.
A battery now takes ``--engine plan`` (no key file read, ``ANTHROPIC_API_KEY`` removed from the process) with the same
cases and the same scoring; ``--engine key`` is the default and behaves as before.

* :func:`add_argument` puts ``--engine`` on a parser.
* :func:`arm` is what a battery runs where it used to read the key: for a key it puts the key where the engine reads it
  (the caller passes the function that reads it, so each battery's own error stays), for the plan it removes any key.
* :func:`settings` builds the leg's settings for either engine: the same tiers (Sonnet main, Haiku small judge).
* :func:`tally` wraps ``providers.resolve_llm_fn`` for the length of a run and counts, per stage label, the calls, the
  calls that raised (an engine error, or a reply the plan-account guard discarded) and the replies that were not a
  JSON object; it keeps the top-level keys of the objects it saw, so a judge answered in another judge's shape shows as
  an unusual key set. It changes nothing a call returns.
"""
from __future__ import annotations

import contextlib
import inspect
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Callable

ENGINES = ("key", "plan")


def add_argument(parser, default: str = "key") -> None:
    parser.add_argument("--engine", choices=ENGINES, default=default,
                        help="key: the Claude key in --key-file (default); plan: the signed-in Claude plan (`claude -p`), "
                             "no key file read and no key in the environment")


def arm(engine: str, read_key: Callable[[], None] | None = None) -> None:
    """Make the process ready for ``engine``. ``read_key`` is the battery's own key reader (it puts the key in the
    environment, or exits saying there is none); it is never called for the plan, which never reads a key file."""
    if engine not in ENGINES:
        raise ValueError(f"unknown engine {engine!r}")
    if engine == "plan":
        os.environ.pop("ANTHROPIC_API_KEY", None)   # `claude -p` would bill a key it finds; the plan leg is the plan's
    elif read_key is not None:
        read_key()


def model_name(engine: str, name: str) -> str:
    from benchmarks.consolidation.run import engine_model

    return engine_model(engine, name)


def settings(engine: str, bank: Path, *, model: str = "sonnet", judge: str = "haiku"):
    """The leg's settings: the engine's main model and its small judge, each by tier name."""
    from benchmarks.engine_parity import settings_for

    return settings_for(engine, bank, model=model_name(engine, model), judge=model_name(engine, judge))


class Tally:
    """What the judges' replies were, per stage label."""

    def __init__(self) -> None:
        self.calls: Counter = Counter()
        self.raised: dict[str, Counter] = defaultdict(Counter)
        self.not_json: Counter = Counter()
        self.shapes: dict[str, Counter] = defaultdict(Counter)

    def saw(self, stage: str, response) -> None:
        self.calls[stage] += 1
        try:
            content = response.choices[0].message.content
        except Exception:  # noqa: BLE001
            try:
                content = response["choices"][0]["message"]["content"]
            except Exception:  # noqa: BLE001
                content = ""
        from api.services import json_parse

        try:
            parsed = json_parse.parse_json_object(content or "")
        except Exception:  # noqa: BLE001
            self.not_json[stage] += 1
            return
        if isinstance(parsed, dict):
            self.shapes[stage][",".join(sorted(parsed)) or "{}"] += 1
        else:
            self.not_json[stage] += 1

    def failed(self, stage: str, exc: BaseException) -> None:
        self.calls[stage] += 1
        self.raised[stage][type(exc).__name__] += 1

    def unusable(self, stage: str | None = None) -> int:
        stages = [stage] if stage else list(self.calls)
        return sum(self.not_json[s] + sum(self.raised[s].values()) for s in stages)

    def total(self) -> int:
        return sum(self.calls.values())

    def report(self) -> str:
        lines = []
        for stage in sorted(self.calls):
            raised = ", ".join(f"{k} {v}" for k, v in self.raised[stage].most_common())
            shapes = "; ".join(f"{v}x {{{k}}}" for k, v in self.shapes[stage].most_common(4))
            lines.append(f"  {stage:16} calls {self.calls[stage]:>4}  raised {sum(self.raised[stage].values()):>3}"
                         + (f" ({raised})" if raised else "") + f"  not a JSON object {self.not_json[stage]:>3}  keys: {shapes}")
        lines.append(f"  calls {self.total()}  unusable (raised or not JSON) {self.unusable()}")
        return "\n".join(lines)

    def as_dict(self) -> dict:
        return {"calls": dict(self.calls), "raised": {k: dict(v) for k, v in self.raised.items()},
                "not_json": dict(self.not_json), "shapes": {k: dict(v) for k, v in self.shapes.items()},
                "unusable": self.unusable()}


@contextlib.contextmanager
def tally():
    """Count every reply a ``resolve_llm_fn`` call returns while the block runs; yields the :class:`Tally`."""
    from api.services import providers

    counts = Tally()
    original = providers.resolve_llm_fn

    def counted(*args, **kwargs):
        stage = str(kwargs.get("stage") or "unknown")
        fn = original(*args, **kwargs)

        def call(*a, **kw):
            try:
                out = fn(*a, **kw)
            except Exception as exc:  # noqa: BLE001
                counts.failed(stage, exc)
                raise
            if inspect.isawaitable(out):
                async def finish():
                    try:
                        response = await out
                    except Exception as exc:  # noqa: BLE001
                        counts.failed(stage, exc)
                        raise
                    counts.saw(stage, response)
                    return response

                return finish()
            counts.saw(stage, out)
            return out

        return call

    providers.resolve_llm_fn = counted
    try:
        yield counts
    finally:
        providers.resolve_llm_fn = original


def dump(counts: Tally, path: Path) -> None:
    path.write_text(json.dumps(counts.as_dict(), indent=1), encoding="utf-8")
