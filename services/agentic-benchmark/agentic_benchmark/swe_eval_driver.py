from __future__ import annotations

import argparse
import json
from pathlib import Path

from docker.models.containers import ContainerCollection
from swebench.harness.run_evaluation import main as run_evaluation


def secure_containers() -> None:
    original = ContainerCollection.create

    def create(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs.setdefault("network_disabled", True)
        kwargs.setdefault("mem_limit", "8g")
        kwargs.setdefault("pids_limit", 512)
        kwargs.setdefault("cap_drop", ["ALL"])
        kwargs.setdefault("security_opt", ["no-new-privileges"])
        return original(self, *args, **kwargs)

    ContainerCollection.create = create  # type: ignore[method-assign]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--predictions", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--report-dir", required=True)
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args()
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    secure_containers()
    report = run_evaluation(
        dataset_name="princeton-nlp/SWE-bench_Verified",
        split="test",
        instance_ids=[args.instance_id],
        predictions_path=args.predictions,
        max_workers=1,
        force_rebuild=False,
        cache_level="env",
        clean=False,
        open_file_limit=4096,
        run_id=args.run_id,
        timeout=args.timeout,
        namespace="swebench",
        rewrite_reports=False,
        modal=False,
        report_dir=str(report_dir),
    ) or {}
    resolved = set(report.get("resolved_ids") or report.get("resolved") or [])
    print("GPU45_RESULT=" + json.dumps({"instanceId": args.instance_id, "resolved": args.instance_id in resolved, "report": report}, default=str))


if __name__ == "__main__":
    main()
