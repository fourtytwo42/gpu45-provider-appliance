from __future__ import annotations

import torch

from wan.utils.fm_solvers_unipc import FlowUniPCMultistepScheduler


class DiffSynthUniPCScheduler:
    """Adapt Wan's reference Flow UniPC scheduler to DiffSynth's scheduler API."""

    training = False

    def __init__(self) -> None:
        self._scheduler = FlowUniPCMultistepScheduler(
            num_train_timesteps=1000,
            shift=1,
            use_dynamic_shifting=False,
        )
        self.timesteps = torch.empty(0)

    def set_timesteps(
        self,
        num_inference_steps: int,
        denoising_strength: float = 1.0,
        shift: float = 5.0,
    ) -> None:
        if denoising_strength != 1.0:
            raise ValueError("Wan UniPC currently supports full denoising only.")
        self._scheduler.set_timesteps(num_inference_steps, device="cpu", shift=shift)
        self.timesteps = self._scheduler.timesteps

    def step(
        self,
        model_output: torch.Tensor,
        timestep: torch.Tensor,
        sample: torch.Tensor,
        **_: object,
    ) -> torch.Tensor:
        return self._scheduler.step(
            model_output,
            timestep,
            sample,
            return_dict=False,
        )[0]

    def add_noise(
        self,
        original_samples: torch.Tensor,
        noise: torch.Tensor,
        timestep: torch.Tensor,
    ) -> torch.Tensor:
        return self._scheduler.add_noise(original_samples, noise, timestep)
