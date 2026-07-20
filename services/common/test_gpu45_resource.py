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

    def test_profile_helpers_use_the_authenticated_manager_contract(self):
        with patch.object(gpu45_resource, "_request", return_value=(200, {"profileName": "fast"})) as request:
            self.assertEqual(gpu45_resource.activate_profile("fast"), {"profileName": "fast"})
        request.assert_called_once_with("/v1/provider/activate", {"profileName": "fast"}, timeout=900)

    def test_resource_state_rejects_manager_failure(self):
        with patch.object(gpu45_resource, "_request", return_value=(503, {"error": "busy"})):
            with self.assertRaisesRegex(RuntimeError, "busy"):
                gpu45_resource.resource_state()

    def test_worker_touch_and_provider_unload(self):
        with patch.object(gpu45_resource, "_request", return_value=(200, {"ok": True})) as request:
            gpu45_resource.touch_worker("whisper")
            gpu45_resource.unload_provider()
        self.assertEqual(
            request.call_args_list,
            [
                unittest.mock.call("/v1/workers/whisper/touch", {}),
                unittest.mock.call("/v1/provider/unload", {}, timeout=120),
            ],
        )
