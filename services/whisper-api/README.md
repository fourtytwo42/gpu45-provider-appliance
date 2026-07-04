# Whisper API

CPU transcription service for the GPU45 appliance. It accepts audio or video uploads,
queues transcription jobs, and writes Markdown transcripts.

The service uses `faster-whisper` with CPU `int8` by default so it does not compete
with the LLM or video GPU workloads.

Default port: `8020`
Default data dir: `/models/whisper`
