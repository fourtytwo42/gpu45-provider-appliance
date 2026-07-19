import tempfile
import unittest
from pathlib import Path

from agentic_benchmark.telemetry import HardwareReader, TaskResourceSampler, WallClockSampler, discover_gpu_card


class TelemetryTests(unittest.TestCase):
    def test_discovers_largest_amd_card_and_reads_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            drm = root / "drm"
            for name, vendor, vram in (("card0", "0x10de", 1), ("card1", "0x1002", 32_000_000_000)):
                device = drm / name / "device"
                device.mkdir(parents=True)
                (device / "vendor").write_text(vendor)
                (device / "mem_info_vram_total").write_text(str(vram))
            device = drm / "card1" / "device"
            (device / "mem_info_vram_used").write_text("1234")
            hwmon = device / "hwmon" / "hwmon1"
            hwmon.mkdir(parents=True)
            (hwmon / "name").write_text("amdgpu")
            (hwmon / "power1_average").write_text("150000000")
            (hwmon / "temp1_input").write_text("72000")
            (hwmon / "temp2_input").write_text("88000")
            meminfo = root / "meminfo"
            meminfo.write_text("MemTotal: 1000 kB\nMemAvailable: 400 kB\n")

            self.assertEqual(drm / "card1", discover_gpu_card(drm))
            sample = HardwareReader(drm, meminfo).read()
            self.assertEqual(150.0, sample["power_w"])
            self.assertEqual(88.0, sample["gpu_temp_c"])
            self.assertEqual(1234, sample["vram_bytes"])
            self.assertEqual(600 * 1024, sample["ram_bytes"])

    def test_sampler_integrates_gross_and_incremental_energy(self):
        class Reader:
            def __init__(self):
                self.at = 0

            def read(self):
                value = {"at": float(self.at), "power_w": 100.0, "gpu_temp_c": 80.0, "vram_bytes": 10, "ram_bytes": 20}
                self.at += 1
                return value

        clock_values = iter((0.0, 2.0))
        sampler = TaskResourceSampler(Reader(), idle_power_w=20.0, interval=1000, clock=lambda: next(clock_values))
        sampler.start()
        result = sampler.stop()
        self.assertAlmostEqual(100.0 / 3600.0, result["gross_energy_wh"], places=6)
        self.assertAlmostEqual(80.0 / 3600.0, result["incremental_energy_wh"], places=6)
        self.assertEqual(100.0, result["peak_power_w"])

    def test_wall_clock_sampler_does_not_attribute_local_gpu_energy(self):
        clock_values = iter((10.0, 12.5))
        sampler = WallClockSampler(clock=lambda: next(clock_values))
        sampler.start()

        result = sampler.stop()

        self.assertEqual(2500, result["wall_duration_ms"])
        self.assertEqual(0, result["sample_count"])
        self.assertIsNone(result["peak_power_w"])


if __name__ == "__main__":
    unittest.main()
