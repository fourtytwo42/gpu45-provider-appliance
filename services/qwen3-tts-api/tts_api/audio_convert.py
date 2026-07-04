"""
Convert WAV to MP3 for API responses. Uses the same approach as the rest of the project:
ffmpeg from system PATH or from imageio-ffmpeg (pip install imageio-ffmpeg).
"""
import subprocess
from pathlib import Path
from typing import Union


def _get_ffmpeg() -> str:
    """Resolve ffmpeg: system PATH first, then imageio-ffmpeg bundle."""
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        return "ffmpeg"
    except (subprocess.CalledProcessError, FileNotFoundError):
        try:
            import imageio_ffmpeg
            return imageio_ffmpeg.get_ffmpeg_exe()
        except (ImportError, RuntimeError):
            raise RuntimeError(
                "ffmpeg not found. Install it (e.g. winget install ffmpeg) or: pip install imageio-ffmpeg"
            )


def wav_to_mp3_bytes(wav_input: Union[str, Path, bytes]) -> bytes:
    """
    Convert WAV (file path or raw bytes) to MP3 bytes.
    Uses ffmpeg (same as witness_audiobook_organize.py and generate_audiobook_credits.py).
    Raises if ffmpeg is not available or conversion fails.
    """
    ffmpeg_exe = _get_ffmpeg()

    if isinstance(wav_input, (str, Path)):
        result = subprocess.run(
            [
                ffmpeg_exe, "-y", "-i", str(wav_input),
                "-f", "mp3",
                "pipe:1",
            ],
            capture_output=True,
            check=True,
        )
        return result.stdout
    else:
        result = subprocess.run(
            [
                ffmpeg_exe, "-y",
                "-f", "wav", "-i", "pipe:0",
                "-f", "mp3",
                "pipe:1",
            ],
            input=wav_input,
            capture_output=True,
            check=True,
        )
        return result.stdout
