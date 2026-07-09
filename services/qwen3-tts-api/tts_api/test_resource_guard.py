import unittest
from unittest.mock import patch
from tts_api import resource_guard


class ResourceGuardTests(unittest.TestCase):
    def test_nested_guard_reuses_outer_lease(self):
        class Lease:
            released = 0
            def release(self): self.released += 1
        lease = Lease()
        resource_guard._LEASE_LOCAL.depth = 0
        with patch.object(resource_guard, "acquire_lease", return_value=lease) as acquire:
            with resource_guard.tts_vram_guard("audiobook", device="cuda:0"):
                with resource_guard.tts_vram_guard("synthesize", device="cuda:0"):
                    self.assertEqual(resource_guard._LEASE_LOCAL.depth, 2)
        self.assertEqual(acquire.call_count, 1)
        self.assertEqual(lease.released, 1)
