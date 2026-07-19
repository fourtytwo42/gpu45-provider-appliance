from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from pathlib import Path


def model_handler(transport: str):
    if transport == "chat-completions":
        from bfcl_eval.model_handler.api_inference.openai_completion import OpenAICompletionsHandler

        return OpenAICompletionsHandler
    if transport != "responses":
        raise ValueError(f"Unsupported BFCL transport: {transport}")
    from bfcl_eval.constants.model_config import MODEL_CONFIG_MAPPING, ModelConfig
    from bfcl_eval.model_handler.api_inference.openai_response import OpenAIResponsesHandler

    return OpenAIResponsesHandler


def register_model(registry_name: str, alias: str, transport: str = "responses") -> None:
    from bfcl_eval.constants.model_config import MODEL_CONFIG_MAPPING, ModelConfig

    handler = model_handler(transport)

    class GPU45Handler(handler):
        def generate_with_backoff(self, **kwargs):
            if transport == "chat-completions":
                return super().generate_with_backoff(**kwargs)
            started = time.monotonic()
            kwargs["stream"] = True
            stream = self.client.responses.create(**kwargs)
            for event in stream:
                if getattr(event, "type", None) == "response.completed":
                    return event.response, time.monotonic() - started
            raise RuntimeError("GPU45 stream ended without response.completed")

    MODEL_CONFIG_MAPPING[registry_name] = ModelConfig(
        model_name=alias,
        display_name=f"GPU45 {alias}",
        url="http://127.0.0.1:30001",
        org="GPU45",
        license="local-profile",
        model_handler=GPU45Handler,
        input_price=None,
        output_price=None,
        is_fc_model=True,
        # OpenAI-compatible tool schemas cannot carry BFCL's dotted function
        # names, so BFCL compiles them with underscores. Restore the dots in
        # the verifier before comparing the model call with the gold answer.
        underscore_to_dot=True,
    )


def read_score(score_root: Path, category: str) -> dict[str, object]:
    candidates = list(score_root.rglob(f"*{category}*.json"))
    for path in sorted(candidates):
        try:
            first = path.read_text(encoding="utf-8").splitlines()[0]
            payload = json.loads(first)
        except (OSError, IndexError, json.JSONDecodeError):
            continue
        if "accuracy" in payload:
            return {
                "accuracy": float(payload["accuracy"]),
                "correct": int(payload.get("correct_count", 0)),
                "total": int(payload.get("total_count", payload.get("total", 0))),
                "scoreFile": str(path),
            }
    raise RuntimeError(f"BFCL did not produce a score for {category}")


def select_entries(entries: list[dict[str, object]], case_id: str | None, limit: int) -> list[dict[str, object]]:
    selected = entries
    if case_id:
        selected = [entry for entry in selected if entry.get("id") == case_id]
        if not selected:
            raise ValueError(f"Unknown BFCL case: {case_id}")
    if limit > 0:
        selected = selected[:limit]
    return selected


def configure_lock_root(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    from bfcl_eval import utils
    from bfcl_eval.constants import eval_config

    # BFCL imports LOCK_DIR into utils by value, so update both references.
    eval_config.LOCK_DIR = path
    utils.LOCK_DIR = path


def is_single_case_run(case_id: str | None, limit: int) -> bool:
    return bool(case_id) or limit == 1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--alias")
    parser.add_argument("--category", action="append", required=True)
    parser.add_argument("--case-id")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--result-root")
    parser.add_argument("--score-root")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--transport", choices=("responses", "chat-completions"), default="responses")
    args = parser.parse_args()

    from bfcl_eval import _llm_response_generation as generation

    if args.list:
        configure_lock_root(Path(os.environ.get("GPU45_BFCL_LOCK_ROOT", "/var/lib/gpu45/benchmarks/bfcl-locks")))
        tasks = []
        for category in args.category:
            _, entries = generation.get_involved_test_entries([category], False)
            tasks.extend(f"{category}::{entry['id']}" for entry in entries)
        if args.limit > 0:
            tasks = tasks[: args.limit]
        print("GPU45_TASKS=" + json.dumps(tasks, separators=(",", ":")))
        return

    if not args.alias or not args.result_root or not args.score_root:
        parser.error("--alias, --result-root, and --score-root are required unless --list is used")
    if len(args.category) != 1:
        parser.error("exactly one --category is required when running a case")
    category = args.category[0]

    result_root = Path(args.result_root).resolve()
    score_root = Path(args.score_root).resolve()
    result_root.mkdir(parents=True, exist_ok=True)
    score_root.mkdir(parents=True, exist_ok=True)
    lock_root = result_root.parent / "locks"

    # BFCL defaults to lock files inside its source checkout. Keep the pinned
    # harness immutable and place per-run locks alongside the campaign output.
    configure_lock_root(lock_root)
    from bfcl_eval.eval_checker import eval_runner

    registry_name = "gpu45-bfcl-model"
    register_model(registry_name, args.alias, args.transport)

    if args.case_id or args.limit > 0:
        original = generation.get_involved_test_entries

        def limited(categories: list[str], run_ids: bool):
            names, entries = original(categories, run_ids)
            return names, select_entries(entries, args.case_id, args.limit)

        generation.get_involved_test_entries = limited

    namespace = argparse.Namespace(
        model=[registry_name],
        test_category=[category],
        temperature=0.0,
        include_input_log=True,
        exclude_state_log=False,
        num_threads=1,
        num_gpus=0,
        backend="vllm",
        gpu_memory_utilization=0.0,
        result_dir=str(result_root),
        run_ids=False,
        allow_overwrite=True,
        skip_server_setup=True,
        local_model_path=None,
        lora_modules=None,
        enable_lora=False,
        max_lora_rank=None,
    )
    generation.main(namespace)
    try:
        eval_runner.main([registry_name], [category], str(result_root), str(score_root), partial_eval=bool(args.case_id or args.limit > 0))
    except statistics.StatisticsError:
        if not is_single_case_run(args.case_id, args.limit):
            raise
        # BFCL's aggregate CSV asks for a sample standard deviation. A
        # one-item diagnostic has no standard deviation, but its verifier
        # score file is complete and remains the source of truth.
    print("GPU45_RESULT=" + json.dumps(read_score(score_root, category), separators=(",", ":")))


if __name__ == "__main__":
    os.environ.setdefault("OPENAI_API_KEY", "gpu45-benchmark")
    main()
