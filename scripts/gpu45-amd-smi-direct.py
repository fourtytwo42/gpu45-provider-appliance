#!/usr/bin/env python3
"""Call the typed AMD SMI API without the 26.0 CLI clock-limit parser."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PREFIX = Path("/opt/amd-smi-gpu45-7.0.0")
sys.path.insert(0, str(PREFIX / "share" / "amd_smi"))

from amdsmi import (  # noqa: E402
    AmdSmiDevPerfLevel,
    amdsmi_get_processor_handles,
    amdsmi_init,
    amdsmi_set_gpu_clk_limit,
    amdsmi_set_gpu_perf_level,
    amdsmi_shut_down,
)


PERF_LEVELS = {
    "AUTO": AmdSmiDevPerfLevel.AUTO,
    "MANUAL": AmdSmiDevPerfLevel.MANUAL,
}


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    performance = subparsers.add_parser("set-performance")
    performance.add_argument("level", choices=sorted(PERF_LEVELS))
    limit = subparsers.add_parser("set-mclk-max")
    limit.add_argument("clock_mhz", type=int, choices=[1025, 1050])
    args = parser.parse_args()

    amdsmi_init()
    try:
        handles = amdsmi_get_processor_handles()
        if len(handles) != 1:
            raise RuntimeError(f"expected one AMD GPU, found {len(handles)}")
        handle = handles[0]
        if args.command == "set-performance":
            amdsmi_set_gpu_perf_level(handle, PERF_LEVELS[args.level])
            result = {"ok": True, "performanceLevel": args.level}
        else:
            amdsmi_set_gpu_clk_limit(handle, "mclk", "max", args.clock_mhz)
            result = {"ok": True, "mclkMaxMHz": args.clock_mhz}
        print(json.dumps(result, sort_keys=True))
    finally:
        amdsmi_shut_down()


if __name__ == "__main__":
    main()
