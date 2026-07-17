import unittest
from unittest import mock

from agentic_benchmark.runner import ResourceClient


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


if __name__ == "__main__":
    unittest.main()
