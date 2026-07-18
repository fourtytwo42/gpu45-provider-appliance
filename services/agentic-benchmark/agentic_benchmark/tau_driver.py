from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


TAU_AGENT_MAX_TOKENS = 2048
TAU_USER_MAX_TOKENS = 256


def build_llm_args(
    timeout: int,
    headers: dict[str, str],
) -> tuple[dict[str, object], dict[str, object]]:
    target_args: dict[str, object] = {
        "temperature": 0.0,
        "api_base": "http://127.0.0.1:30001/v1",
        "api_key": "gpu45-benchmark",
        "timeout": timeout,
        "num_retries": 0,
        "max_tokens": TAU_AGENT_MAX_TOKENS,
        "extra_headers": headers,
    }
    user_args: dict[str, object] = {
        "temperature": 0.0,
        "api_base": "http://127.0.0.1:30002/v1",
        "api_key": "gpu45",
        "timeout": timeout,
        "num_retries": 0,
        "max_tokens": TAU_USER_MAX_TOKENS,
        "extra_body": {
            "chat_template_kwargs": {"enable_thinking": False},
            "reasoning_budget": 0,
        },
    }
    return target_args, user_args


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--domain")
    parser.add_argument("--task-id")
    parser.add_argument("--target-alias")
    parser.add_argument("--output")
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args()

    from tau2.data_model.simulation import TextRunConfig
    from tau2.run import get_tasks, run_single_task

    if args.list:
        tasks = []
        for domain in ("airline", "retail", "telecom"):
            tasks.extend(f"{domain}:{task.id}" for task in get_tasks(domain))
        print("GPU45_TASKS=" + json.dumps(tasks, separators=(",", ":")))
        return
    if not all((args.domain, args.task_id, args.target_alias, args.output)):
        raise SystemExit("domain, task-id, target-alias, and output are required")

    target_args, user_args = build_llm_args(
        args.timeout,
        json.loads(os.environ.get("GPU45_BENCHMARK_HEADERS", "{}")),
    )
    config = TextRunConfig(
        domain=args.domain,
        agent="llm_agent",
        user="user_simulator",
        llm_agent=f"openai/{args.target_alias}",
        llm_args_agent=target_args,
        llm_user="openai/gpu45-tau-user",
        llm_args_user=user_args,
        max_steps=200,
        max_errors=10,
        max_concurrency=1,
        seed=42,
        timeout=args.timeout,
        max_retries=0,
        log_level="ERROR",
        enforce_communication_protocol=True,
    )
    selected = get_tasks(args.domain, task_ids=[args.task_id])
    if len(selected) != 1:
        raise RuntimeError(f"Expected one tau task, found {len(selected)}")
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    result = run_single_task(config, selected[0], seed=42, save_dir=output.parent, verbose_logs=True)
    payload = result.model_dump(mode="json")
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    reward = float(result.reward_info.reward)
    print("GPU45_RESULT=" + json.dumps({"reward": reward, "terminationReason": str(result.termination_reason), "duration": result.duration}, separators=(",", ":")))


if __name__ == "__main__":
    main()
