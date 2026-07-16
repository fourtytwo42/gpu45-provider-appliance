import asyncio
from io import BytesIO
from pathlib import Path

from fastapi import UploadFile

from wan_api import main
from wan_api.job_store import JobStore


def test_cancelled_state_cannot_be_overwritten(tmp_path, monkeypatch) -> None:
    store = JobStore(tmp_path / "jobs.json")
    monkeypatch.setattr(main, "_job_store", store)
    main.save_jobs([{"id": "job-1", "status": "cancelled", "error": "Cancelled by user."}])

    changed = main.update_job_unless_cancelled("job-1", status="failed", error="process exited")

    assert changed is False
    assert main.load_jobs()[0]["status"] == "cancelled"
    assert main.load_jobs()[0]["error"] == "Cancelled by user."


def test_legacy_sigterm_failure_is_reconciled_as_cancelled(tmp_path, monkeypatch) -> None:
    store = JobStore(tmp_path / "jobs.json")
    monkeypatch.setattr(main, "_job_store", store)
    main.save_jobs([{"id": "job-2", "status": "failed", "error": "generate.py exited with -15"}])

    result = main.cancel_job("job-2")

    assert result == {"ok": True, "reconciled": True}
    assert main.load_jobs()[0]["status"] == "cancelled"


def test_i2v_submission_persists_job_and_starts_runner(tmp_path, monkeypatch) -> None:
    store = JobStore(tmp_path / "jobs.json")
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    runner_calls: list[bool] = []
    monkeypatch.setattr(main, "_job_store", store)
    monkeypatch.setattr(main, "UPLOAD_DIR", upload_dir)
    monkeypatch.setattr(main, "profile_ready", lambda _profile: True)
    monkeypatch.setattr(main, "ensure_runner", lambda: runner_calls.append(True))

    result = asyncio.run(main.create_i2v_job(
        file=UploadFile(filename="source.png", file=BytesIO(b"image-data")),
        prompt="A camera moves through a forest.",
        negative_prompt="blur",
        profile="ltx23-q4",
        preset="preview",
        size="512*320",
        steps=8,
        duration_seconds=2,
        seed=7,
    ))

    assert result["status"] == "queued"
    assert result["mode"] == "i2v"
    assert result["solver"] == "euler"
    assert runner_calls == [True]
    assert len(main.load_jobs()) == 1
    assert (upload_dir / f"{result['id']}.png").read_bytes() == b"image-data"


def test_extend_job_inherits_parent_settings_and_extracts_last_frame(tmp_path, monkeypatch) -> None:
    store = JobStore(tmp_path / "jobs.json")
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    parent_output = tmp_path / "parent.mp4"
    parent_output.write_bytes(b"parent-video")
    runner_calls: list[bool] = []
    monkeypatch.setattr(main, "_job_store", store)
    monkeypatch.setattr(main, "UPLOAD_DIR", upload_dir)
    monkeypatch.setattr(main, "ensure_runner", lambda: runner_calls.append(True))
    monkeypatch.setattr(main, "extract_last_frame", lambda _source, target: target.write_bytes(b"last-frame"))
    main.save_jobs([{
        "id": "parent-1", "status": "completed", "output_path": str(parent_output),
        "output_duration_seconds": 2.0, "profile": "ltx23-q4", "profile_name": "LTX-2.3 Q4",
        "preset": "balanced", "preset_name": "Balanced", "size": "512*288", "steps": 11,
        "fps": 24, "negative_prompt": "blur", "solver": "euler",
    }])

    result = main.extend_job("parent-1", main.ExtendJobBody(
        prompt="The truck continues down the wet road.", duration_seconds=3, seed=9,
    ))

    assert result["status"] == "queued"
    assert result["mode"] == "extend"
    assert result["continuation_of"] == "parent-1"
    assert result["preset"] == "balanced"
    assert result["size"] == "512*288"
    assert result["steps"] == 11
    assert result["extension_duration_seconds"] == 3
    assert result["duration_seconds"] == 5.0
    assert Path(result["source_image_path"]).read_bytes() == b"last-frame"
    assert runner_calls == [True]


