import unittest
from unittest import mock

from agentic_benchmark.runner import (
    ExternalBenchmarkLease,
    ResourceClient,
    is_external_profile,
    is_scored_task_timeout,
    requires_gpu45_lease,
)


class ResourceClientTests(unittest.TestCase):
    def test_external_reference_uses_a_lease_only_for_tau_simulator(self):
        self.assertTrue(is_external_profile({"executionMode": "external-openai"}))
        self.assertFalse(is_external_profile({"backend": "llama.cpp"}))
        self.assertFalse(requires_gpu45_lease({"executionMode": "external-openai"}, {"adapter": "harbor"}))
        self.assertTrue(requires_gpu45_lease({"executionMode": "external-openai"}, {"adapter": "tau"}))
        self.assertTrue(requires_gpu45_lease({"backend": "llama.cpp"}, {"adapter": "harbor"}))
        lease = ExternalBenchmarkLease()
        lease.ensure_active()
        self.assertFalse(lease.lost.is_set())

    def test_activate_retries_while_resource_manager_transitions(self):
        client = ResourceClient()
        client.post = mock.Mock(side_effect=[
            (503, {"error": "transitioning"}),
            (200, {"ok": True}),
        ])

        with mock.patch("agentic_benchmark.runner.time.sleep"):
            client.activate("model-a")

        self.assertEqual(2, client.post.call_count)
        for call in client.post.call_args_list:
            self.assertEqual(ResourceClient.PROVIDER_ACTIVATION_TIMEOUT, call.kwargs["timeout"])

    def test_agentic_task_timeout_is_scored_not_retried_as_infrastructure(self):
        self.assertTrue(is_scored_task_timeout({"adapter": "tau"}, TimeoutError("expired")))
        self.assertTrue(is_scored_task_timeout({"adapter": "swebench"}, TimeoutError("expired")))
        self.assertTrue(is_scored_task_timeout({"adapter": "harbor"}, TimeoutError("expired")))
        self.assertFalse(is_scored_task_timeout({"adapter": "bfcl"}, TimeoutError("expired")))
        self.assertFalse(is_scored_task_timeout({"adapter": "tau"}, RuntimeError("transport")))


if __name__ == "__main__":
    unittest.main()
