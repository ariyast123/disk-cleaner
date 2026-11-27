"""Round 27 — lowest-metric active default route wins the gateway pick.

`route print` can list several 0.0.0.0 rows (Ethernet + Wi-Fi, or a
VPN's own default route); Windows forwards through the lowest-metric
one, so pinging the first row can test a gateway that is not in the
path — and "bare" vs "blocked" is decided against it. Only Active
Routes rows count, lowest metric wins."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import gamemode_core as core


class FakeResult:
    def __init__(self, stdout=""):
        self.stdout = stdout


def run_with(output):
    original_run = core.subprocess.run
    core.subprocess.run = lambda cmd, **kw: FakeResult(output)
    try:
        return core.default_gateway()
    finally:
        core.subprocess.run = original_run


ROUTE_HEADER = """===========================================================================
Interface List
  7...aa bb cc dd ee ff ......Intel(R) Ethernet
 15...11 22 33 44 55 66 ......Wi-Fi
===========================================================================
IPv4 Route Table
===========================================================================
Active Routes:
Network Destination        Netmask          Gateway       Interface  Metric
"""

ROUTE_FOOTER = """===========================================================================
Persistent Routes:
  Network Address          Netmask  Gateway Address  Metric
          0.0.0.0          0.0.0.0      192.168.99.1       1
===========================================================================
"""


def test_lowest_metric_wins_not_first_row():
    output = (ROUTE_HEADER
              + "          0.0.0.0          0.0.0.0      192.168.1.1    192.168.1.100     25\n"
              + "          0.0.0.0          0.0.0.0       10.8.0.1        10.8.0.5      5\n"
              + "        192.168.1.0    255.255.255.0      192.168.1.1    192.168.1.100     25\n"
              + ROUTE_FOOTER)
    assert run_with(output) == "10.8.0.1", run_with(output)
    print("PASS lowest-metric default route wins over the first row")


def test_single_route_unchanged():
    output = (ROUTE_HEADER
              + "          0.0.0.0          0.0.0.0      192.168.1.1    192.168.1.100     25\n"
              + ROUTE_FOOTER)
    assert run_with(output) == "192.168.1.1"
    print("PASS a single default route still returns its gateway")


def test_tie_keeps_first_row():
    output = (ROUTE_HEADER
              + "          0.0.0.0          0.0.0.0      192.168.1.1    192.168.1.100     25\n"
              + "          0.0.0.0          0.0.0.0      192.168.2.1    192.168.2.100     25\n"
              + ROUTE_FOOTER)
    assert run_with(output) == "192.168.1.1"
    print("PASS equal metrics keep the first row")


def test_persistent_route_is_ignored():
    # The persistent 0.0.0.0 row (metric 1, gateway 192.168.99.1)
    # must never win over the live table, even with the lowest metric.
    output = (ROUTE_HEADER
              + "          0.0.0.0          0.0.0.0      192.168.1.1    192.168.1.100     25\n"
              + ROUTE_FOOTER)
    assert run_with(output) == "192.168.1.1"
    print("PASS a persistent route never beats the active table")


def test_no_default_route_is_none():
    output = (ROUTE_HEADER
              + "        192.168.1.0    255.255.255.0      192.168.1.1    192.168.1.100     25\n"
              + ROUTE_FOOTER)
    assert run_with(output) is None
    print("PASS no default route means no gateway")


def test_unparseable_metric_only_wins_alone():
    output = (ROUTE_HEADER
              + "          0.0.0.0          0.0.0.0      192.168.1.1    192.168.1.100     25\n"
              + "          0.0.0.0          0.0.0.0      192.168.2.1    192.168.2.100    bad\n"
              + ROUTE_FOOTER)
    assert run_with(output) == "192.168.1.1"
    alone = (ROUTE_HEADER
             + "          0.0.0.0          0.0.0.0      192.168.2.1    192.168.2.100    bad\n"
             + ROUTE_FOOTER)
    assert run_with(alone) == "192.168.2.1"
    print("PASS a row with a bad metric only wins when it is the only route")


def test_no_headers_falls_back_to_scanning_all_rows():
    # Localised Windows has no "Active Routes:" header: the old
    # behaviour (scan every row, lowest metric wins) must still hold.
    output = ("          0.0.0.0          0.0.0.0      192.168.1.1    192.168.1.100     25\n"
              "          0.0.0.0          0.0.0.0       10.8.0.1        10.8.0.5      5\n")
    assert run_with(output) == "10.8.0.1"
    print("PASS without section headers every row is still considered")


def test_route_command_failure_is_none():
    original_run = core.subprocess.run
    core.subprocess.run = lambda cmd, **kw: (_ for _ in ()).throw(
        OSError("no route here"))
    try:
        assert core.default_gateway() is None
    finally:
        core.subprocess.run = original_run
    print("PASS a failing route command stays unknown")


def test_snapshot_uses_lowest_metric_gateway():
    """End to end: with two default routes the snapshot pings the
    lowest-metric gateway, not the first row's."""
    settings = core.default_settings()
    output = (ROUTE_HEADER
              + "          0.0.0.0          0.0.0.0      192.168.1.1    192.168.1.100     25\n"
              + "          0.0.0.0          0.0.0.0       10.8.0.1        10.8.0.5      5\n"
              + ROUTE_FOOTER)
    originals = (core.interface_states, core.subprocess.run)
    core.interface_states = lambda: {"Wi-Fi": True}
    seen = []

    class PingResult:
        stdout = ""
        returncode = 0

    def fake_run(cmd, **kwargs):
        seen.append(cmd)
        if cmd[0] == "route":
            return FakeResult(output)
        return PingResult()

    core.subprocess.run = fake_run
    try:
        cache = core.SnapshotCache()
        assert cache.gateway(0.0) == "10.8.0.1"
        running, state = core.collect_snapshot(
            settings, cache, now=0.0)
        pings = [c for c in seen if c[0] == "ping"]
        assert len(pings) == 1, seen
        assert pings[0][-1] == "10.8.0.1", pings
        assert state == "bare", state
    finally:
        (core.interface_states, core.subprocess.run) = originals
    print("PASS snapshot pings the lowest-metric gateway")


if __name__ == "__main__":
    test_lowest_metric_wins_not_first_row()
    test_single_route_unchanged()
    test_tie_keeps_first_row()
    test_persistent_route_is_ignored()
    test_no_default_route_is_none()
    test_unparseable_metric_only_wins_alone()
    test_no_headers_falls_back_to_scanning_all_rows()
    test_route_command_failure_is_none()
    test_snapshot_uses_lowest_metric_gateway()
    print("ROUND 27: ALL PASS")
