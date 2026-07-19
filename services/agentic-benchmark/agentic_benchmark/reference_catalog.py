from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .domain import configuration_hash


def load_reference_profiles(directory: Path) -> list[dict[str, Any]]:
    profiles: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in sorted(directory.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        name = str(payload.get("name") or "").strip()
        endpoint = str(payload.get("endpointUrl") or "").rstrip("/")
        if not name or name in seen:
            raise ValueError(f"Invalid or duplicate reference profile in {path}")
        if payload.get("executionMode") != "external-openai" or not endpoint.startswith("http://127.0.0.1:"):
            raise ValueError(f"Reference profile {name} must use a loopback external-openai endpoint")
        seen.add(name)
        payload["endpointUrl"] = endpoint
        payload["profileHash"] = configuration_hash(payload)
        profiles.append(payload)
    return profiles
