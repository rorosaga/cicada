"""A stuck backend says where it is stuck: SIGUSR1 writes every thread's Python stack, even from a busy loop."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from api.services import stack_dump

REPO = Path(__file__).resolve().parents[2]
CHILD = """
import sys, time
sys.path.insert(0, {repo!r})
from api.services import stack_dump
assert stack_dump.install() is True
def spinning_where_nobody_can_see():
    print("ready", flush=True)
    end = time.time() + 20
    while time.time() < end:      # a busy loop: no await, no I/O, the shape of a blocked event loop
        sum(range(1000))
spinning_where_nobody_can_see()
"""


@pytest.mark.skipif(stack_dump.SIGNAL is None, reason="no SIGUSR1 on this platform")
def test_a_busy_process_writes_its_stacks_on_the_signal_and_keeps_running(tmp_path):
    err = tmp_path / "err.log"
    with err.open("w") as fh:
        proc = subprocess.Popen([sys.executable, "-c", CHILD.format(repo=str(REPO))], stdout=subprocess.PIPE,
                                stderr=fh, text=True, env={**os.environ, "CICADA_CAPTURE": "off"})
        try:
            assert proc.stdout.readline().strip() == "ready"
            os.kill(proc.pid, signal.SIGUSR1)
            deadline = time.time() + 10
            text = ""
            while time.time() < deadline and "spinning_where_nobody_can_see" not in text:
                time.sleep(0.1)
                text = err.read_text()
            assert "spinning_where_nobody_can_see" in text, "the stack names the function it is stuck in"
            assert "File " in text and "line " in text
            assert proc.poll() is None, "the signal is a question, never a stop"
        finally:
            proc.kill()
            proc.wait(timeout=10)


def test_a_stream_with_no_file_descriptor_installs_nothing():
    import io

    stack_dump.uninstall()
    try:
        assert stack_dump.install(stream=io.StringIO()) is False
    finally:
        stack_dump.uninstall()
