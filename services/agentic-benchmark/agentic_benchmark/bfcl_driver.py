from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from pathlib import Path


def register_model(registry_name: str, alias: str) -> None:
    from bfcl_eval.constants.model_config import MODEL_CONFIG_MAPPING, ModelConfig
    from bfcl_eval.model_handler.api_inference.openai_response import OpenAIResponsesHandler

    class GPU45ResponsesHandler(OpenAIResponsesHandler):
        def generate_with_backoff(self, **kwargs):
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
        model_handler=GPU45ResponsesHandler,
        input_price=None,
        output_price=None,
        is_fc_model=True,
        underscore_to_dot=False,
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--alias", required=True)
    parser.add_argument("--category", required=True)
    parser.add_argument("--result-root", required=True)
    parser.add_argument("--score-root", required=True)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    result_root = Path(args.result_root).resolve()
    score_root = Path(args.score_root).resolve()
    result_root.mkdir(parents=True, exist_ok=True)
    score_root.mkdir(parents=True, exist_ok=True)
    lock_root = result_root.parent / "locks"
    lock_root.mkdir(parents=True, exist_ok=True)

    # BFCL defaults to lock files inside its source checkout. Keep the pinned
    # harness immutable and place per-run locks alongside the campaign output.
    from bfcl_eval.constants import eval_config

    eval_config.LOCK_DIR = lock_root
    from bfcl_eval import _llm_response_generation as generation
    from bfcl_eval.eval_checker import eval_runner

    registry_name = "gpu45-bfcl-model"
    register_model(registry_name, args.alias)

    if args.limit > 0:
        original = generation.get_involved_test_entries

        def limited(categories: list[str], run_ids: bool):
            names, entries = original(categories, run_ids)
            return names, entries[: args.limit]

        generation.get_involved_test_entries = limited

    namespace = argparse.Namespace(
        model=[registry_name],
        test_category=[args.category],
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
        eval_runner.main([registry_name], [args.category], str(result_root), str(score_root), partial_eval=args.limit > 0)
    except statistics.StatisticsError:
        if args.limit != 1:
            raise
        # BFCL's aggregate CSV asks for a sample standard deviation. A
        # one-item diagnostic has no standard deviation, but its verifier
        # score file is complete and remains the source of truth.
    print("GPU45_RESULT=" + json.dumps(read_score(score_root, args.category), separators=(",", ":")))


if __name__ == "__main__":
    os.environ.setdefault("OPENAI_API_KEY", "gpu45-benchmark")
    main()
