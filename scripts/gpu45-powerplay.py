#!/usr/bin/env python3
"""Build and validate tightly scoped V620 memory-clock PowerPlay tables."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path


EXPECTED_SIZE = 2470
STOCK_SHA256 = "a6fc019fdada096422629293bee778e8857af3330fd2dc2de42dd9d9d921b1c8"
STOCK_CLOCK_MHZ = 1000
ALLOWED_CLOCKS_MHZ = {1000, 1025, 1050}
UCLK_OFFSETS = (62, 1412)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_clock(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def inspect_table(data: bytes) -> dict[str, object]:
    if len(data) != EXPECTED_SIZE:
        raise ValueError(f"expected {EXPECTED_SIZE} bytes, got {len(data)}")
    return {
        "size": len(data),
        "sha256": sha256(data),
        "uclkMHz": [read_clock(data, offset) for offset in UCLK_OFFSETS],
    }


def build_candidate(stock: bytes, clock_mhz: int, *, require_stock_hash: bool = True) -> bytes:
    details = inspect_table(stock)
    if require_stock_hash and details["sha256"] != STOCK_SHA256:
        raise ValueError(f"stock table checksum mismatch: {details['sha256']}")
    if details["uclkMHz"] != [STOCK_CLOCK_MHZ, STOCK_CLOCK_MHZ]:
        raise ValueError(f"stock UCLK fields are not both {STOCK_CLOCK_MHZ}: {details['uclkMHz']}")
    if clock_mhz not in ALLOWED_CLOCKS_MHZ:
        raise ValueError(f"clock must be one of {sorted(ALLOWED_CLOCKS_MHZ)}")

    candidate = bytearray(stock)
    for offset in UCLK_OFFSETS:
        struct.pack_into("<H", candidate, offset, clock_mhz)
    return bytes(candidate)


def validate_candidate(
    stock: bytes,
    candidate: bytes,
    expected_clock_mhz: int,
    *,
    require_stock_hash: bool = True,
) -> dict[str, object]:
    expected = build_candidate(stock, expected_clock_mhz, require_stock_hash=require_stock_hash)
    if candidate != expected:
        unexpected = [index for index, pair in enumerate(zip(candidate, expected)) if pair[0] != pair[1]]
        if len(candidate) != len(expected):
            unexpected.append(min(len(candidate), len(expected)))
        raise ValueError(f"candidate differs outside the approved UCLK edits at offsets {unexpected[:16]}")

    changed = [index for index, pair in enumerate(zip(stock, candidate)) if pair[0] != pair[1]]
    details = inspect_table(candidate)
    details["changedOffsetsZeroBased"] = changed
    details["expectedClockMHz"] = expected_clock_mhz
    return details


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("table", type=Path)

    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("--source", type=Path, required=True)
    build_parser.add_argument("--clock", type=int, required=True)
    build_parser.add_argument("--output", type=Path, required=True)

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--stock", type=Path, required=True)
    validate_parser.add_argument("--candidate", type=Path, required=True)
    validate_parser.add_argument("--clock", type=int, required=True)

    args = parser.parse_args()
    if args.command == "inspect":
        result = inspect_table(args.table.read_bytes())
    elif args.command == "build":
        stock = args.source.read_bytes()
        candidate = build_candidate(stock, args.clock)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(candidate)
        result = validate_candidate(stock, candidate, args.clock)
        result["output"] = str(args.output)
    else:
        result = validate_candidate(args.stock.read_bytes(), args.candidate.read_bytes(), args.clock)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
