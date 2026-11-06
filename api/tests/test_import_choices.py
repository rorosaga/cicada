"""ROR-126 — the person's choice on an uploaded export: a start date, deselected chats, and the chats remembered."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _intake_fixtures import claude_conversations, claude_zip  # noqa: E402
from test_intake import _client, _episodes, _post  # noqa: E402

from api.services import import_choices  # noqa: E402


def _zip_of(n: int, *, grown: bool = False) -> bytes:
    from _intake_fixtures import _zip
    return _zip({"conversations.json": json.dumps(claude_conversations(n, grown=grown))})


def test_select_drops_older_and_deselected_and_keeps_undated():
    eps = [{"source": "claude", "source_id": "a", "original_date": "2026-01-05"},
           {"source": "claude", "source_id": "b", "original_date": "2026-03-01"},
           {"source": "claude", "source_id": "c", "original_date": None},
           {"source": "claude", "source_id": "d", "original_date": "2026-04-01"}]
    kept = import_choices.select(eps, since="2026-02-01", deselected={"claude:d"})
    assert [e["source_id"] for e in kept] == ["b", "c"]
    assert import_choices.parse_since("nonsense") is None and import_choices.parse_since("2026-02-01T10") == "2026-02-01"


def test_sniff_gives_each_chat_a_key_and_a_status(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    body = _post(client, "/intake/sniff", "data.zip", _zip_of(3)).json()
    titles = body["titles"]
    assert len(titles) == 3 and all(t["key"].startswith("claude:") and t["status"] == "new" for t in titles)
    assert body["delta"]["new"] == 3 and not any(t["deselected"] for t in titles)


def test_start_date_and_deselection_apply_before_any_episode_exists(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    keys = [t["key"] for t in _post(client, "/intake/sniff", "data.zip", _zip_of(4)).json()["titles"]]
    skip = next(k for k in keys if k.endswith("conv-3"))
    resp = client.post("/intake/import", files={"file": ("data.zip", _zip_of(4), "application/octet-stream")},
                       data={"since": "2026-02-02", "exclude": json.dumps([skip])})
    assert resp.status_code == 200
    # conv-0 is 2026-02-01 (before the start date), conv-3 is deselected: two chats become episodes.
    assert resp.json()["episodesStaged"] == 2
    assert len(_episodes(tmp_path)) == 2
    assert import_choices.remembered(tmp_path) == {skip}, "the start date is not remembered, the deselection is"


def test_a_remembered_chat_is_not_offered_as_new_and_stays_out_of_a_later_import(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    keys = [t["key"] for t in _post(client, "/intake/sniff", "data.zip", _zip_of(3)).json()["titles"]]
    skip = next(k for k in keys if k.endswith("conv-1"))
    client.post("/intake/import", files={"file": ("data.zip", _zip_of(3), "application/octet-stream")},
                data={"exclude": json.dumps([skip])})
    # A grown export arrives later: the chat is offered unticked, uncounted, and not staged.
    grown = _post(client, "/intake/sniff", "data.zip", _zip_of(5)).json()
    flags = {t["key"]: t["deselected"] for t in grown["titles"]}
    assert flags[skip] is True and sum(flags.values()) == 1
    assert grown["delta"]["new"] == 2, "only the two chats that were never seen"
    again = client.post("/intake/import", files={"file": ("data.zip", _zip_of(5), "application/octet-stream")})
    assert again.json()["episodesStaged"] == 2
    # Ticking it again forgets the decision.
    client.post("/intake/import", files={"file": ("data.zip", _zip_of(5), "application/octet-stream")},
                data={"exclude": "[]"})
    assert import_choices.remembered(tmp_path) == set()
