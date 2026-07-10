import unittest
from unittest.mock import patch
import gpu45_resource


class LeaseHeartbeatTests(unittest.TestCase):
    def test_transient_manager_failure_does_not_end_lease(self):
        lease = gpu45_resource.Lease.__new__(gpu45_resource.Lease)
        lease.lease_id = "lease"
        import threading
        lease._stop = threading.Event()
        calls = iter([(0, {}), (404, {})])
        with patch.object(gpu45_resource, "_request", side_effect=lambda *_args: next(calls)), patch.object(lease._stop, "wait", side_effect=[False, False, True]):
            lease._heartbeat()
        self.assertTrue(lease._stop.is_set())
