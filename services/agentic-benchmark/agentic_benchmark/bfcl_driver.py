from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def register_model(alias: str) -> None:
    from bfcl_eval.constants.model_config import MODEL_CONFIG_MAPPING, ModelConfig
    from bfcl_eval.model_handler.api_inference.openai_response import OpenAIResponsesHandler

    MODEL_CONFIG_MAPPING[alias] = ModelConfig(
        model_name=alias,
        display_name=f"GPU45 {alias}",
        url="http://127.0.0.1:30001",
        org="GPU45",
        license="local-profile",
        model_handler=OpenAIResponsesHandler,
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

    from bfcl_eval import _llm_response_generation as generation
    from bfcl_eval.eval_checker import eval_runner

    register_model(args.alias)
    result_root = Path(args.result_root).resolve()
    score_root = Path(args.score_root).resolve()
    result_root.mkdir(parents=True, exist_ok=True)
    score_root.mkdir(parents=True, exist_ok=True)

    if args.limit > 0:
        original = generation.get_involved_test_entries

        def limited(categories: list[str], run_ids: bool):
            names, entries = original(categories, run_ids)
            return names, entries[: args.limit]

        generation.get_involved_test_entries = limited

    namespace = argparse.Namespace(
        model=[args.alias],
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
    eval_runner.main([args.alias], [args.category], str(result_root), str(score_root), partial_eval=args.limit > 0)
    print("GPU45_RESULT=" + json.dumps(read_score(score_root, args.category), separators=(",", ":")))


if __name__ == "__main__":
    os.environ.setdefault("OPENAI_API_KEY", "gpu45-benchmark")
    main()
