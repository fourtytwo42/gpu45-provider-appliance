from __future__ import annotations

from unittest.mock import MagicMock

import torch

from wan_api.scheduler import DiffSynthUniPCScheduler


def test_scheduler_sets_reference_shift_and_returns_previous_sample() -> None:
    scheduler = DiffSynthUniPCScheduler()
    inner = MagicMock()
    inner.timesteps = torch.tensor([999, 500], dtype=torch.int64)
    inner.step.return_value = (torch.tensor([3.0]),)
    scheduler._scheduler = inner

    scheduler.set_timesteps(2, shift=5.0)
    result = scheduler.step(torch.tensor([1.0]), torch.tensor(999), torch.tensor([2.0]))

    inner.set_timesteps.assert_called_once_with(2, device="cpu", shift=5.0)
    assert scheduler.timesteps.tolist() == [999, 500]
    assert result.tolist() == [3.0]


def test_scheduler_rejects_partial_denoising() -> None:
    scheduler = DiffSynthUniPCScheduler()

    try:
        scheduler.set_timesteps(2, denoising_strength=0.5)
    except ValueError as exc:
        assert "full denoising" in str(exc)
    else:
        raise AssertionError("Expected partial denoising to be rejected")
