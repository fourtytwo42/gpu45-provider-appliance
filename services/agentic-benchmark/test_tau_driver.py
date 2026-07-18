import unittest

from agentic_benchmark.tau_driver import TAU_AGENT_MAX_TOKENS, TAU_USER_MAX_TOKENS, build_llm_args


class TauDriverConfigTests(unittest.TestCase):
    def test_target_calls_are_bounded_and_correlated(self):
        headers = {"X-GPU45-Benchmark-Task": "task-1"}

        target, _ = build_llm_args(1800, headers)

        self.assertEqual(TAU_AGENT_MAX_TOKENS, target["max_tokens"])
        self.assertEqual(headers, target["extra_headers"])
        self.assertEqual("http://127.0.0.1:30001/v1", target["api_base"])

    def test_cpu_user_simulator_is_short_and_non_reasoning(self):
        _, user = build_llm_args(1800, {})

        self.assertEqual(TAU_USER_MAX_TOKENS, user["max_tokens"])
        self.assertEqual(
            {
                "chat_template_kwargs": {"enable_thinking": False},
                "reasoning_budget": 0,
            },
            user["extra_body"],
        )
        self.assertEqual("http://127.0.0.1:30002/v1", user["api_base"])


if __name__ == "__main__":
    unittest.main()
