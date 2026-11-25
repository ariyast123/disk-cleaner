"""Round 1: LibreHardwareMonitor data.json tree parsing."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import heatwatch_core as core


def tree(cpu_sensors, gpu_sensors, cpu_name="Intel Core i7-11800H",
         gpu_name="NVIDIA GeForce RTX 3060 Laptop GPU",
         cpu_fans=None, gpu_fans=None):
    def hw(name, sensors, fans=None):
        children = [{"Text": "Temperatures", "Children": [
            {"Text": n, "Value": v} for n, v in sensors]}]
        if fans:
            children.append({"Text": "Fans", "Children": [
                {"Text": n, "Value": v} for n, v in fans]})
        return {"Text": name, "Children": children}

    return {"Text": "Sensor", "Children": [
        {"Text": "DESKTOP-ARIYA", "Children": [
            hw("Gigabyte B660M", [("System", "45.0 °C")]),
            hw(cpu_name, cpu_sensors, cpu_fans),
            hw(gpu_name, gpu_sensors, gpu_fans),
        ]}]}


def test_package_and_core():
    result = core.parse_lhm_web_tree(tree(
        [("CPU Core #1", "88.0 °C"), ("CPU Core #2", "91.0 °C"),
         ("CPU Package", "93.0 °C"), ("Core Average", "89.0 °C")],
        [("GPU Core", "71.0 °C"), ("GPU Hot Spot", "82.0 °C")]))
    assert result == {"cpu": 93.0, "gpu": 71.0, "fan": None}, result
    print("PASS package + GPU core preferred over hotter siblings")


def test_core_max_fallback():
    result = core.parse_lhm_web_tree(tree(
        [("CPU Core #1", "88.0 °C"), ("CPU Core #2", "95.0 °C")],
        [("GPU Core", "70.0 °C")]))
    assert result["cpu"] == 95.0, result
    print("PASS without a package sensor, the hottest core speaks")


def test_missing_and_garbage():
    empty = {"cpu": None, "gpu": None, "fan": None}
    assert core.parse_lhm_web_tree({}) == empty
    assert core.parse_lhm_web_tree(None) == empty
    assert core.parse_lhm_web_tree({"Children": "junk"}) == empty
    result = core.parse_lhm_web_tree(tree([], [("GPU Core", "66 °C")]))
    assert result == {"cpu": None, "gpu": 66.0, "fan": None}, result
    print("PASS missing hardware and garbage trees yield Nones")


def test_comma_decimals_and_motherboard_ignored():
    result = core.parse_lhm_web_tree(tree(
        [("CPU Package", "97,5 °C")], [("GPU Core", "80,25 °C")]))
    assert result == {"cpu": 97.5, "gpu": 80.25, "fan": None}, result
    print("PASS comma decimal separators parse (locale-proof)")


def test_fan_sensors():
    result = core.parse_lhm_web_tree(tree(
        [("CPU Package", "93.0 °C")], [("GPU Core", "71.0 °C")],
        cpu_fans=[("Fan #1", "2100 RPM"), ("Fan #2", "1800 RPM")],
        gpu_fans=[("Fan #1", "2600 RPM")]))
    assert result["fan"] == 2600.0, result
    assert result["cpu"] == 93.0 and result["gpu"] == 71.0, result
    result = core.parse_lhm_web_tree(tree(
        [("CPU Package", "93.0 °C")], [("GPU Core", "71.0 °C")],
        cpu_fans=[("Fan #1", "1850 RPM")]))
    assert result["fan"] == 1850.0, result
    print("PASS fan RPM: fastest fan wins, plain RPM values parse")


def main():
    test_package_and_core()
    test_core_max_fallback()
    test_missing_and_garbage()
    test_comma_decimals_and_motherboard_ignored()
    test_fan_sensors()
    print("ROUND 1 ALL PASS")


if __name__ == "__main__":
    main()
