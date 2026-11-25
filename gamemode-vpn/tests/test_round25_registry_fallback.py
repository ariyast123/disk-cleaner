"""Round 25 — registry uninstall-key fallback for Proton's location (v1.4.2).

Roadmap item 1 left this open: if a future Proton update changes the
install layout so the folder scan finds nothing, the Add/Remove
Programs uninstall entry still names the real install folder. The
fallback must stay honest: it only trusts entries whose DisplayName
names Proton VPN, and it only returns a path when the exe file
really exists. Any registry problem degrades to None, never a
guess, and non-Windows platforms (no winreg) always return None.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import gamemode_core as core

TMP = tempfile.mkdtemp(prefix="gmvpn-reg-")
UNINSTALL = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"


class _FakeKey:
    def __init__(self, node):
        self.node = node


class FakeWinreg:
    """Minimal winreg stand-in backed by nested dicts.

    A node is a dict: string values are registry values, dict values
    are subkeys. OpenKey accepts a hive name or a parent key handle.
    """
    HKEY_LOCAL_MACHINE = "HKLM"
    HKEY_CURRENT_USER = "HKCU"

    def __init__(self, tree, explode=False):
        self._tree = tree
        self._explode = explode

    def OpenKey(self, hive, subkey):
        if self._explode:
            raise OSError("registry unavailable")
        node = hive.node if isinstance(hive, _FakeKey) else self._tree.get(hive, {})
        for part in subkey.split("\\"):
            nxt = node.get(part)
            if not isinstance(nxt, dict):
                raise OSError("no such key")
            node = nxt
        return _FakeKey(node)

    def EnumKey(self, key, index):
        names = [n for n, v in key.node.items() if isinstance(v, dict)]
        if index >= len(names):
            raise OSError("no more items")
        return names[index]

    def QueryValueEx(self, key, name):
        value = key.node.get(name)
        if not isinstance(value, str):
            raise OSError("no such value")
        return value, 1

    def CloseKey(self, key):
        return None


def _touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write("exe")


def _tree(entries):
    """entries: {app key name: {value name: value}} under HKLM Uninstall."""
    node = {"HKLM": {}}
    cur = node["HKLM"]
    for part in UNINSTALL.split("\\"):
        cur[part] = {}
        cur = cur[part]
    cur.update(entries)
    return node


def test_install_location_versioned():
    base = os.path.join(TMP, "proton-vpn")
    client = os.path.join(base, "v5.2.0", "ProtonVPN.Client.exe")
    _touch(client)
    _touch(os.path.join(base, "v4.9.0", "ProtonVPN.Client.exe"))
    reg = FakeWinreg(_tree({"Proton VPN": {
        "DisplayName": "Proton VPN",
        "InstallLocation": base}}))
    assert core.find_proton_exe_via_uninstall_key(reg) == client
    print("PASS InstallLocation: versioned subfolder, newest wins")


def test_install_location_flat_and_client_first():
    base = os.path.join(TMP, "proton-flat")
    _touch(os.path.join(base, "ProtonVPN.exe"))
    _touch(os.path.join(base, "ProtonVPN.Client.exe"))
    reg = FakeWinreg(_tree({"ProtonVPN": {
        "DisplayName": "ProtonVPN",
        "InstallLocation": base}}))
    assert core.find_proton_exe_via_uninstall_key(reg) == \
        os.path.join(base, "ProtonVPN.Client.exe")
    print("PASS InstallLocation: flat folder, Client name first")


def test_other_apps_ignored():
    base = os.path.join(TMP, "other-app")
    _touch(os.path.join(base, "ProtonVPN.exe"))
    reg = FakeWinreg(_tree({
        "Some Other App": {"DisplayName": "Some Other App",
                           "InstallLocation": base},
        "Proton Mail": {"DisplayName": "Proton Mail",
                        "InstallLocation": base},
    }))
    assert core.find_proton_exe_via_uninstall_key(reg) is None
    print("PASS non-Proton-VPN entries never yield a path")


def test_display_icon_and_uninstall_string():
    base = os.path.join(TMP, "proton-icon")
    exe = os.path.join(base, "ProtonVPN.Client.exe")
    _touch(exe)
    reg = FakeWinreg(_tree({"Proton VPN": {
        "DisplayName": "Proton VPN",
        "DisplayIcon": '"%s,0"' % exe}}))
    assert core.find_proton_exe_via_uninstall_key(reg) == exe
    uninstaller = os.path.join(base, "uninstall.exe")
    _touch(uninstaller)
    reg = FakeWinreg(_tree({"Proton VPN": {
        "DisplayName": "Proton VPN",
        "UninstallString": '"%s"' % uninstaller}}))
    assert core.find_proton_exe_via_uninstall_key(reg) == exe
    print("PASS DisplayIcon / UninstallString derive the folder")


def test_missing_or_broken_registry():
    # Entry names Proton VPN but the folder holds no exe: no guess.
    base = os.path.join(TMP, "proton-empty")
    os.makedirs(base, exist_ok=True)
    reg = FakeWinreg(_tree({"Proton VPN": {
        "DisplayName": "Proton VPN",
        "InstallLocation": base}}))
    assert core.find_proton_exe_via_uninstall_key(reg) is None
    # InstallLocation points nowhere.
    reg = FakeWinreg(_tree({"Proton VPN": {
        "DisplayName": "Proton VPN",
        "InstallLocation": os.path.join(TMP, "nope")}}))
    assert core.find_proton_exe_via_uninstall_key(reg) is None
    # No uninstall key at all.
    assert core.find_proton_exe_via_uninstall_key(FakeWinreg({})) is None
    # Registry itself unreadable.
    assert core.find_proton_exe_via_uninstall_key(
        FakeWinreg({}, explode=True)) is None
    # Non-Windows: no winreg module to import.
    assert core.find_proton_exe_via_uninstall_key(None) is None
    # Non-string values are skipped, not crashed on.
    reg = FakeWinreg(_tree({"Proton VPN": {
        "DisplayName": 12345,
        "InstallLocation": base}}))
    assert core.find_proton_exe_via_uninstall_key(reg) is None
    print("PASS missing / broken registry degrades to None")


def test_find_proton_exe_wiring():
    base = os.path.join(TMP, "proton-wired")
    client = os.path.join(base, "ProtonVPN.Client.exe")
    _touch(client)
    reg = FakeWinreg(_tree({"Proton VPN": {
        "DisplayName": "Proton VPN",
        "InstallLocation": base}}))
    # Registry is the last resort: folder scan and override still win.
    scan_base = os.path.join(TMP, "scan")
    scan_exe = os.path.join(scan_base, "ProtonVPN.exe")
    _touch(scan_exe)
    assert core.find_proton_exe({}, bases=[scan_base],
                                winreg_module=reg) == scan_exe
    override = os.path.join(TMP, "custom.exe")
    _touch(override)
    assert core.find_proton_exe({"proton_path": override}, bases=[scan_base],
                                winreg_module=reg) == override
    # Nothing else matches: the registry path is returned.
    assert core.find_proton_exe({}, bases=[os.path.join(TMP, "nope")],
                                winreg_module=reg) == client
    # And without a registry to ask, still None (no guess).
    assert core.find_proton_exe({}, bases=[os.path.join(TMP, "nope")]) is None
    print("PASS find_proton_exe: registry is last resort, precedence kept")


if __name__ == "__main__":
    test_install_location_versioned()
    test_install_location_flat_and_client_first()
    test_other_apps_ignored()
    test_display_icon_and_uninstall_string()
    test_missing_or_broken_registry()
    test_find_proton_exe_wiring()
    print("ROUND 25: ALL PASS")
