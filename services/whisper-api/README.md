# Whisper API

Transcription service for the GPU45 appliance. It accepts audio or video uploads,
queues transcription jobs, and writes Markdown transcripts. Completed transcripts can
also be outlined by a temporary fast LLM profile, either automatically or on demand.

The service uses `faster-whisper` with CPU `int8` by default. Outline jobs acquire a
foreground LLM lease, temporarily activate Qwythos 9B for a single-pass transcript or
Qwen3.6 35B A3B for a multi-pass transcript, write a separate Markdown file, and
restore the previous provider state.

Outline environment variables:

- `WHISPER_OUTLINE_PROFILE`
- `WHISPER_OUTLINE_MODEL`
- `WHISPER_OUTLINE_LONG_PROFILE`
- `WHISPER_OUTLINE_LONG_MODEL`
- `WHISPER_OUTLINE_BACKEND_URL`
- `WHISPER_OUTLINE_CHUNK_CHARS`

Default port: `8020`
Default data dir: `/models/whisper`
