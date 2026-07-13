# V620 PowerPlay Memory Evaluation

Date: 2026-07-13

## Result

The V620 must remain at its stock 1000 MHz memory controller clock. The current Ubuntu 22.04 kernel, amdgpu 6.12.12 stack, and V620 SMU firmware reject live PowerPlay table reinitialization. Both a same-as-stock upload and the validated 1025 MHz candidate timed out during SMU reset. The 1050 MHz candidate was not attempted because the 1025 MHz stability gate failed.

No experimental table is referenced by `/etc/gpu45/gpu-tuning.json` or any boot service. The production `-80 mV` graphics-voltage offset, fan curve, Q4 profile, and Q5 profile were not changed.

## Tables

| Profile | UCLK | SHA-256 | Result |
| --- | ---: | --- | --- |
| VBIOS stock | 1000 MHz | `a6fc019fdada096422629293bee778e8857af3330fd2dc2de42dd9d9d921b1c8` | Production |
| Candidate | 1025 MHz | `b8c7c279b2a39a29a159b5ecc8cb542d6fa0979ad06c365515bc49a89cc76687` | Rejected, SMU reset timeout |
| Candidate | 1050 MHz | `a38b74a1d63191233903937e4c1e276491868adef727ff355a82ddfdf84217cf` | Not attempted after 1025 failure |

The candidates changed only zero-based offsets `62-63` and `1412-1413`, corresponding to the two validated maximum UCLK fields.

## Stock Performance

| Model | 3376-token first prefill | 256-token decode | 1024-token decode median | 2048-token decode | Peak power | Peak junction | Peak memory temp |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Qwen3.6 27B Q4 | 370.68 tok/s | 35.84 tok/s | 33.13 tok/s | 34.55 tok/s | 239 W | 84 C | 78 C |
| Qwen3.6 27B Q5 | 363.67 tok/s | 33.48 tok/s | 31.84 tok/s | 32.13 tok/s | 237 W | 82 C | 74 C |

Repeated prompts after the first pass reused prompt state and are not reported as uncached prefill measurements.

## Failure Evidence

The stock-table rehearsal and 1025 MHz attempt both produced:

```text
SMU: I'm not done with your previous command
Failed to enable requested dpm features!
Failed to setup smc hw!
smu reset failed, ret = -62
```

The failure also made `pp_table`, `pp_dpm_mclk`, and GPU busy telemetry unavailable until reboot. This is a driver/firmware reinitialization failure, not evidence that 1025 MHz itself is unstable.

## Recovery

The evaluation installed a root-owned transient SysRq failsafe. On an upload failure it records the failure, syncs filesystems, remounts them read-only, and hard-reboots without relying on the normal amdgpu shutdown path. The boot recovery unit verifies that VBIOS restored the exact stock table before clearing the experiment marker.

Recovery was exercised twice. Both boots returned the exact stock checksum and 1000 MHz DPM state. A total kernel or CPU hard lock remains outside software recovery and requires a physical power cycle or managed external power control.

## Recommendation

Do not persist or retry live `pp_table` uploads on this host with the current kernel, amdgpu driver, and SMU firmware combination. Pursue Qwen speed through llama.cpp, MTP/DFlash, batching, and cache improvements instead of V620 memory overclocking.
