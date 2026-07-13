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

## Soft-Limit Test Contract

`gpu45-soft-uclk-apply.sh` refuses to run with an active or queued GPU lease. It records active services, stops GPU workers, waits for VRAM to fall below 2 GB, creates an atomic experiment marker, and arms the SysRq failsafe before invoking AMD SMI. A rejected request restores automatic performance mode and the prior service state without writing `pp_table`.

AMD SMI 26.0 has a CLI validation bug that compares the integer limit against string bounds. `gpu45-amd-smi-direct.py` bypasses only that parser and invokes the package's typed `amdsmi_set_gpu_clk_limit` API directly.

### Kernel 5.15 Result

The typed AMD SMI request entered manual performance mode successfully, but `amdsmi_set_gpu_clk_limit(..., "mclk", "max", 1025)` returned `AMDSMI_STATUS_NOT_SUPPORTED`. The guard restored automatic mode, the 1000 MHz VBIOS table, the prior services, and a disarmed recovery timer. The 1050 MHz candidate was not attempted because the 1025 MHz gate failed.

## One-Time Kernel Tests

`gpu45-kernel-attempt` schedules kernel 6.8 through `grub-reboot` while preserving kernel 5.15 as `GRUB_DEFAULT`. Its boot observer records the actual kernel. Returning to 5.15 with a pending marker is treated as a failed attempt and disables automatic retry.

### Kernel 6.8 With AMDGPU 6.12.12 Result

The one-time `6.8.0-124-generic` boot reached the kernel but never reached usable userspace. AMDGPU entered a continuous V620 virtual-GPU mailbox loop beginning during device initialization:

```text
amdgpu 0000:2d:00.0: amdgpu: trn=2 ACK should not assert! wait again !
xgpu_nv_mailbox_trans_msg: callbacks suppressed
```

After a physical power cycle, GRUB returned to the saved `5.15.0-185-generic` fallback. The boot observer recorded `returned-to-fallback`, cleared the pending marker, and disabled automatic retry. The stock 1000 MHz memory states, automatic performance mode, fan service, resource manager, management console, and Responses model catalog all recovered.

## Isolated Newer Driver

ROCm 7.2.4's official Jammy installer points to AMDGPU release `30.30.4`, which packages kernel module version `6.16.13`. The `gpu45-amdgpu-experimental.sh` recipe extracts the checksummed DKMS source under the distinct package name `amdgpu-gpu45`, builds it only for kernel 6.8, and leaves ROCm 7.0 userspace unchanged.

The recipe does not install the newer shared firmware package. Before installing its modules, it backs up the complete 6.8 DKMS module directory and initramfs. It verifies that the production 5.15 AMDGPU module and initramfs checksums are unchanged and restores the original 6.8 image on any installation failure.

### AMDGPU 6.16.13 Installation Checkpoint

The signed AMDGPU `6.16.13` modules built and installed successfully for `6.8.0-124-generic`. The experimental package provides all eight expected modules, including `amddrm_exec`, and the 6.8 initramfs was regenerated. The production 5.15 initramfs and AMDGPU module retained their recorded SHA-256 checksums:

- `initrd.img-5.15.0-185-generic`: `e6fa1ab84b522c1cf7eee6e66313cf3d05c2744cf98d5dc521e35249577295c5`
- `amdgpu.ko` for 5.15: `8ab8995a95e1c98cd223cd48f588ab0024e46c71df1e1faf827f584c021eff9c`

The 6.8 initramfs reports missing firmware for unrelated AMD architectures. It also reports `sienna_cichlid_cap.bin`, but the working production 6.12.12 module requests the same absent optional capability file. All other Navi21 and Sienna Cichlid firmware requested by the experimental module is present.
