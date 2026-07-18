import unittest
from unittest import mock

from agentic_benchmark.runner import ResourceClient, is_scored_task_timeout


class ResourceClientTests(unittest.TestCase):
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
