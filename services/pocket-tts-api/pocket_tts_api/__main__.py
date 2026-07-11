import os

import uvicorn


if __name__ == "__main__":
    uvicorn.run(
        "pocket_tts_api.main:app",
        host=os.environ.get("POCKET_TTS_HOST", "127.0.0.1"),
        port=int(os.environ.get("POCKET_TTS_PORT", "8002")),
    )
