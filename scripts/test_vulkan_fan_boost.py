import importlib.machinery
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "deploy" / "usr" / "local" / "sbin" / "gpu45-v620-fan-controller"


def load_controller():
    loader = importlib.machinery.SourceFileLoader("gpu45_fan_controller", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class VulkanFanBoostTests(unittest.TestCase):
    def setUp(self):
        self.controller = load_controller()

    def test_boost_requires_profile_and_busy_gpu(self):
        self.assertFalse(self.controller.should_boost_fans(False, 100))
        self.assertFalse(self.controller.should_boost_fans(True, 4))
        self.assertTrue(self.controller.should_boost_fans(True, 5))

    def test_live_owner_enables_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            flag = Path(directory) / "boost"
            flag.write_text(str(os.getpid()), encoding="utf-8")
            self.controller.BOOST_FLAG = str(flag)
            self.assertTrue(self.controller.fast_profile_active())

    def test_stale_owner_is_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            flag = Path(directory) / "boost"
            flag.write_text("99999999", encoding="utf-8")
            self.controller.BOOST_FLAG = str(flag)
            self.assertFalse(self.controller.fast_profile_active())
            self.assertFalse(flag.exists())


if __name__ == "__main__":
    unittest.main()
