# V620 Soft UCLK Evaluation

Date: 2026-07-13

## Safety Boundary

The production fallback remains Ubuntu kernel `5.15.0-185-generic`, AMDGPU `6.12.12`, the VBIOS-provided 1000 MHz UCLK table, and the existing `-80 mV` graphics voltage offset. Soft-UCLK experiments must not write `pp_table`, memory voltage, memory timings, or firmware.

The host has no active hardware watchdog. The existing SysRq failsafe handles a responsive kernel and GPU/SMU wedge. A total host lock still requires a physical power cycle.

## Recovery Bundle

The initial rollback bundle is stored at:

`/var/lib/gpu45/soft-uclk-evaluation/baseline-20260713T205115Z`

It contains checksummed copies of both kernels and initramfs files, AMDGPU modules for 5.15 and 6.8, GPU45 configuration, service definitions, package state, GRUB state, GPU state, and a complete Git bundle.

## AMD SMI Packaging

The appliance uses versioned ROCm packages such as `rocm-core7.0.0`. The unversioned `amd-smi-lib` package depends on unversioned `rocm-core`, which conflicts with files already owned by `rocm-core7.0.0`. Installing the package normally was rejected without changing the kernel or driver.

`install-amd-smi-isolated.sh` verifies the official package checksum and extracts AMD SMI under `/opt/amd-smi-gpu45-7.0.0`. The dedicated `/usr/local/bin/amd-smi-gpu45` wrapper keeps it separate from dpkg and the production ROCm tree.
