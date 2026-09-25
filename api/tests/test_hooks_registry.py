"""G105 R14: install.sh's settings.json merge — idempotent, never clobbers
other hooks or keys, refuses to touch a file it cannot parse."""
from __future__ import annotations

import json
from pathlib import Path

from api.hooks import registry as reg

CMD = '"/opt/example/api/.venv/bin/python" "/opt/example/api/hooks/capture.py" --harness claude-code'


def _read(p: Path) -> dict:
    return json.loads(p.read_text())


def test_install_creates_file_and_parent(tmp_path):
    p = tmp_path / ".claude" / "settings.json"
    assert reg.install(p, event="Stop", command=CMD) == "added"
    data = _read(p)
    assert data == {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": CMD, "timeout": 5}]}]}}
    assert reg.status(p, event="Stop", command=CMD) == "present"


def test_install_merges_and_preserves_other_hooks_and_keys(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({
        "model": "opus",
        "hooks": {
            "Stop": [{"hooks": [{"type": "command", "command": "/other/stop.sh"}]}],
            "SessionStart": [{"matcher": "startup", "hooks": [{"type": "command", "command": "/other/start.sh"}]}],
        },
    }))
    assert reg.install(p, event="Stop", command=CMD) == "added"
    data = _read(p)
    assert data["model"] == "opus"
    assert data["hooks"]["SessionStart"][0]["hooks"][0]["command"] == "/other/start.sh"
    cmds = [h["command"] for e in data["hooks"]["Stop"] for h in e["hooks"]]
    assert cmds == ["/other/stop.sh", CMD]


def test_install_is_idempotent_and_updates_a_moved_repo(tmp_path):
    p = tmp_path / "settings.json"
    reg.install(p, event="Stop", command=CMD)
    assert reg.install(p, event="Stop", command=CMD) == "present"
    moved = CMD.replace("/opt/example", "/srv/example")
    assert reg.status(p, event="Stop", command=moved) == "stale"
    assert reg.install(p, event="Stop", command=moved) == "updated"
    cmds = [h["command"] for e in _read(p)["hooks"]["Stop"] for h in e["hooks"]]
    assert cmds == [moved]


def test_uninstall_removes_only_ours_and_prunes_empties(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "/other/stop.sh"}]}]},
                             "permissions": {"allow": ["Bash(ls)"]}}))
    reg.install(p, event="Stop", command=CMD)
    assert reg.uninstall(p) == 1
    data = _read(p)
    assert data["hooks"]["Stop"][0]["hooks"][0]["command"] == "/other/stop.sh"
    assert data["permissions"] == {"allow": ["Bash(ls)"]}
    q = tmp_path / "only-ours.json"
    reg.install(q, event="Stop", command=CMD)
    reg.uninstall(q)
    assert _read(q) == {}
    assert reg.uninstall(tmp_path / "missing.json") == 0


def test_refuses_to_clobber_unparseable_settings(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text("{ not json")
    rc = reg.main(["install", "--settings", str(p), "--event", "Stop", "--command", CMD])
    assert rc == 3 and p.read_text() == "{ not json"


def test_cli_status_exit_codes(tmp_path):
    p = tmp_path / "settings.json"
    assert reg.main(["status", "--settings", str(p), "--event", "Stop", "--command", CMD]) == 1
    assert reg.main(["install", "--settings", str(p), "--event", "Stop", "--command", CMD]) == 0
    assert reg.main(["status", "--settings", str(p), "--event", "Stop", "--command", CMD]) == 0
    assert reg.main(["status", "--settings", str(p), "--event", "Stop", "--command", CMD + " --x"]) == 2
    assert reg.main(["uninstall", "--settings", str(p)]) == 0


def test_registry_module_imports_nothing_from_api():
    src = Path(reg.__file__).read_text()
    assert "from api" not in src and "import api" not in src


RECALL = '"/opt/example/api/.venv/bin/python" "/opt/example/api/hooks/recall.py" --harness claude-code'


def test_recall_entries_sit_beside_the_stop_hook_and_never_collapse_it(tmp_path):
    p = tmp_path / "settings.json"
    reg.install(p, event="Stop", command=CMD)
    for ev in ("SessionStart", "UserPromptSubmit"):
        assert reg.install(p, event=ev, command=RECALL) == "added"
        assert reg.install(p, event=ev, command=RECALL) == "present"
        assert reg.status(p, event=ev, command=RECALL) == "present"
    assert reg.status(p, event="Stop", command=CMD) == "present"
    assert [h["command"] for e in _read(p)["hooks"]["Stop"] for h in e["hooks"]] == [CMD]


def test_a_capture_entry_in_an_event_is_never_mistaken_for_the_recall_hook(tmp_path):
    p = tmp_path / "settings.json"
    reg.install(p, event="SessionStart", command=CMD)
    assert reg.status(p, event="SessionStart", command=RECALL) == "absent"
    assert reg.install(p, event="SessionStart", command=RECALL) == "added"
    assert [h["command"] for e in _read(p)["hooks"]["SessionStart"] for h in e["hooks"]] == [CMD, RECALL]


def test_a_moved_repo_updates_the_recall_entries(tmp_path):
    p = tmp_path / "settings.json"
    reg.install(p, event="UserPromptSubmit", command=RECALL)
    moved = RECALL.replace("/opt/example", "/srv/example")
    assert reg.status(p, event="UserPromptSubmit", command=moved) == "stale"
    assert reg.install(p, event="UserPromptSubmit", command=moved) == "updated"
    assert [h["command"] for e in _read(p)["hooks"]["UserPromptSubmit"] for h in e["hooks"]] == [moved]


def test_uninstall_hook_recall_leaves_the_stop_hook_and_other_hooks(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"hooks": {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": "/o/u.sh"}]}]}}))
    reg.install(p, event="Stop", command=CMD)
    reg.install(p, event="SessionStart", command=RECALL)
    reg.install(p, event="UserPromptSubmit", command=RECALL)
    assert reg.uninstall(p, hook="recall") == 2
    data = _read(p)
    assert [h["command"] for e in data["hooks"]["Stop"] for h in e["hooks"]] == [CMD]
    assert [h["command"] for e in data["hooks"]["UserPromptSubmit"] for h in e["hooks"]] == ["/o/u.sh"]
    assert "SessionStart" not in data["hooks"]
    assert reg.main(["uninstall", "--settings", str(p), "--hook", "recall"]) == 0


def test_a_bare_uninstall_removes_both_scripts(tmp_path):
    p = tmp_path / "settings.json"
    reg.install(p, event="Stop", command=CMD)
    reg.install(p, event="SessionStart", command=RECALL)
    reg.install(p, event="UserPromptSubmit", command=RECALL)
    assert reg.uninstall(p) == 3 and _read(p) == {}
