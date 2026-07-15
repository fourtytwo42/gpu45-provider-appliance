from argparse import Namespace

from wan_api.comfy_generate import find_saved_video, ltx23_workflow, t2v_workflow, wan22_a14b_workflow


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


def ltx_args(**overrides):
    values = dict(
        profile="ltx23-q4-preview", prompt="A car drives across a table.", negative_prompt="blur",
        seed=42, width=512, height=320, frames=49, fps=24, job_id="ltx-1", input_image=None,
    )
    values.update(overrides)
    return Namespace(**values)


def test_ltx_preview_workflow_generates_synchronized_audio() -> None:
    workflow = ltx23_workflow(ltx_args())

    assert workflow["1"]["inputs"]["unet_name"] == "ltx-2.3-22b-distilled-Q4_K_M.gguf"
    assert workflow["7"]["inputs"]["frame_rate"] == 24
    assert workflow["19"]["inputs"]["audio"] == ["18", 0]
    assert workflow["20"]["inputs"]["filename_prefix"] == "gpu45/ltx-1"


def test_ltx_i2v_conditions_the_video_latent() -> None:
    workflow = ltx23_workflow(ltx_args(input_image="/tmp/source.png"))

    assert workflow["30"]["class_type"] == "LoadImage"
    assert workflow["32"]["inputs"]["strength"] == 0.8
    assert workflow["8"]["inputs"]["video_latent"] == ["32", 0]


def test_ltx_balanced_adds_upscale_and_refinement() -> None:
    workflow = ltx23_workflow(ltx_args(profile="ltx23-q4-balanced"))

    assert workflow["22"]["class_type"] == "LTXVLatentUpsampler"
    assert workflow["27"]["inputs"]["sigmas"] == ["25", 0]
    assert workflow["17"]["inputs"]["latents"] == ["28", 0]
    assert workflow["18"]["inputs"]["samples"] == ["28", 1]


def test_ltx_video_falls_back_to_expected_output_prefix(tmp_path) -> None:
    output = tmp_path / "gpu45" / "job-7_00001_.mp4"
    output.parent.mkdir()
    output.write_bytes(b"video")

    assert find_saved_video({"outputs": {}}, tmp_path, "job-7") == output
