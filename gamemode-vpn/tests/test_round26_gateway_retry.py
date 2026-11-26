"""Round 26 — gateway ping retry: one dropped echo must not cry "blocked"."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import gamemode_core as core


class FakeResult:
    def __init__(self, returncode=0):
        self.stdout = ""
        self.returncode = returncode


def test_retry_after_one_lost_echo():
    calls = []
    original_run = core.subprocess.run
    answers = [FakeResult(1), FakeResult(0)]  # lost, then answered

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return answers.pop(0)

    core.subprocess.run = fake_run
    try:
        assert core.ping_host("192.168.1.1") is True
        assert len(calls) == 2, calls
        assert calls[0] == calls[1], "the retry pings the same host the same way"
        assert calls[0][-1] == "192.168.1.1"
    finally:
        core.subprocess.run = original_run
    print("PASS one lost echo is retried and then answers")


def test_two_lost_echoes_is_unreachable():
    calls = []
    original_run = core.subprocess.run
    core.subprocess.run = lambda cmd, **kw: (
        calls.append(cmd), FakeResult(1))[1]
    try:
        assert core.ping_host("192.168.1.1") is False
        assert len(calls) == 2, calls  # exactly one retry, then it gives up
    finally:
        core.subprocess.run = original_run
    print("PASS two lost echoes count as unreachable")


def test_first_echo_answering_costs_no_retry():
    calls = []
    original_run = core.subprocess.run
    core.subprocess.run = lambda cmd, **kw: (
        calls.append(cmd), FakeResult(0))[1]
    try:
        assert core.ping_host("192.168.1.1") is True
        assert len(calls) == 1, calls
    finally:
        core.subprocess.run = original_run
    print("PASS a gateway that answers is pinged exactly once")


def test_attempts_one_is_the_old_behavior():
    calls = []
    original_run = core.subprocess.run
    core.subprocess.run = lambda cmd, **kw: (
        calls.append(cmd), FakeResult(1))[1]
    try:
        assert core.ping_host("192.168.1.1", attempts=1) is False
        assert len(calls) == 1, calls
        assert core.ping_host("192.168.1.1", attempts=0) is False
        assert len(calls) == 2, calls  # attempts clamps to at least 1
    finally:
        core.subprocess.run = original_run
    print("PASS attempts=1 behaves like the old single ping")


def test_missing_ping_binary_is_not_retried():
    calls = []
    original_run = core.subprocess.run

    def boom(cmd, **kwargs):
        calls.append(cmd)
        raise OSError("no ping here")

    core.subprocess.run = boom
    try:
        assert core.ping_host("192.168.1.1") is None
        assert len(calls) == 1, calls  # retrying a missing binary proves nothing
        assert core.ping_host("") is None
        assert core.ping_host(None) is None
        assert len(calls) == 1, "an empty host never reaches ping"
    finally:
        core.subprocess.run = original_run
    print("PASS a ping that cannot run stays unknown, unretried")


def test_snapshot_no_false_blocked_on_flaky_gateway():
    """End to end: one lost gateway echo no longer flips a bare
    connection to 'blocked' for a tick."""
    settings = core.default_settings()
    originals = (core.interface_states, core.default_gateway,
                 core.subprocess.run)
    core.interface_states = lambda: {"Wi-Fi": True}
    core.default_gateway = lambda: "192.168.1.1"
    answers = [FakeResult(1), FakeResult(0)]  # first poll loses one echo

    def fake_run(cmd, **kwargs):
        return answers.pop(0) if answers else FakeResult(0)

    core.subprocess.run = fake_run
    try:
        running, state = core.collect_snapshot(
            settings, core.SnapshotCache(), now=0.0)
        assert state == "bare", state
    finally:
        (core.interface_states, core.default_gateway,
         core.subprocess.run) = originals
    print("PASS snapshot stays bare when the gateway drops one echo")


if __name__ == "__main__":
    test_retry_after_one_lost_echo()
    test_two_lost_echoes_is_unreachable()
    test_first_echo_answering_costs_no_retry()
    test_attempts_one_is_the_old_behavior()
    test_missing_ping_binary_is_not_retried()
    test_snapshot_no_false_blocked_on_flaky_gateway()
    print("ROUND 26: ALL PASS")
