from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "gpu45-soft-uclk.py"
SPEC = importlib.util.spec_from_file_location("gpu45_soft_uclk", SCRIPT)
assert SPEC and SPEC.loader
soft_uclk = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(soft_uclk)


@pytest.mark.parametrize("clock", [1000, 1025, 1050])
def test_allowed_clocks(clock: int) -> None:
    assert soft_uclk.validate_clock(clock) == clock


def test_experiment_marker_rejects_stock() -> None:
    with pytest.raises(ValueError, match="clock must be one of"):
        soft_uclk.marker_payload(1000, "current-stack", "6.12.12")


def test_marker_records_recovery_context() -> None:
    result = soft_uclk.marker_payload(1025, "current-stack", "6.12.12", "5.15-test")
    assert result["requestedClockMHz"] == 1025
    assert result["kernel"] == "5.15-test"
    assert result["recovery"] == "reboot-to-vbios-stock"


def test_manifest_requires_approval_for_overclock() -> None:
    with pytest.raises(ValueError, match="is not approved"):
        soft_uclk.validate_manifest({"profiles": [{"name": "test", "clockMHz": 1025}]})


def test_manifest_accepts_stock_and_approved_profile() -> None:
    manifest = {
        "profiles": [
            {"name": "stock", "clockMHz": 1000, "approved": True},
            {"name": "optimized", "clockMHz": 1025, "approved": True},
        ]
    }
    assert soft_uclk.validate_manifest(manifest) == manifest
