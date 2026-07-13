from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "gpu45-powerplay.py"
SPEC = importlib.util.spec_from_file_location("gpu45_powerplay", SCRIPT)
assert SPEC and SPEC.loader
powerplay = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(powerplay)


def stock_fixture() -> bytes:
    data = bytearray(powerplay.EXPECTED_SIZE)
    for offset in powerplay.UCLK_OFFSETS:
        data[offset : offset + 2] = powerplay.STOCK_CLOCK_MHZ.to_bytes(2, "little")
    return bytes(data)


@pytest.mark.parametrize("clock", [1000, 1025, 1050])
def test_build_and_validate_candidate(clock: int) -> None:
    stock = stock_fixture()
    candidate = powerplay.build_candidate(stock, clock, require_stock_hash=False)
    result = powerplay.validate_candidate(
        stock,
        candidate,
        clock,
        require_stock_hash=False,
    )
    assert result["uclkMHz"] == [clock, clock]
    assert set(result["changedOffsetsZeroBased"]).issubset({62, 63, 1412, 1413})


def test_rejects_changes_outside_approved_fields() -> None:
    stock = stock_fixture()
    candidate = bytearray(powerplay.build_candidate(stock, 1025, require_stock_hash=False))
    candidate[900] = 1
    with pytest.raises(ValueError, match="outside the approved UCLK edits"):
        powerplay.validate_candidate(
            stock,
            bytes(candidate),
            1025,
            require_stock_hash=False,
        )


def test_rejects_unapproved_clock() -> None:
    with pytest.raises(ValueError, match="clock must be one of"):
        powerplay.build_candidate(stock_fixture(), 1075, require_stock_hash=False)
