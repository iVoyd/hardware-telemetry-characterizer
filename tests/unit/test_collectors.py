from __future__ import annotations

from datetime import UTC, datetime

from conftest import FakeFilesystem, FakeRunner
from htc.adapters import CommandResult, CommandTimeout, CommandUnavailable
from htc.collectors.hwmon import HWMONCollector
from htc.collectors.ipmi import IPMICollector
from htc.collectors.network import NetworkCollector
from htc.collectors.smart import SmartCollector
from htc.collectors.system import SystemCollector
from htc.measurement import Quality

NOW = datetime(2025, 1, 1, tzinfo=UTC)


def test_hwmon_preserves_instances_with_identical_driver_names() -> None:
    files = {
        "/sys/class/hwmon/hwmon0/name": "nvme\n",
        "/sys/class/hwmon/hwmon0/temp1_input": "41000\n",
        "/sys/class/hwmon/hwmon1/name": "nvme\n",
        "/sys/class/hwmon/hwmon1/temp1_input": "52000\n",
    }
    fs = FakeFilesystem(files, ["/sys/class/hwmon/hwmon0", "/sys/class/hwmon/hwmon1"])
    measurements = HWMONCollector(filesystem=fs).collect(NOW)
    values = {(item.device_id, item.channel): item.value for item in measurements}
    assert values[("nvme:hwmon0", "temp1")] == 41.0
    assert values[("nvme:hwmon1", "temp1")] == 52.0


def test_hwmon_reports_a_channel_missing_mid_run() -> None:
    files = {
        "/sys/class/hwmon/hwmon0/name": "coretemp\n",
        "/sys/class/hwmon/hwmon0/temp1_input": "41000\n",
    }
    fs = FakeFilesystem(files, ["/sys/class/hwmon/hwmon0"])
    collector = HWMONCollector(filesystem=fs)
    assert collector.collect(NOW)[0].quality == Quality.GOOD
    del fs.files["/sys/class/hwmon/hwmon0/temp1_input"]
    missing = collector.collect(NOW)
    assert any(item.quality == Quality.MISSING for item in missing)


def test_system_collector_calculates_cpu_delta_and_degrades_cpufreq() -> None:
    fs = FakeFilesystem(
        {
            "/proc/stat": "cpu  100 0 100 800 0 0 0 0\ncpu0 50 0 50 400 0 0 0 0\n",
            "/proc/loadavg": "0.25 0.50 0.75 1/10 1234\n",
            "/proc/meminfo": "MemAvailable:       2048 kB\n",
        }
    )
    collector = SystemCollector(filesystem=fs)
    first = collector.collect(NOW)
    assert (
        next(item for item in first if item.channel == "cpu_utilization").quality
        == Quality.UNAVAILABLE
    )
    fs.files["/proc/stat"] = "cpu  150 0 150 850 0 0 0 0\ncpu0 75 0 75 425 0 0 0 0\n"
    second = collector.collect(NOW)
    utilization = next(item for item in second if item.channel == "cpu_utilization")
    assert utilization.quality == Quality.GOOD
    assert utilization.value == 66.66666666666667
    assert (
        next(item for item in second if item.channel == "frequency").quality == Quality.UNAVAILABLE
    )


def test_ipmi_parses_measurements_and_status() -> None:
    runner = FakeRunner(
        {
            ("ipmitool", "sensor"): CommandResult(
                ("ipmitool", "sensor"),
                0,
                "CPU Temp | 42 | degrees C | ok\nFan | 1200 | RPM | ok\n",
                "",
                0.01,
            )
        }
    )
    measurements = IPMICollector(runner=runner).collect(NOW)
    assert any(item.channel == "CPU Temp" and item.value == 42 for item in measurements)
    assert any(item.channel == "Fan.status" and item.value == "ok" for item in measurements)


def test_ipmi_timeout_and_malformed_output_are_explicit() -> None:
    timeout = FakeRunner({("ipmitool", "sensor"): CommandTimeout("timeout")})
    assert IPMICollector(runner=timeout).collect(NOW)[0].quality == Quality.TIMEOUT
    malformed = FakeRunner(
        {
            ("ipmitool", "sensor"): CommandResult(
                ("ipmitool", "sensor"), 0, "not a sensor row\n", "", 0.01
            )
        }
    )
    assert IPMICollector(runner=malformed).collect(NOW)[0].quality == Quality.PARSE_ERROR


def test_smart_discovers_all_nvme_controllers_and_parses_fields() -> None:
    scan = CommandResult(
        ("smartctl", "--scan-open"), 0, "/dev/nvme0 -d nvme\n/dev/nvme1 -d nvme\n", "", 0.01
    )
    smart_text = """SMART overall-health self-assessment test result: PASSED
Critical Warning:                   0x00
Temperature:                        37 Celsius
Temperature Sensor 1:               39 Celsius
Available Spare:                    100%
Percentage Used:                    2%
Power On Hours:                     10
Power Cycles:                       3
Unsafe Shutdowns:                   1
Media and Data Integrity Errors:    0
Error Information Log Entries:      0
"""
    runner = FakeRunner(
        {
            ("smartctl", "--scan-open"): scan,
            ("smartctl", "-a", "-d", "nvme", "/dev/nvme0"): CommandResult(
                (), 0, smart_text, "", 0.01
            ),
            ("smartctl", "-a", "-d", "nvme", "/dev/nvme1"): CommandResult(
                (), 0, smart_text, "", 0.01
            ),
        }
    )
    measurements = SmartCollector(runner=runner).collect(NOW)
    devices = {item.device_id for item in measurements if item.channel == "composite_temperature"}
    assert devices == {"nvme0", "nvme1"}
    assert any(item.channel == "unsafe_shutdowns" and item.value == 1 for item in measurements)


def test_missing_smartctl_is_unavailable_not_a_dut_failure() -> None:
    runner = FakeRunner({("smartctl", "--scan-open"): CommandUnavailable("missing")})
    measurement = SmartCollector(runner=runner).collect(NOW)[0]
    assert measurement.quality == Quality.UNAVAILABLE


def test_network_collector_reads_standard_sysfs_counters() -> None:
    root = "/sys/class/net/eth0"
    files = {
        f"{root}/carrier": "1\n",
        f"{root}/speed": "1000\n",
        **{f"{root}/statistics/{counter}": "7\n" for counter in NetworkCollector._COUNTERS},
    }
    fs = FakeFilesystem(files, [root])
    measurements = NetworkCollector(filesystem=fs).collect(NOW)
    assert next(item for item in measurements if item.channel == "carrier").value == 1
    assert next(item for item in measurements if item.channel == "speed").value == 1000
