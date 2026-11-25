"""Round 6: the kill-first update helper + no manual close."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import disk_cleaner_app as gui


def test_helper_kills_first():
    project = r"C:\Users\ariyast\DiskCleaner"
    launched = os.path.join(project, "DiskCleaner.exe")
    lines = gui.update_helper_lines(project, launched)
    body = "\n".join(lines)
    # kill-first: every copy dies before any waiting or building
    assert "taskkill /F /IM DiskCleaner.exe" in body
    assert body.index("taskkill /F /IM DiskCleaner.exe") < \
        body.index(":waitloop") < body.index("call build.bat")
    # short verification loop with a proceed-anyway exit
    assert "if %WAITS% GEQ 10 goto proceed" in body
    assert ":allclosed" in body
    # unattended build, logged by appending (never wiping the log)
    assert "call build.bat auto >> update_build.log 2>&1" in body
    # copy-back over the launched exe + relaunch, with fallback
    assert 'copy /Y "%BUILT%" "%LAUNCHED%"' in body
    assert 'start "" "%LAUNCHED%"' in body
    assert "relaunch issued" in body
    print("PASS helper: kill-first, verify, build, copy-back, relaunch")


def test_no_manual_close_step():
    src = open(os.path.join(os.path.dirname(__file__), "..",
                            "disk_cleaner_app.py"),
               encoding="utf-8").read()
    assert "Close Disk Cleaner now" not in src
    assert "close the app to finish" not in src.lower()
    frozen = src[src.index("def _update_downloaded"):]
    frozen = frozen[:frozen.index("def _write_update_helper")]
    assert "os._exit" in frozen  # guaranteed exit backstop
    print("PASS the frozen update path closes itself, no dialog")


def test_helper_launch_has_a_console():
    src = open(os.path.join(os.path.dirname(__file__), "..",
                            "disk_cleaner_app.py"),
               encoding="utf-8").read()
    assert "CREATE_NEW_CONSOLE" in src
    assert "explorer.exe" in src
    assert '"DETACHED_PROCESS"' not in src
    print("PASS helper launches with its own console window")


def test_version():
    assert gui.VERSION == "1.2.7"
    print("PASS app version is 1.2.7")


def main():
    test_helper_kills_first()
    test_no_manual_close_step()
    test_helper_launch_has_a_console()
    test_version()
    print("ROUND 6 ALL PASS")


if __name__ == "__main__":
    main()
