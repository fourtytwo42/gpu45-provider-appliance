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


def kernel_marker_payload(target_kernel: str, fallback_kernel: str, stage: str) -> dict[str, object]:
    if not target_kernel.strip() or not fallback_kernel.strip() or target_kernel == fallback_kernel:
        raise ValueError("target and fallback kernels must be distinct non-empty values")
    if not stage.strip():
        raise ValueError("stage is required")
    return {
        "schemaVersion": SCHEMA_VERSION,
        "state": "scheduled",
        "stage": stage,
        "targetKernel": target_kernel,
        "fallbackKernel": fallback_kernel,
        "scheduledAtEpoch": int(time.time()),
        "retryAllowed": False,
    }


def observe_kernel_marker(payload: dict[str, object], observed_kernel: str) -> dict[str, object]:
    target = payload.get("targetKernel")
    fallback = payload.get("fallbackKernel")
    if observed_kernel == target:
        state = "booted-target"
    elif observed_kernel == fallback:
        state = "returned-to-fallback"
    else:
        state = "booted-unexpected-kernel"
    return {
        **payload,
        "state": state,
        "observedKernel": observed_kernel,
        "observedAtEpoch": int(time.time()),
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

    kernel_marker = subparsers.add_parser("kernel-marker")
    kernel_marker.add_argument("--output", type=Path, required=True)
    kernel_marker.add_argument("--target", required=True)
    kernel_marker.add_argument("--fallback", required=True)
    kernel_marker.add_argument("--stage", required=True)

    kernel_observe = subparsers.add_parser("kernel-observe")
    kernel_observe.add_argument("--marker", type=Path, required=True)
    kernel_observe.add_argument("--output", type=Path, required=True)
    kernel_observe.add_argument("--kernel", required=True)

    manifest = subparsers.add_parser("validate-manifest")
    manifest.add_argument("path", type=Path)

    digest = subparsers.add_parser("sha256")
    digest.add_argument("path", type=Path)

    args = parser.parse_args()
    if args.command == "marker":
        payload = marker_payload(args.clock, args.stage, args.driver, args.kernel)
        atomic_write_json(args.output, payload)
        result: object = payload
    elif args.command == "kernel-marker":
        payload = kernel_marker_payload(args.target, args.fallback, args.stage)
        atomic_write_json(args.output, payload)
        result = payload
    elif args.command == "kernel-observe":
        payload = json.loads(args.marker.read_text(encoding="utf-8"))
        result = observe_kernel_marker(payload, args.kernel)
        atomic_write_json(args.output, result)
    elif args.command == "validate-manifest":
        result = validate_manifest(json.loads(args.path.read_text(encoding="utf-8")))
    else:
        result = {"path": str(args.path), "sha256": sha256_file(args.path)}
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
