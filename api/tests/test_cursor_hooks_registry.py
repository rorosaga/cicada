"""Only synthetic user-level Cursor configuration; never the owner's HOME."""
import json
from pathlib import Path

import pytest

CMD = "'/synthetic/python' '/synthetic/cicada/api/hooks/cursor.py'"


def registry():
    from api.hooks import cursor_registry
    return cursor_registry


def test_merge_update_uninstall_preserves_every_foreign_entry(tmp_path):
    r = registry(); p = tmp_path / ".cursor/hooks.json"; p.parent.mkdir()
    original = {"version": 1, "custom": {"sentinel": True}, "hooks": {
        "sessionStart": [{"command": "./foreign.sh", "timeout": 42}],
        "stop": [{"command": "./stop.sh"}], "afterAgentResponse": [{"type": "prompt", "prompt": "custom"}]}}
    p.write_text(json.dumps(original))
    assert r.install(p, command=CMD) == "added"
    assert r.install(p, command=CMD) == "present"
    new = '"/other home/bin/cicada-hook" cursor'
    assert r.status(p, command=new) == "stale"
    assert r.install(p, command=new) == "updated"
    data = json.loads(p.read_text())
    assert data["hooks"]["sessionStart"] == [original["hooks"]["sessionStart"][0], {"command": new, "timeout": 2}]
    assert r.uninstall(p) == 1
    assert json.loads(p.read_text()) == original
    assert r.uninstall(p) == 0


@pytest.mark.parametrize("raw", ['{broken', '[]', '{"version":2,"hooks":{}}', '{"version":1,"hooks":[]}',
                              '{"version":1,"hooks":{"sessionStart":{}}}', ' ' * (256*1024+1)])
def test_invalid_or_unknown_version_is_untouched(tmp_path, raw):
    r = registry(); p = tmp_path / "hooks.json"; p.write_text(raw)
    with pytest.raises(r.RegistryError): r.install(p, command=CMD)
    with pytest.raises(r.RegistryError): r.uninstall(p)
    assert p.read_text() == raw
    assert r.status(p, command=CMD) == "invalid"


def test_ownership_is_parsed_command_not_substring(tmp_path):
    r = registry(); p = tmp_path / "hooks.json"
    foreign = {"command": "echo '/synthetic/api/hooks/cursor.py'"}
    p.write_text(json.dumps({"version":1,"hooks":{"sessionStart":[foreign]}}))
    assert r.uninstall(p) == 0
    assert r.status(p, command=CMD) == "absent"
    assert r.install(p, command=CMD) == "added"
    assert json.loads(p.read_text())["hooks"]["sessionStart"][0] == foreign


def test_symlink_config_is_refused(tmp_path):
    r = registry(); target = tmp_path / "other.json"; target.write_text('{}')
    p = tmp_path / "hooks.json"; p.symlink_to(target)
    with pytest.raises(r.RegistryError): r.install(p, command=CMD)
    assert target.read_text() == '{}'


def test_duplicate_own_commands_collapse_without_touching_foreign_hooks(tmp_path):
    r = registry(); p = tmp_path / "hooks.json"
    p.write_text(json.dumps({"version":1,"hooks":{"sessionStart":[{"command":CMD},{"command":CMD},
                          {"command":"/bin/echo /synthetic/api/hooks/cursor.py"}]}}))
    assert r.install(p, command=CMD) == "updated"
    assert len(json.loads(p.read_text())["hooks"]["sessionStart"]) == 2
    assert r.uninstall(p) == 1
    assert json.loads(p.read_text())["hooks"]["sessionStart"] == [{"command":"/bin/echo /synthetic/api/hooks/cursor.py"}]
