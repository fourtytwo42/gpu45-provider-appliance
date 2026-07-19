from __future__ import annotations

import json
import unittest

from agentic_benchmark.codex_reference_proxy import build_chat_response, build_turn_prompt, listener_hosts, parse_codex_jsonl


class CodexReferenceProxyTests(unittest.TestCase):
    def test_prompt_preserves_conversation_tools_and_forbids_builtin_execution(self):
        prompt = build_turn_prompt({
            "messages": [{"role": "user", "content": "Find order 42"}],
            "tools": [{"type": "function", "function": {"name": "lookup", "parameters": {"type": "object"}}}],
        })
        self.assertIn("Do not execute shell commands", prompt)
        self.assertIn('"name":"lookup"', prompt)
        self.assertIn('"content":"Find order 42"', prompt)

    def test_jsonl_parser_returns_structured_turn_and_usage(self):
        output = "\n".join([
            json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps({"content": "", "tool_calls": [{"name": "lookup", "arguments_json": "{\\\"id\\\":42}"}]})}}),
            json.dumps({"type": "turn.completed", "usage": {"input_tokens": 100, "cached_input_tokens": 40, "output_tokens": 20, "reasoning_output_tokens": 7}}),
        ])
        result, usage = parse_codex_jsonl(output)
        self.assertEqual("lookup", result["tool_calls"][0]["name"])
        self.assertEqual(100, usage["input_tokens"])
        self.assertEqual(7, usage["reasoning_output_tokens"])

    def test_chat_response_maps_multiple_tool_calls_and_usage(self):
        response = build_chat_response(
            {"content": "", "tool_calls": [
                {"name": "lookup", "arguments_json": '{"id":42}'},
                {"name": "notify", "arguments_json": '{"urgent":true}'},
            ]},
            {"input_tokens": 100, "cached_input_tokens": 40, "output_tokens": 20, "reasoning_output_tokens": 7},
            "codex-gpt-5.6-sol-medium",
        )
        self.assertEqual("tool_calls", response["choices"][0]["finish_reason"])
        self.assertEqual(2, len(response["choices"][0]["message"]["tool_calls"]))
        self.assertEqual(120, response["usage"]["total_tokens"])
        self.assertEqual(7, response["usage"]["completion_tokens_details"]["reasoning_tokens"])

    def test_listener_hosts_adds_docker_bridge_without_public_wildcard(self):
        self.assertEqual(["127.0.0.1", "172.28.0.1"], listener_hosts("127.0.0.1", "172.28.0.1"))
        self.assertNotIn("0.0.0.0", listener_hosts("127.0.0.1", "172.28.0.1"))


if __name__ == "__main__":
    unittest.main()
