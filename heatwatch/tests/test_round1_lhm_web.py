"""Round 1: LibreHardwareMonitor data.json tree parsing."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import heatwatch_core as core


def tree(cpu_sensors, gpu_sensors, cpu_name="Intel Core i7-11800H",
         gpu_name="NVIDIA GeForce RTX 3060 Laptop GPU"):
    def hw(name, sensors):
        return {"Text": name, "Children": [
            {"Text": "Temperatures", "Children": [
                {"Text": n, "Value": v} for n, v in sensors]}]}

    return {"Text": "Sensor", "Children": [
        {"Text": "DESKTOP-ARIYA", "Children": [
            hw("Gigabyte B660M", [("System", "45.0 °C")]),
            hw(cpu_name, cpu_sensors),
            hw(gpu_name, gpu_sensors),
        ]}]}


def test_package_and_core():
    result = core.parse_lhm_web_tree(tree(
        [("CPU Core #1", "88.0 °C"), ("CPU Core #2", "91.0 °C"),
         ("CPU Package", "93.0 °C"), ("Core Average", "89.0 °C")],
        [("GPU Core", "71.0 °C"), ("GPU Hot Spot", "82.0 °C")]))
    assert result == {"cpu": 93.0, "gpu": 71.0}, result
    print("PASS package + GPU core preferred over hotter siblings")


def test_core_max_fallback():
    result = core.parse_lhm_web_tree(tree(
        [("CPU Core #1", "88.0 °C"), ("CPU Core #2", "95.0 °C")],
        [("GPU Core", "70.0 °C")]))
    assert result["cpu"] == 95.0, result
    print("PASS without a package sensor, the hottest core speaks")


def test_missing_and_garbage():
    assert core.parse_lhm_web_tree({}) == {"cpu": None, "gpu": None}
    assert core.parse_lhm_web_tree(None) == {"cpu": None, "gpu": None}
    assert core.parse_lhm_web_tree({"Children": "junk"}) == {
        "cpu": None, "gpu": None}
    result = core.parse_lhm_web_tree(tree([], [("GPU Core", "66 °C")]))
    assert result == {"cpu": None, "gpu": 66.0}, result
    print("PASS missing hardware and garbage trees yield Nones")


def test_comma_decimals_and_motherboard_ignored():
    result = core.parse_lhm_web_tree(tree(
        [("CPU Package", "97,5 °C")], [("GPU Core", "80,25 °C")]))
    assert result == {"cpu": 97.5, "gpu": 80.25}, result
    print("PASS comma decimal separators parse (locale-proof)")


def main():
    test_package_and_core()
    test_core_max_fallback()
    test_missing_and_garbage()
    test_comma_decimals_and_motherboard_ignored()
    print("ROUND 1 ALL PASS")


if __name__ == "__main__":
    main()
