import asyncio
from io import BytesIO

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
        profile="wan22-ti2v-5b",
        size="832*480",
        steps=20,
        duration_seconds=2,
        seed=7,
    ))

    assert result["status"] == "queued"
    assert result["mode"] == "i2v"
    assert runner_calls == [True]
    assert len(main.load_jobs()) == 1
    assert (upload_dir / f"{result['id']}.png").read_bytes() == b"image-data"


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
