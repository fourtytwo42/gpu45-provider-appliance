from argparse import Namespace

from wan_api.comfy_generate import t2v_workflow, wan22_a14b_workflow


def test_t2v_workflow_uses_distilled_hunyuan_settings() -> None:
    workflow = t2v_workflow(Namespace(
        model="model.gguf",
        prompt="A camera pans across a city.",
        negative_prompt="blur",
        shift=5.0,
        cfg=1.0,
        seed=42,
        steps=20,
        width=848,
        height=480,
        frames=49,
        fps=12,
        job_id="job-1",
    ))

    assert workflow["1"]["class_type"] == "UnetLoaderGGUF"
    assert workflow["6"]["inputs"]["cfg"] == 1.0
    assert workflow["9"]["inputs"]["steps"] == 20
    assert workflow["10"]["inputs"] == {"width": 848, "height": 480, "length": 49, "batch_size": 1}
    assert workflow["15"]["inputs"]["filename_prefix"] == "gpu45/job-1"


def test_wan_a14b_workflow_splits_four_steps_between_experts() -> None:
    workflow = wan22_a14b_workflow(Namespace(
        prompt="A car drives through rain.", negative_prompt="blur", seed=7,
        width=832, height=480, frames=21, fps=12, job_id="a14b-1",
    ))

    assert workflow["1"]["class_type"] == "UnetLoaderGGUF"
    assert workflow["11"]["inputs"]["start_at_step"] == 0
    assert workflow["11"]["inputs"]["end_at_step"] == 2
    assert workflow["12"]["inputs"]["start_at_step"] == 2
    assert workflow["12"]["inputs"]["end_at_step"] == 4
    assert workflow["16"]["inputs"]["filename_prefix"] == "gpu45/a14b-1"
