"""Client for the GPU45 central resource manager."""

from __future__ import annotations
import json, os, threading, time, urllib.error, urllib.request

URL = os.environ.get("GPU45_RESOURCE_MANAGER_URL", "http://127.0.0.1:8040").rstrip("/")
TOKEN = os.environ.get("GPU45_RESOURCE_MANAGER_TOKEN", "")


def _request(path: str, payload: dict | None = None, timeout: int = 15) -> tuple[int, dict]:
    headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(URL + path, data=data, headers=headers, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode() or "{}")
    except (urllib.error.URLError, TimeoutError, OSError):
        return 0, {"error": "resource manager unavailable"}


class Lease:
    def __init__(self, lease_id: str):
        self.lease_id = lease_id
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._heartbeat, daemon=True)
        self._thread.start()

    def _heartbeat(self) -> None:
        while not self._stop.wait(20):
            status, _ = _request(f"/v1/leases/{self.lease_id}/heartbeat", {})
            if status == 404:
                self._stop.set()

    def release(self) -> None:
        self._stop.set()
        _request(f"/v1/leases/{self.lease_id}/release", {})


def acquire_lease(job_id: str, kind: str, priority: int, preemptible: bool, resume_policy: str, timeout: int = 600) -> Lease:
    if not TOKEN:
        raise RuntimeError("GPU45 resource manager token is missing")
    status, response = _request("/v1/leases/acquire", {"jobId": job_id, "kind": kind, "priority": priority, "preemptible": preemptible, "resumePolicy": resume_policy}, timeout=120)
    if status not in (200, 202): raise RuntimeError(response.get("error", "resource lease rejected"))
    lease_id = response["leaseId"]
    deadline = time.time() + timeout
    while time.time() < deadline:
        _, current = _request("/v1/state")
        if (current.get("owner") or {}).get("leaseId") == lease_id:
            return Lease(lease_id)
        time.sleep(1)
    _request(f"/v1/leases/{lease_id}/release", {})
    raise TimeoutError("Timed out waiting for GPU ownership")
