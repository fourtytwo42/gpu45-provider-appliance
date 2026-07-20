from __future__ import annotations

import json
import os
import re
import urllib.request
from collections.abc import Callable
from datetime import datetime, timezone


OUTLINE_PROFILE = os.environ.get(
    "WHISPER_OUTLINE_PROFILE",
    "gpu45-m-shq8-mtp-opta-q5-k-m-69f462b8",
)
OUTLINE_MODEL = os.environ.get(
    "WHISPER_OUTLINE_MODEL",
    "M-SHQ8-MTP-OptA-Q5_K_M-69f462b8",
)
OUTLINE_LONG_PROFILE = os.environ.get(
    "WHISPER_OUTLINE_LONG_PROFILE",
    "gpu45-qwen3-6-35b-a3b-ud-q4_k_xl-b420e923",
)
OUTLINE_LONG_MODEL = os.environ.get(
    "WHISPER_OUTLINE_LONG_MODEL",
    "Qwen3.6-35B-A3B-UD-Q4_K_XL-b420e923",
)
BACKEND_URL = os.environ.get("WHISPER_OUTLINE_BACKEND_URL", "http://127.0.0.1:30000").rstrip("/")
MAX_CHUNK_CHARS = max(8_000, int(os.environ.get("WHISPER_OUTLINE_CHUNK_CHARS", "60000")))


def transcript_body(markdown: str) -> str:
    marker = "## Transcript"
    if marker in markdown:
        return markdown.split(marker, 1)[1].strip()
    return markdown.strip()


def _split_oversized_paragraph(paragraph: str, max_chars: int) -> list[str]:
    lines = [line.strip() for line in paragraph.splitlines() if line.strip()]
    if len(lines) > 1:
        parts: list[str] = []
        for line in lines:
            parts.extend(_split_oversized_paragraph(line, max_chars))
        return parts
    words = paragraph.split()
    parts, current = [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > max_chars:
            parts.append(current)
            current = word
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts


def split_transcript(markdown: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    body = transcript_body(markdown)
    paragraphs = [item.strip() for item in re.split(r"\n\s*\n", body) if item.strip()]
    expanded = [part for paragraph in paragraphs for part in _split_oversized_paragraph(paragraph, max_chars)]
    chunks: list[str] = []
    current = ""
    for paragraph in expanded:
        candidate = f"{current}\n\n{paragraph}".strip()
        if current and len(candidate) > max_chars:
            chunks.append(current)
            current = paragraph
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks or [body]


def outline_target(markdown: str) -> tuple[str, str]:
    if len(transcript_body(markdown)) > MAX_CHUNK_CHARS:
        return OUTLINE_LONG_PROFILE, OUTLINE_LONG_MODEL
    return OUTLINE_PROFILE, OUTLINE_MODEL


def clean_markdown(value: str) -> str:
    text = value.strip()
    match = re.fullmatch(r"```(?:markdown|md)?\s*(.*?)\s*```", text, flags=re.IGNORECASE | re.DOTALL)
    if match:
        text = match.group(1).strip()
    text = re.sub(r"^#\s+Outline[^\n]*\n+", "", text, flags=re.IGNORECASE)
    if not text:
        raise RuntimeError("outline model returned no Markdown content")
    return text


def response_text(payload: dict) -> str:
    choices = payload.get("choices") or []
    if not choices:
        raise RuntimeError("outline model returned no completion choice")
    content = (choices[0].get("message") or {}).get("content")
    if isinstance(content, str):
        return clean_markdown(content)
    if isinstance(content, list):
        text = "".join(str(item.get("text") or "") for item in content if isinstance(item, dict))
        return clean_markdown(text)
    raise RuntimeError("outline model returned an unsupported response")


class OutlineGenerator:
    def __init__(
        self,
        model: str = OUTLINE_MODEL,
        backend_url: str = BACKEND_URL,
        completion: Callable[[str, int], str] | None = None,
    ):
        self.model = model
        self.backend_url = backend_url
        self._completion = completion

    def complete(self, prompt: str, max_tokens: int) -> str:
        if self._completion:
            return clean_markdown(self._completion(prompt, max_tokens))
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Create faithful Markdown outlines from transcripts. Preserve important facts, names, "
                        "decisions, arguments, and action items. Use timestamps when they are useful. Do not invent "
                        "information and do not wrap the answer in a code fence."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
            "max_tokens": max_tokens,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        request = urllib.request.Request(
            self.backend_url + "/v1/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=1800) as response:
            return response_text(json.load(response))

    def generate(
        self,
        markdown: str,
        source_name: str,
        progress: Callable[[int, int, str], None] | None = None,
    ) -> str:
        chunks = split_transcript(markdown)
        if len(chunks) == 1:
            if progress:
                progress(0, 1, "Creating outline")
            return self.complete(self._final_prompt(source_name, chunks[0]), 4096)

        notes: list[str] = []
        total_steps = len(chunks) + 1
        for index, chunk in enumerate(chunks, start=1):
            if progress:
                progress(index - 1, total_steps, f"Summarizing transcript section {index}/{len(chunks)}")
            notes.append(
                self.complete(
                    (
                        f"Create structured notes for section {index} of {len(chunks)} from {source_name}. "
                        "Keep facts, names, timestamps, decisions, and action items needed for a final outline.\n\n"
                        f"{chunk}"
                    ),
                    1800,
                )
            )

        combined = "\n\n".join(f"### Section {index}\n{note}" for index, note in enumerate(notes, start=1))
        while len(combined) > MAX_CHUNK_CHARS:
            reduced: list[str] = []
            groups = split_transcript(combined)
            for index, group in enumerate(groups, start=1):
                reduced.append(
                    self.complete(
                        "Condense these partial transcript notes without dropping names, decisions, or action items.\n\n" + group,
                        1800,
                    )
                )
            combined = "\n\n".join(reduced)
        if progress:
            progress(total_steps - 1, total_steps, "Assembling final outline")
        return self.complete(self._final_prompt(source_name, combined), 4096)

    @staticmethod
    def _final_prompt(source_name: str, content: str) -> str:
        return (
            f"Create a useful final outline for the transcript {source_name}. Use descriptive Markdown headings and "
            "nested bullet lists. Begin with an Overview section, organize the main topics in source order, then add "
            "Key Takeaways and Action Items sections when supported by the transcript. Omit empty sections.\n\n"
            f"{content}"
        )


def render_outline(source_name: str, model: str, content: str) -> str:
    generated = datetime.now(timezone.utc).isoformat()
    return (
        f"# Outline: {source_name}\n\n"
        f"- Source transcript: `{source_name}`\n"
        f"- Outline model: `{model}`\n"
        f"- Generated: `{generated}`\n\n"
        f"{clean_markdown(content)}\n"
    )
