"""
API configuration: data directory, device, host/port.
"""
import os

# Base directory for all API data (voices, models, JSON stores).
# Default: api_data in repo root (cwd when running the server).
API_DATA_DIR = os.environ.get("QWEN_TTS_API_DATA", os.path.join(os.getcwd(), "api_data"))

# Device for inference and training. Default CUDA.
DEVICE = os.environ.get("QWEN_TTS_DEVICE", "cuda:0")

# Default synthesis when no voice_id or model_id: "default" means use VoiceDesign with empty instruct.
# Can be overridden to a model_id later if desired.
DEFAULT_SYNTHESIS_MODE = "voice_design_default"

# HuggingFace model IDs
VOICE_DESIGN_MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign"
BASE_MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
TOKENIZER_MODEL = "Qwen/Qwen3-TTS-Tokenizer-12Hz"

# Local Whisper service used to recover transcript text for uploaded voice clones.
WHISPER_API_URL = os.environ.get("QWEN_TTS_WHISPER_API_URL", "http://127.0.0.1:8020")
IMPORT_MAX_SECONDS = int(os.environ.get("QWEN_TTS_IMPORT_MAX_SECONDS", "45"))

# Built-in speakers from the CustomVoice model (for reference; synthesis with these is not in the API yet).
BUILTIN_SPEAKERS = [
    {"name": "Ryan", "description": "Dynamic male voice with strong rhythmic drive", "native_language": "English"},
    {"name": "Aiden", "description": "Sunny American male voice with a clear midrange", "native_language": "English"},
    {"name": "Vivian", "description": "Bright, slightly edgy young female voice", "native_language": "Chinese"},
    {"name": "Serena", "description": "Warm, gentle young female voice", "native_language": "Chinese"},
    {"name": "Uncle_Fu", "description": "Seasoned male voice with a low, mellow timbre", "native_language": "Chinese"},
    {"name": "Dylan", "description": "Youthful Beijing male voice with a clear, natural timbre", "native_language": "Chinese (Beijing Dialect)"},
    {"name": "Eric", "description": "Lively Chengdu male voice with a slightly husky brightness", "native_language": "Chinese (Sichuan Dialect)"},
    {"name": "Ono_Anna", "description": "Playful Japanese female voice with a light, nimble timbre", "native_language": "Japanese"},
    {"name": "Sohee", "description": "Warm Korean female voice with rich emotion", "native_language": "Korean"},
]
