"""Round 14 — finish_update.bat copies the new exe back over the
launched copy, so a taskbar pin can never resurrect an old version."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import gamemode_vpn_app as gui

PROJECT = r"C:\Users\ariyast\GameModeProject"
BUILT = os.path.join(PROJECT, "dist", "GameModeVPN.exe")


def test_helper_waits_builds_and_copies_back():
    launched = r"C:\Users\ariyast\Desktop\GameModeVPN.exe"
    lines = gui.update_helper_lines(PROJECT, launched)
    body = "\n".join(lines)
    assert ":waitloop" in body and "GameModeVPN.exe" in body
    # the build runs unattended (auto = no pause) and logs to a file
    assert "call build.bat auto > update_build.log 2>&1" in body
    assert f'set "BUILT={BUILT}"' in body
    assert f'set "LAUNCHED={launched}"' in body
    # the copy-back guard: only when the paths differ (case-insensitive)
    assert 'if /I not "%BUILT%"=="%LAUNCHED%" copy /Y "%BUILT%" "%LAUNCHED%" >NUL' in body
    # and it relaunches the launched path, not just the dist build
    assert 'start "" "%LAUNCHED%"' in body
    # if the build failed (no fresh exe), the old copy still relaunches
    assert ') else (' in body
    assert 'if exist "%LAUNCHED%" start "" "%LAUNCHED%"' in body
    print("PASS helper copies the fresh exe over the launched copy")


def test_helper_with_dist_launch():
    lines = gui.update_helper_lines(PROJECT, BUILT)
    body = "\n".join(lines)
    assert f'set "BUILT={BUILT}"' in body
    assert f'set "LAUNCHED={BUILT}"' in body
    assert 'start "" "%LAUNCHED%"' in body
    print("PASS helper is consistent when launched from dist")


def test_version_is_123():
    assert gui.VERSION == "1.2.4"
    print("PASS app version is 1.2.4")


if __name__ == "__main__":
    test_helper_waits_builds_and_copies_back()
    test_helper_with_dist_launch()
    test_version_is_123()
    print("ROUND 14: ALL PASS")
