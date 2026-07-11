from argparse import Namespace

from wan_api.comfy_generate import t2v_workflow


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
