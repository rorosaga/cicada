"""The memory tool backend for the Anthropic Python SDK: ``CicadaMemoryTool`` is a ``BetaAbstractMemoryTool``.

    from anthropic import Anthropic
    from cicada_memory_tool import CicadaMemoryTool

    memory = CicadaMemoryTool("http://127.0.0.1:8000", token="cic_api_…")
    runner = Anthropic().beta.messages.tool_runner(model=..., max_tokens=..., tools=[memory], messages=[...])

Every command is answered by :class:`cicada_memory_tool.core.CicadaMemory`; a refusal is a ``ToolError``, so the model
sees it as an error result (``is_error: true``) and reads the sentence saying what to do instead.
"""
from __future__ import annotations

import os
from typing import Any

from anthropic.lib.tools import BetaAbstractMemoryTool, ToolError

from .core import CicadaMemory, MemoryCommandError


class CicadaMemoryTool(BetaAbstractMemoryTool):
    """The person's Cicada as Claude's `/memories` directory, through one agent token."""

    def __init__(self, base_url: str | None = None, token: str | None = None, *,
                 state_path: str | os.PathLike | None = None, timeout: float = 30.0, cache_control=None,
                 memory: CicadaMemory | None = None) -> None:
        super().__init__(cache_control=cache_control)
        self.memory = memory or CicadaMemory(base_url, token, state_path=state_path, timeout=timeout)

    def _run(self, command: Any) -> str:
        payload = command.model_dump(exclude_none=True) if hasattr(command, "model_dump") else dict(command)
        try:
            return self.memory.execute(payload)
        except MemoryCommandError as refusal:
            raise ToolError(str(refusal)) from None

    def view(self, command):  # noqa: D102 — the six commands share one translation
        return self._run(command)

    def create(self, command):  # noqa: D102
        return self._run(command)

    def str_replace(self, command):  # noqa: D102
        return self._run(command)

    def insert(self, command):  # noqa: D102
        return self._run(command)

    def delete(self, command):  # noqa: D102
        return self._run(command)

    def rename(self, command):  # noqa: D102
        return self._run(command)
