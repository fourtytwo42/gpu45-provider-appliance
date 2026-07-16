# GPU45 Agentic Benchmark Coordinator

This loopback-only service owns persistent agentic benchmark campaigns on the appliance. It discovers served LLM profiles from the appliance catalog, snapshots their launch configuration, stores durable campaign state in SQLite, and exposes a narrow API to the management console.

Core GPU45 services remain bare metal. Docker is used only by pinned SWE-bench and Terminal-Bench adapters for disposable task sandboxes.

Runtime paths:

- Database: `/var/lib/gpu45/benchmarks/agentic.db`
- Artifacts: `/var/lib/gpu45/benchmarks/artifacts`
- Harnesses: `/opt/gpu45/benchmark-harnesses`
- Container and dataset cache: `/models/benchmark-cache`
- API: `http://127.0.0.1:8055`
