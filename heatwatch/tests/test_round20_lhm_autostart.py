"""Round 20: the LHM autostart helper — task args, elevation, status."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import heatwatch_core as core


class FakeResult:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class Recorder:
    def __init__(self, result=None):
        self.calls = []
        self.result = result or FakeResult(0)
        self.explode = False

    def __call__(self, argv):
        self.calls.append(list(argv))
        if self.explode:
            raise OSError("boom")
        return self.result


def main():
    real_is_windows = core.is_windows
    core.is_windows = lambda: True
    try:
        test_build_task_args()
        test_build_elevated_command()
        test_task_exists()
        test_create_task()
        test_remove_task()
        test_off_windows_is_quiet()
    finally:
        core.is_windows = real_is_windows
    print("ROUND 20 ALL PASS")


def test_build_task_args():
    args = core.build_lhm_task_args(
        r"C:\Program Files\LibreHardwareMonitor\LibreHardwareMonitor.exe")
    assert args == ["schtasks", "/Create", "/TN", "LibreHardwareMonitor",
                    "/TR",
                    r'"C:\Program Files\LibreHardwareMonitor'
                    r'\LibreHardwareMonitor.exe"',
                    "/SC", "ONLOGON", "/RL", "HIGHEST", "/F"], args
    assert core.build_lhm_task_args("") is None
    assert core.build_lhm_task_args("   ") is None
    assert core.build_lhm_task_args(None) is None
    print("PASS task args: elevated logon task, quoted exe, "
          "blank path is None")


def test_build_elevated_command():
    argv = ["schtasks", "/Create", "/TN", "LibreHardwareMonitor"]
    cmd = core.build_elevated_command(argv)
    assert cmd[0] == "powershell"
    assert cmd[1:3] == ["-NoProfile", "-NonInteractive"]
    script = cmd[4]
    assert "-Verb RunAs" in script
    assert "-Wait -PassThru" in script
    assert "exit $p.ExitCode" in script
    assert "'schtasks'" in script
    assert "'/Create'" in script
    assert "catch { exit 1 }" in script
    # A single quote in a path is doubled, never breaks the script.
    tricky = core.build_elevated_command(
        ["schtasks", "/TR", '"C:\\O\'Neil\\app.exe"'])
    assert "O''Neil" in tricky[4]
    assert core.build_elevated_command([]) is None
    assert core.build_elevated_command(None) is None
    print("PASS elevation wraps the call in RunAs and carries the "
          "exit code back")


def test_task_exists():
    recorder = Recorder(FakeResult(0, "TaskName: LibreHardwareMonitor"))
    assert core.lhm_task_exists(runner=recorder) is True
    assert recorder.calls == [["schtasks", "/Query", "/TN",
                               "LibreHardwareMonitor"]]
    recorder = Recorder(FakeResult(1, "", "ERROR: cannot find"))
    assert core.lhm_task_exists(runner=recorder) is False
    recorder = Recorder()
    recorder.explode = True
    assert core.lhm_task_exists(runner=recorder) is False
    print("PASS status query: present, absent, and a failing "
          "spawn all answer cleanly")


def test_create_task():
    exe = (r"C:\Program Files\LibreHardwareMonitor"
           r"\LibreHardwareMonitor.exe")
    recorder = Recorder(FakeResult(0))
    ok, message = core.create_lhm_task(exe, runner=recorder)
    assert ok is True, message
    assert "every sign-in" in message
    assert len(recorder.calls) == 1
    script = recorder.calls[0][4]
    assert "schtasks" in script and "/Create" in script
    assert "/RL" in script and "HIGHEST" in script
    assert "/SC" in script and "ONLOGON" in script
    assert ('"C:\\Program Files\\LibreHardwareMonitor'
            '\\LibreHardwareMonitor.exe"') in script

    recorder = Recorder(FakeResult(1, "", "Access is denied."))
    ok, message = core.create_lhm_task(exe, runner=recorder)
    assert ok is False
    assert "admin prompt" in message

    recorder = Recorder(FakeResult(0))
    ok, _ = core.create_lhm_task("  ", runner=recorder)
    assert ok is False
    assert recorder.calls == []
    print("PASS create: success carries the task, failure asks for "
          "the admin prompt, blank path never spawns")


def test_remove_task():
    recorder = Recorder(FakeResult(0))
    ok, message = core.remove_lhm_task(runner=recorder)
    assert ok is True, message
    script = recorder.calls[0][4]
    assert "/Delete" in script
    assert "LibreHardwareMonitor" in script
    assert "-Verb RunAs" in script
    recorder = Recorder(FakeResult(1, "", "ERROR: cannot find"))
    ok, message = core.remove_lhm_task(runner=recorder)
    assert ok is False
    assert "admin prompt" in message
    print("PASS remove: elevated delete, failure asks for the "
          "admin prompt")


def test_off_windows_is_quiet():
    core.is_windows = lambda: False
    try:
        recorder = Recorder(FakeResult(0))
        assert core.lhm_task_exists(runner=recorder) is False
        assert recorder.calls == []
        ok, message = core.create_lhm_task(r"C:\x\LHM.exe",
                                           runner=recorder)
        assert ok is False and "Windows only" in message
        ok, message = core.remove_lhm_task(runner=recorder)
        assert ok is False and "Windows only" in message
        assert recorder.calls == []
    finally:
        core.is_windows = lambda: True
    print("PASS off Windows nothing spawns and every call says so")


if __name__ == "__main__":
    main()
