"""Round 10: the finish_update helper script + startup command."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import heatwatch_core as core

TMP = tempfile.mkdtemp(prefix="hw-help-")
core.data_dir = lambda: TMP

import heatwatch_app as gui


def test_helper_lines():
    lines = gui.update_helper_lines(r"C:\Users\ariyast\HeatWatchApp",
                                    r"C:\Users\ariyast\HeatWatchApp\HeatWatch.exe")
    body = "\n".join(lines)
    assert 'cd /d "C:\\Users\\ariyast\\HeatWatchApp"' in lines[2]
    assert "update started" in body and "> update_build.log" in body
    assert ":waitloop" in lines and "goto allclosed" in body
    assert "if %WAITS% GEQ 10 goto proceed" in body
    assert 'taskkill /F /IM HeatWatch.exe' in body
    # kill-first: every copy dies before any waiting or building
    assert body.index("taskkill /F /IM HeatWatch.exe") < \
        body.index("call build.bat")
    assert "call build.bat auto >> update_build.log 2>&1" in body
    assert "copy /Y" in body and "%BUILT%" in body and "%LAUNCHED%" in body
    assert 'start "" "%LAUNCHED%"' in body
    # narrated on the console too — no more silent black window
    assert "echo HeatWatch update: closing any running copies..." in body
    assert "echo HeatWatch update: building" in body
    print("PASS helper: kill-first, narration, log, copy-back, relaunch")


def test_helper_launch_has_a_console():
    src = open(os.path.join(os.path.dirname(__file__), "..",
                            "heatwatch_app.py"),
               encoding="utf-8").read()
    assert "CREATE_NEW_CONSOLE" in src
    assert '"DETACHED_PROCESS"' not in src
    print("PASS helper launches with its own console window")


def test_version_is_1_1_0():
    assert gui.VERSION == "1.3.0"
    print("PASS app version is 1.3.0")


def test_startup_command():
    frozen = gui._startup_command(True, r"C:\app\HeatWatch.exe", "x.py")
    assert frozen == '"C:\\app\\HeatWatch.exe" --minimized'
    source = gui._startup_command(False, r"C:\Python\python.exe",
                                  r"C:\app\heatwatch_app.py")
    assert source == ('"C:\\Python\\python.exe" '
                      '"C:\\app\\heatwatch_app.py" --minimized')
    assert gui._wants_minimized(["HeatWatch.exe", "--minimized"])
    assert gui._wants_minimized(["HeatWatch.exe", "/minimized"])
    assert not gui._wants_minimized(["HeatWatch.exe"])
    print("PASS startup entries always launch minimized")


def main():
    test_helper_lines()
    test_helper_launch_has_a_console()
    test_version_is_1_1_0()
    test_startup_command()
    print("ROUND 10 ALL PASS")


if __name__ == "__main__":
    main()
