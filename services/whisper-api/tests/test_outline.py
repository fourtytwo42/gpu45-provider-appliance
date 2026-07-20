import unittest

from whisper_api.outline import OutlineGenerator, clean_markdown, render_outline, response_text, split_transcript, transcript_body


class OutlineTests(unittest.TestCase):
    def test_transcript_body_discards_transcript_metadata(self):
        markdown = "# Transcript: demo.wav\n\n- Model: `small`\n\n## Transcript\n\n**[00:00]** Hello"
        self.assertEqual(transcript_body(markdown), "**[00:00]** Hello")

    def test_split_transcript_keeps_paragraphs_when_possible(self):
        markdown = "## Transcript\n\nFirst paragraph.\n\nSecond paragraph.\n\nThird paragraph."
        chunks = split_transcript(markdown, max_chars=35)
        self.assertEqual(chunks, ["First paragraph.\n\nSecond paragraph.", "Third paragraph."])

    def test_response_text_accepts_standard_chat_completion(self):
        payload = {"choices": [{"message": {"content": "```markdown\n## Overview\n\n- Item\n```"}}]}
        self.assertEqual(response_text(payload), "## Overview\n\n- Item")

    def test_generator_uses_hierarchical_pass_for_multiple_chunks(self):
        calls = []

        def complete(prompt, max_tokens):
            calls.append((prompt, max_tokens))
            return "## Notes\n\n- Result"

        generator = OutlineGenerator(model="fast", completion=complete)
        markdown = "## Transcript\n\n" + "\n\n".join(["A" * 70000, "B" * 70000])
        result = generator.generate(markdown, "demo.md")
        self.assertEqual(result, "## Notes\n\n- Result")
        self.assertGreaterEqual(len(calls), 3)
        self.assertIn("Create a useful final outline", calls[-1][0])

    def test_render_outline_adds_downloadable_markdown_metadata(self):
        rendered = render_outline("demo.wav", "fast-model", "# Outline: demo\n\n## Overview\n- Item")
        self.assertTrue(rendered.startswith("# Outline: demo.wav"))
        self.assertIn("- Outline model: `fast-model`", rendered)
        self.assertIn("## Overview", rendered)

    def test_clean_markdown_rejects_empty_output(self):
        with self.assertRaisesRegex(RuntimeError, "no Markdown"):
            clean_markdown("   ")


if __name__ == "__main__":
    unittest.main()
