from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


MODEL_ROOT = Path(os.environ.get("GPU45_MUSIC_MODEL_ROOT", "/models/music"))
ACE_CHECKPOINTS = Path(os.environ.get("GPU45_ACE_CHECKPOINTS", str(MODEL_ROOT / "ace-step" / "checkpoints")))
LEVO_ROOT = Path(os.environ.get("GPU45_LEVO_MODEL_ROOT", str(MODEL_ROOT / "levo2")))
LEVO_LICENSE_TEXT = (
    "LeVo 2 is restricted to academic, research, and educational use. "
    "Outputs from this profile are labeled noncommercial."
)
LEVO_LICENSE_HASH = hashlib.sha256(LEVO_LICENSE_TEXT.encode("utf-8")).hexdigest()


PROFILES: tuple[dict[str, object], ...] = (
    {
        "id": "ace-xl-turbo-4b",
        "name": "ACE-Step 1.5 XL Turbo + 4B LM",
        "backend": "ace",
        "model": "acestep-v15-xl-turbo",
        "lmModel": "acestep-5Hz-lm-4B",
        "description": "Fast full-quality song generation on the 32 GB V620.",
        "recommended": True,
        "experimental": False,
        "noncommercial": False,
        "modes": ["create", "reference", "edit"],
        "taskTypes": ["text2music", "cover", "repaint"],
        "duration": {"min": 10, "max": 600, "default": 60},
        "stepOptions": [8],
        "defaultSteps": 8,
        "outputFormats": ["flac", "wav", "mp3"],
        "expectedVramGb": 24,
    },
    {
        "id": "ace-xl-sft-4b",
        "name": "ACE-Step 1.5 XL SFT + 4B LM",
        "backend": "ace",
        "model": "acestep-v15-xl-sft",
        "lmModel": "acestep-5Hz-lm-4B",
        "description": "Highest-quality ACE song generation and reference editing.",
        "recommended": False,
        "experimental": False,
        "noncommercial": False,
        "modes": ["create", "reference", "edit"],
        "taskTypes": ["text2music", "cover", "repaint"],
        "duration": {"min": 10, "max": 600, "default": 60},
        "stepOptions": [32, 50],
        "defaultSteps": 50,
        "outputFormats": ["flac", "wav", "mp3"],
        "expectedVramGb": 24,
    },
    {
        "id": "ace-xl-base-4b",
        "name": "ACE-Step 1.5 XL Base + 4B LM",
        "backend": "ace",
        "model": "acestep-v15-xl-base",
        "lmModel": "acestep-5Hz-lm-4B",
        "description": "ACE editing profile for cover, repaint, complete, layers, and stems.",
        "recommended": False,
        "experimental": False,
        "noncommercial": False,
        "modes": ["create", "reference", "edit", "stems"],
        "taskTypes": ["text2music", "cover", "repaint", "complete", "lego", "extract"],
        "duration": {"min": 10, "max": 600, "default": 60},
        "stepOptions": [32, 50],
        "defaultSteps": 50,
        "outputFormats": ["flac", "wav", "mp3"],
        "expectedVramGb": 24,
    },
    {
        "id": "levo2-large-amd",
        "name": "LeVo 2 Large AMD",
        "backend": "levo",
        "model": "SongGeneration-v2-large",
        "lmModel": None,
        "description": "Experimental four-phase AMD profile with Q8 mu-law KV cache.",
        "recommended": False,
        "experimental": True,
        "noncommercial": True,
        "licenseHash": LEVO_LICENSE_HASH,
        "modes": ["create", "reference", "stems"],
        "taskTypes": ["text2music", "reference", "separate"],
        "duration": {"min": 10, "max": 280, "default": 60},
        "stepOptions": [],
        "defaultSteps": None,
        "outputFormats": ["wav"],
        "expectedVramGb": 28,
    },
)


def _contains_weights(path: Path) -> bool:
    try:
        if not path.is_dir():
            return False
        patterns = ("*.safetensors", "*.bin", "*.pt", "*.pth")
        return any(next(path.rglob(pattern), None) is not None for pattern in patterns)
    except OSError:
        return False


def _validation() -> dict[str, object]:
    path = LEVO_ROOT / "validation.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def snapshots(license_accepted: bool) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    common_ready = _contains_weights(ACE_CHECKPOINTS / "vae") and _contains_weights(ACE_CHECKPOINTS / "acestep-5Hz-lm-4B")
    levo_validation = _validation()
    for source in PROFILES:
        profile = dict(source)
        if profile["backend"] == "ace":
            model_ready = _contains_weights(ACE_CHECKPOINTS / str(profile["model"]))
            ready = common_ready and model_ready
            reason = None if ready else "ACE model assets are not installed yet."
        else:
            ready = _contains_weights(LEVO_ROOT / "SongGeneration-v2-large") and levo_validation.get("status") == "passed"
            reason = None if ready else str(levo_validation.get("reason") or "LeVo has not passed AMD hardware validation.")
        profile.update(
            ready=ready,
            availabilityReason=reason,
            licenseAccepted=license_accepted if profile.get("noncommercial") else True,
        )
        result.append(profile)
    return result


def get_profile(profile_id: str) -> dict[str, object] | None:
    return next((dict(profile) for profile in PROFILES if profile["id"] == profile_id), None)

