"""How a run is billed, by engine id alone (Sleep page v5, B9). No provider is named: the app words it
from this enum and the engine label the person already chose. Ruling 4 stays visible: a scheduled
preview is never a plan — and, since ruling 16, a scheduled run reads everything waiting."""
from __future__ import annotations

import pytest

from test_sleep_engine_prefs import client  # noqa: F401  (the hermetic fixture)

from api.services import sleep_engine_prefs


@pytest.mark.parametrize("engine,billing", [
    ("claude-cli", "plan"), ("codex-cli", "plan"), ("litellm", "charged"), ("ollama", "local"),
    ("something-new", "unknown"), (None, "unknown"),
])
def test_the_billing_enum_comes_from_the_engine_id(engine, billing):
    assert sleep_engine_prefs.billing_for(engine) == billing


def test_a_default_install_previews_charged_on_both_triggers(client):
    prev = client.get("/sleep/engine").json()["preview"]
    assert prev["manual"]["billing"] == "charged" and prev["scheduled"]["billing"] == "charged"


def test_the_scheduled_preview_is_never_a_plan_even_when_a_plan_is_chosen(client):
    client.put("/sleep/engine", json={"mode": "codex", "model": "gpt-5.6-luna"})
    prev = client.get("/sleep/engine").json()["preview"]
    assert prev["manual"]["billing"] == "plan", "a run you start may use the plan you chose"
    assert prev["scheduled"]["billing"] != "plan", "TODO ruling 4: an unattended run never spends a plan"
    client.put("/sleep/engine", json={"mode": "agent", "model": "sonnet"})
    prev = client.get("/sleep/engine").json()["preview"]
    assert (prev["manual"]["billing"], prev["scheduled"]["billing"]) == ("plan", "charged")


def test_no_provider_name_rides_the_billing_field(client):
    text = str(client.get("/sleep/engine").json()["preview"]).lower()
    for name in ("openai", "anthropic", "claude plan", "chatgpt"):
        assert name not in text.replace("claude-cli", "").replace("codex-cli", ""), name
