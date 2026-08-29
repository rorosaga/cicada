"""Uses ``asyncio.run`` — pytest-asyncio is not a project dependency (same
convention as ``test_llm_seam_adoption.py``)."""
from __future__ import annotations

import asyncio
import os
import sys

from api.models.schemas import ConnectionKind, ConnectionStatus, LoginHint
from api.services.connections import base


def test_scrubbed_env_drops_provider_keys(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    monkeypatch.setenv("OPENAI_API_KEY", "b")
    monkeypatch.setenv("PATH", os.environ["PATH"])
    env = base.scrubbed_env()
    assert "ANTHROPIC_API_KEY" not in env and "OPENAI_API_KEY" not in env
    assert env["PATH"] == os.environ["PATH"]


def test_run_cli_captures_output():
    res = asyncio.run(base.run_cli([sys.executable, "-c", "import sys; print('hi'); sys.exit(3)"]))
    assert res.rc == 3 and res.stdout.strip() == "hi"


def test_run_cli_missing_binary_is_not_an_exception():
    res = asyncio.run(base.run_cli(["definitely-not-a-binary-xyz"]))
    assert res.rc == 127 and "not found" in res.stderr


def test_run_cli_timeout():
    res = asyncio.run(base.run_cli([sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.2))
    assert res.rc == 124 and "timed out" in res.stderr


def test_status_serialises_camel_case():
    s = ConnectionStatus(
        id="claude-plan", label="Claude plan", kind=ConnectionKind.subscription,
        available=True, connected=False, billing="subscription",
        login=LoginHint(mode="terminal", command="claude auth login"),
    )
    d = s.model_dump()
    assert d["priceUsdMonth"] is None and d["login"]["command"] == "claude auth login"
