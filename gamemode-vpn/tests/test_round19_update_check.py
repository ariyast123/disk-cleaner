"""Round 19: update checks defeat the raw-cache lag (v1.2.8).

What bit Ariya: 1.2.7 was published and verified live, yet his
app showed no banner — GitHub's raw cache serves version.json
per region with a minutes-long lag (his VPN exit hit a stale
edge), and the app checked exactly once at startup, silently.
Now every fetch carries a cache-busting query, downloads too,
and the checker re-checks every 5 minutes while the app runs,
so a missed first check heals itself in the tray.
"""
import io
import json
import os
import sys
import tempfile
import threading
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import gamemode_core as core

TMP = tempfile.mkdtemp(prefix="gmvpn-gui19-")
core.data_dir = lambda: TMP
core.settings_path = lambda: os.path.join(TMP, "settings.json")
core.log_path = lambda: os.path.join(TMP, "gamemode.log")

import gamemode_vpn_app as gui


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def with_fake_urlopen(payload_by_marker, fn):
    """Run fn() with urllib.request.urlopen faked; return the URLs
    it requested. payload_by_marker maps a URL substring to bytes,
    or to an Exception instance to raise."""
    seen = []
    real = urllib.request.urlopen

    def fake(url, timeout=None):
        seen.append(url)
        for marker, payload in payload_by_marker.items():
            if marker in url:
                if isinstance(payload, Exception):
                    raise payload
                return FakeResponse(payload)
        raise AssertionError(f"unexpected URL {url}")

    urllib.request.urlopen = fake
    try:
        return fn(), seen
    finally:
        urllib.request.urlopen = real


def test_raw_url():
    plain = gui._raw_url("gamemode-vpn/version.json")
    assert plain == ("https://raw.githubusercontent.com/ariyast123/"
                     "disk-cleaner/main/gamemode-vpn/version.json"), plain
    busted = gui._raw_url("gamemode-vpn/version.json", cache_bust=True)
    assert busted.startswith(plain + "?t="), busted
    assert busted.rsplit("=", 1)[1].isdigit()
    print("PASS raw URL builder, with and without cache bust")


def test_fetch_busts_cache():
    payload = json.dumps({"version": "9.9.9", "notes": "x"}).encode()
    info, seen = with_fake_urlopen({"version.json": payload},
                                   gui.fetch_update_info)
    assert info is not None and info["version"] == "9.9.9"
    assert len(seen) == 1 and "version.json?t=" in seen[0], seen
    print("PASS update check fetches with a cache-busting query")

    info, seen = with_fake_urlopen(
        {"version.json": OSError("network down")}, gui.fetch_update_info)
    assert info is None
    print("PASS a failed check still returns None, never raises")


def test_download_busts_cache():
    def attempt():
        return gui.download_update_files()

    _result, seen = with_fake_urlopen(
        {"gamemode_vpn_app.py": b"# src", "gamemode_core.py": OSError("boom")},
        attempt)
    assert _result is None  # the failure aborts the download
    assert seen and all("?t=" in u for u in seen), seen
    print("PASS update downloads are cache-busted too")


def test_worker_rechecks():
    app = gui.GameModeApp()
    try:
        app._stop.set()
        while not app.msg_queue.empty():
            app.msg_queue.get_nowait()

        real_fetch = gui.fetch_update_info
        try:
            gui.fetch_update_info = lambda: {"version": "99.0.0"}
            app._stop.clear()  # the worker loop refuses to run while set
            worker = threading.Thread(target=app._check_update_worker)
            worker.start()
            worker.join(timeout=5)
            assert not worker.is_alive(), "worker must stop after posting"
            kind, info = app.msg_queue.get_nowait()
            assert kind == "update_available" and info["version"] == "99.0.0"
            print("PASS worker posts the banner when a version appears")

            gui.fetch_update_info = lambda: None
            app._stop.clear()
            worker = threading.Thread(target=app._check_update_worker)
            worker.start()
            app._stop.set()  # lands inside the 5-minute wait
            worker.join(timeout=5)
            assert not worker.is_alive(), "worker must honor the stop event"
            assert app.msg_queue.empty()
            print("PASS worker waits between checks and stops cleanly")
        finally:
            gui.fetch_update_info = real_fetch
    finally:
        app._stop.set()
        app.destroy()


def main():
    test_raw_url()
    test_fetch_busts_cache()
    test_download_busts_cache()
    test_worker_rechecks()
    print("ROUND 19 ALL PASS")


if __name__ == "__main__":
    main()
