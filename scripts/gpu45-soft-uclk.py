#!/usr/bin/env python3
"""Validate GPU45 soft-UCLK profiles and write atomic experiment markers."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import time
from pathlib import Path


ALLOWED_CLOCKS_MHZ = {1000, 1025, 1050}
STOCK_CLOCK_MHZ = 1000
SCHEMA_VERSION = 1


def validate_clock(clock_mhz: int, *, allow_stock: bool = True) -> int:
    allowed = ALLOWED_CLOCKS_MHZ if allow_stock else ALLOWED_CLOCKS_MHZ - {STOCK_CLOCK_MHZ}
    if clock_mhz not in allowed:
        raise ValueError(f"clock must be one of {sorted(allowed)}")
    return clock_mhz


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def marker_payload(clock_mhz: int, stage: str, driver: str, kernel: str | None = None) -> dict[str, object]:
    validate_clock(clock_mhz, allow_stock=False)
    if not stage.strip():
        raise ValueError("stage is required")
    if not driver.strip():
        raise ValueError("driver is required")
    return {
        "schemaVersion": SCHEMA_VERSION,
        "state": "armed",
        "stage": stage,
        "requestedClockMHz": clock_mhz,
        "kernel": kernel or platform.release(),
        "driver": driver,
        "armedAtEpoch": int(time.time()),
        "recovery": "reboot-to-vbios-stock",
    }


def atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def validate_manifest(payload: dict[str, object]) -> dict[str, object]:
    profiles = payload.get("profiles")
    if not isinstance(profiles, list) or not profiles:
        raise ValueError("manifest must contain profiles")
    seen: set[str] = set()
    for profile in profiles:
        if not isinstance(profile, dict):
            raise ValueError("profile must be an object")
        name = profile.get("name")
        clock = profile.get("clockMHz")
        if not isinstance(name, str) or not name.strip() or name in seen:
            raise ValueError("profile names must be unique non-empty strings")
        if not isinstance(clock, int):
            raise ValueError(f"profile {name} clockMHz must be an integer")
        validate_clock(clock)
        if clock != STOCK_CLOCK_MHZ and profile.get("approved") is not True:
            raise ValueError(f"experimental profile {name} is not approved")
        seen.add(name)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    marker = subparsers.add_parser("marker")
    marker.add_argument("--output", type=Path, required=True)
    marker.add_argument("--clock", type=int, required=True)
    marker.add_argument("--stage", required=True)
    marker.add_argument("--driver", required=True)
    marker.add_argument("--kernel")

    manifest = subparsers.add_parser("validate-manifest")
    manifest.add_argument("path", type=Path)

    digest = subparsers.add_parser("sha256")
    digest.add_argument("path", type=Path)

    args = parser.parse_args()
    if args.command == "marker":
        payload = marker_payload(args.clock, args.stage, args.driver, args.kernel)
        atomic_write_json(args.output, payload)
        result: object = payload
    elif args.command == "validate-manifest":
        result = validate_manifest(json.loads(args.path.read_text(encoding="utf-8")))
    else:
        result = {"path": str(args.path), "sha256": sha256_file(args.path)}
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
