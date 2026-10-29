"""A person's Cicada as the backend for Claude's memory tool, over the agent API (`/v1`).

``CicadaMemory`` answers the six memory commands with no dependency beyond the standard library;
``CicadaMemoryTool`` (needs the ``anthropic`` package) plugs it into the SDK's tool runner.
"""
from .core import CicadaMemory, MemoryCommandError

__all__ = ["CicadaMemory", "CicadaMemoryTool", "MemoryCommandError"]


def __getattr__(name: str):
    if name == "CicadaMemoryTool":
        from .sdk import CicadaMemoryTool

        return CicadaMemoryTool
    raise AttributeError(name)
