# GPU45 Agentic Benchmark Coordinator

This loopback-only service owns persistent agentic benchmark campaigns on the appliance. It discovers served LLM profiles from the appliance catalog, snapshots their launch configuration, stores durable campaign state in SQLite, and exposes a narrow API to the management console.

Core GPU45 services remain bare metal. Docker is used only by pinned SWE-bench and Terminal-Bench adapters for disposable task sandboxes.

Runtime paths:

- Database: `/var/lib/gpu45/benchmarks/agentic.db`
- Artifacts: `/var/lib/gpu45/benchmarks/artifacts`
- Harnesses: `/opt/gpu45/benchmark-harnesses`
- Container and dataset cache: `/models/benchmark-cache`
- API: `http://127.0.0.1:8055`

## Codex reference baseline

The optional `gpu45-codex-reference-proxy.service` runs the same fixed 11-task finalist panel through a pinned Codex CLI using `gpt-5.6-sol` with medium reasoning effort. It is an agent-system reference, not a raw-model leaderboard entry. The coordinator records verifier outcomes, wall time, and Codex-reported tokens, but leaves energy unavailable because the evaluated hardware is not GPU45.

Install and authenticate it once:

```bash
sudo gpu45-install-codex-reference
sudo -u gpu45-benchmark env CODEX_HOME=/var/lib/gpu45-benchmark/.codex codex login --device-auth
sudo systemctl restart gpu45-codex-reference-proxy.service
```

Reference campaigns use the same BFCL, tau, SWE-bench, and Terminal-Bench adapters and task IDs as the local finalist efficiency panel. Their results appear beside local models without changing local-model promotion or GPU efficiency ranking.
