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
