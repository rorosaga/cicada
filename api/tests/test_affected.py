"""`make test-changed` picks the tests a change can break (`_affected.py`, owner 2026-11-24), by the names that changed."""
from __future__ import annotations

import subprocess
from pathlib import Path

from api.tests import _affected


def _repo(tmp_path: Path) -> Path:
    files = {
        "api/__init__.py": "",
        "api/services/__init__.py": "",
        "api/services/a.py": "def f():\n    return 1\n\n\ndef g():\n    return 2\n\n\ndef uses_f():\n    return f()\n",
        "api/services/b.py": "from api.services import a\n\n\ndef h():\n    return a.f()\n\n\ndef k():\n    return 3\n",
        "api/tests/test_f.py": "from api.services.a import f\n\n\ndef test_f():\n    assert f() == 1\n",
        "api/tests/test_uses_f.py": "from api.services import a\n\n\ndef test_u():\n    assert a.uses_f() == 1\n",
        "api/tests/test_g.py": "from api.services import a\n\n\ndef test_g(monkeypatch):\n"
                               "    monkeypatch.setattr(a, 'g', lambda: 5)\n    assert a.g() == 5\n",
        "api/tests/test_h.py": "from api.services import b\n\n\ndef test_h():\n    assert b.h() == 1\n",
        "api/tests/test_k.py": "from api.services import b\n\n\ndef test_k():\n    assert b.k() == 3\n",
        "api/tests/test_script.py": "SCRIPT = 'scripts/dev/tidy.sh'\n\n\ndef test_s():\n    '''Mentions api/services/a.py in prose only.'''\n",
        "scripts/dev/tidy.sh": "echo hi\n",
    }
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    for args in (["init", "-q"], ["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base"]):
        subprocess.run(["git", *args], cwd=tmp_path, check=True)
    return tmp_path


def _select(repo: Path, changed: list[str]):
    _affected._tree.cache_clear()
    return _affected.select(changed, repo=repo, ref="HEAD")


def test_a_changed_function_selects_its_users_and_its_callers_users_never_a_neighbours(tmp_path):
    repo = _repo(tmp_path)
    a = repo / "api/services/a.py"
    a.write_text(a.read_text().replace("return 1", "return 10"))

    chosen = set(_select(repo, ["api/services/a.py"]).pytest)

    # f's own test, the test of a function in a.py that calls f, and the test of b.h, which calls a.f.
    assert chosen == {"test_f.py", "test_uses_f.py", "test_h.py"}


def test_a_monkeypatched_name_counts_as_used_and_a_named_file_selects_its_test(tmp_path):
    repo = _repo(tmp_path)
    a = repo / "api/services/a.py"
    a.write_text(a.read_text().replace("return 2", "return 20"))
    (repo / "scripts/dev/tidy.sh").write_text("echo bye\n")

    chosen = set(_select(repo, ["api/services/a.py", "scripts/dev/tidy.sh"]).pytest)

    # `setattr(a, "g", …)` uses g; the script's path in a string names it; a docstring never names anything.
    assert chosen == {"test_g.py", "test_script.py"}


def test_the_suite_wide_files_select_everything(tmp_path):
    repo = _repo(tmp_path)
    assert _select(repo, ["api/tests/conftest.py"]).everything == "api/tests/conftest.py"