def test_parent_with_active_extension_cannot_be_deleted(tmp_path, monkeypatch) -> None:
    store = JobStore(tmp_path / "jobs.json")
    monkeypatch.setattr(main, "_job_store", store)
    main.save_jobs([
        {"id": "parent-2", "status": "completed"},
        {"id": "child-2", "status": "running", "continuation_of": "parent-2"},
    ])

    try:
        main.delete_job("parent-2")
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 409
    else:
        raise AssertionError("Expected parent deletion to be blocked while its extension is active.")


def test_startup_requeues_interrupted_jobs(tmp_path, monkeypatch) -> None:
    store = JobStore(tmp_path / "jobs.json")
    runner_calls: list[bool] = []
    monkeypatch.setattr(main, "_job_store", store)
    monkeypatch.setattr(main, "ensure_runner", lambda: runner_calls.append(True))
    main.save_jobs([{
        "id": "job-3",
        "status": "running",
        "started_at": "2026-07-14T12:00:00Z",
        "process_pid": 123,
        "process_group": True,
        "error": "stale",
    }])

    recovered = main.recover_pending_jobs()

    job = main.load_jobs()[0]
    assert recovered == 1
    assert job["status"] == "queued"
    assert job["started_at"] is None
    assert job["process_pid"] is None
    assert job["error"] is None
    assert runner_calls == [True]


def test_video_output_validation_rejects_truncated_duration() -> None:
    error = main.validate_video_output(
        {"duration_seconds": 5},
        {"duration_seconds": 1.292, "frame_count": 31},
    )

    assert error == "Output duration was 1.29s; expected approximately 5.00s."


def test_video_output_validation_accepts_requested_duration() -> None:
    error = main.validate_video_output(
        {"duration_seconds": 5},
        {"duration_seconds": 5.042, "frame_count": 121},
    )

    assert error is None


def test_detects_recoverable_gpu_transfer_fault(tmp_path) -> None:
    log_path = tmp_path / "video.log"
    log_path.write_text(
        "Memory access fault by GPU node-1 on address 0x123. Reason: Page not present.\n",
        encoding="utf-8",
    )

    assert main.has_recoverable_gpu_transfer_fault(log_path)


def test_does_not_retry_ordinary_generation_failure(tmp_path) -> None:
    log_path = tmp_path / "video.log"
    log_path.write_text("HIP out of memory. Tried to allocate 72 MiB.\n", encoding="utf-8")

    assert not main.has_recoverable_gpu_transfer_fault(log_path)


def test_video_request_accepts_twenty_second_duration() -> None:
    request = main.CreateJobBody(prompt="A slow camera pan.", duration_seconds=20)

    assert request.duration_seconds == 20


def test_ltx_model_exposes_one_through_twenty_seconds() -> None:
    profile = main.PROFILES["ltx23-q4"]

    assert profile["durations"] == list(range(1, 21))
    assert profile["max_tested_duration_seconds"] == 5


def test_ltx_balanced_is_a_preset_on_the_q4_model() -> None:
    profile = main.PROFILES["ltx23-q4"]
    balanced = profile["presets"]["balanced"]

    assert balanced["size"] == "512*288"
    assert balanced["steps"] == 11
    assert "512*288" in profile["sizes"]
    assert balanced["output_scale"] == 2
    assert balanced["modes"] == ["t2v", "i2v"]


def test_legacy_ltx_profile_ids_resolve_to_one_model() -> None:
    assert main.get_profile("ltx23-q4-preview")["id"] == "ltx23-q4"
    assert main.get_profile("ltx23-q4-balanced")["id"] == "ltx23-q4"


def test_vae_decode_progress_does_not_restart_denoising(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "LOG_DIR", tmp_path)
    (tmp_path / "job-4.log").write_text(
        "100%|██████████| 50/50 [1:00:43<00:00, 72.80s/it]\n"
        "VAE decoding:  22%|██▏       | 2/9 [00:59<03:26, 29.48s/it]",
        encoding="utf-8",
    )

    progress = main.job_progress({"id": "job-4", "status": "running"})

    assert progress == {
        "progress_percent": 92,
        "progress_label": "Decoding frame tiles 2/9",
        "progress_stage": "decoding",
    }
