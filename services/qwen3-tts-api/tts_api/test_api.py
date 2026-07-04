"""
Test script for TTS API. Run from project root with server running:
  python tts_api/test_api.py
Or with base URL: python tts_api/test_api.py http://localhost:8000
"""
import json
import sys
import urllib.error
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")


def request(method, path, body=None, expect_status=200):
    url = f"{BASE}{path}"
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            if expect_status and resp.status != expect_status:
                raise SystemExit(f"Expected status {expect_status}, got {resp.status} for {method} {path}")
            ct = resp.headers.get("Content-Type", "")
            if "application/json" in ct:
                return json.loads(resp.read().decode("utf-8"))
            return resp.read()
    except urllib.error.HTTPError as e:
        if expect_status and e.code != expect_status:
            raise SystemExit(f"Expected status {expect_status}, got {e.code} for {method} {path}: {e.read()}")
        if expect_status:
            return None
        raise


def main():
    print("Testing TTS API at", BASE)
    failed = []

    # 1. Health
    print("1. GET /health ...", end=" ")
    try:
        r = request("GET", "/health")
        assert r.get("status") == "ok"
        print("OK")
    except Exception as e:
        print("FAIL:", e)
        failed.append("health")
        return failed

    # 2. List voices (may be empty)
    print("2. GET /voices ...", end=" ")
    try:
        voices = request("GET", "/voices")
        assert isinstance(voices, list)
        print("OK (count=%s)" % len(voices))
    except Exception as e:
        print("FAIL:", e)
        failed.append("list voices")
        return failed

    # 3. Create voice (loads model, may be slow)
    print("3. POST /voices (create) ...", end=" ", flush=True)
    try:
        voice = request("POST", "/voices", body={
            "instruct": "Calm male narrator, clear and neutral.",
            "language": "English",
            "name": "test_voice_api",
        }, expect_status=201)
        assert "id" in voice and "name" in voice and voice["name"] == "test_voice_api"
        voice_id = voice["id"]
        print("OK id=%s" % voice_id[:8])
    except Exception as e:
        print("FAIL:", e)
        failed.append("create voice")
        return failed

    # 4. Get voice
    print("4. GET /voices/{id} ...", end=" ")
    try:
        v = request("GET", f"/voices/{voice_id}")
        assert v["id"] == voice_id and v["name"] == "test_voice_api"
        print("OK")
    except Exception as e:
        print("FAIL:", e)
        failed.append("get voice")

    # 5. Get voice sample (paragraph MP3)
    print("5. GET /voices/{id}/sample ...", end=" ")
    try:
        req = urllib.request.Request(f"{BASE}/voices/{voice_id}/sample", method="GET")
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
            assert len(data) > 1000
            assert resp.headers.get("Content-Type", "").startswith("audio/mpeg") or data[:3] == b"ID3" or data[:2] == b"\xff\xfb"
        print("OK (%s bytes MP3)" % len(data))
    except Exception as e:
        print("FAIL:", e)
        failed.append("voice sample")

    # 6. Rename voice
    print("6. PATCH /voices/{id} (rename) ...", end=" ")
    try:
        req = urllib.request.Request(f"{BASE}/voices/{voice_id}", data=b'{"name":"test_voice_renamed"}', method="PATCH")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=10) as resp:
            v = json.loads(resp.read().decode())
        assert v["name"] == "test_voice_renamed"
        print("OK")
    except Exception as e:
        print("FAIL:", e)
        failed.append("rename voice")

    # 7. Synthesize with use_default
    print("7. POST /synthesize (use_default) ...", end=" ", flush=True)
    try:
        req = urllib.request.Request(f"{BASE}/synthesize", data=b'{"text":"Hello world.","use_default":true}', method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = resp.read()
            assert len(data) > 1000
            assert resp.headers.get("Content-Type", "").startswith("audio/mpeg") or data[:3] == b"ID3" or data[:2] == b"\xff\xfb"
        print("OK (%s bytes MP3)" % len(data))
    except Exception as e:
        print("FAIL:", e)
        failed.append("synthesize default")

    # 8. Synthesize with voice_id
    print("8. POST /synthesize (voice_id) ...", end=" ", flush=True)
    try:
        req = urllib.request.Request(f"{BASE}/synthesize", data=json.dumps({
            "text": "Short test.",
            "voice_id": voice_id,
        }).encode(), method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = resp.read()
            assert len(data) > 1000
            assert resp.headers.get("Content-Type", "").startswith("audio/mpeg") or data[:3] == b"ID3" or data[:2] == b"\xff\xfb"
        print("OK (%s bytes MP3)" % len(data))
    except Exception as e:
        print("FAIL:", e)
        failed.append("synthesize voice")

    # 9. POST /models (start training, 202)
    print("9. POST /models (start training) ...", end=" ", flush=True)
    try:
        req = urllib.request.Request(f"{BASE}/models", data=json.dumps({"voice_id": voice_id}).encode(), method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=10) as resp:
            assert resp.status == 202
            r = json.loads(resp.read().decode())
        model_id = r.get("model_id")
        assert model_id and r.get("status") == "training"
        print("OK model_id=%s" % model_id[:8])
    except Exception as e:
        print("FAIL:", e)
        failed.append("create model")
        model_id = None

    # 10. GET /models and GET /models/{id}
    if model_id:
        print("10. GET /models and GET /models/{id} ...", end=" ")
        try:
            models = request("GET", "/models")
            assert isinstance(models, list)
            m = request("GET", f"/models/{model_id}")
            assert m["id"] == model_id and m.get("status") in ("training", "ready", "failed")
            print("OK status=%s" % m.get("status"))
        except Exception as e:
            print("FAIL:", e)
            failed.append("list/get model")

        # 11. GET /models/{id}/sample while training -> 409
        print("11. GET /models/{id}/sample (expect 409 if training) ...", end=" ")
        try:
            request("GET", f"/models/{model_id}/sample", expect_status=409)
            print("OK (409 as expected)")
        except urllib.error.HTTPError as e:
            if e.code == 409:
                print("OK (409)")
            else:
                print("FAIL:", e.code)
                failed.append("model sample 409")
        except Exception as e:
            if "409" in str(e):
                print("OK")
            else:
                print("FAIL:", e)
                failed.append("model sample 409")

    # 12. Error: 404 voice
    print("12. GET /voices/bad-id-404 ...", end=" ")
    try:
        request("GET", "/voices/bad-id-404", expect_status=404)
        print("OK")
    except Exception as e:
        print("FAIL:", e)
        failed.append("404 voice")

    # 13. Error: synthesize without option -> 400
    print("13. POST /synthesize no option (expect 400) ...", end=" ")
    try:
        req = urllib.request.Request(f"{BASE}/synthesize", data=b'{"text":"Hi"}', method="POST")
        req.add_header("Content-Type", "application/json")
        try:
            urllib.request.urlopen(req, timeout=5)
        except urllib.error.HTTPError as e:
            if e.code == 400:
                print("OK")
            else:
                print("FAIL:", e.code)
                failed.append("synthesize 400")
        else:
            print("FAIL: expected 400")
            failed.append("synthesize 400")
    except urllib.error.HTTPError as e:
        if e.code == 400:
            print("OK")
        else:
            print("FAIL:", e.code)
            failed.append("synthesize 400")
    except Exception as e:
        print("FAIL:", e)
        failed.append("synthesize 400")

    # 14. Delete model (if we have one and it's not still training we could delete; else skip or delete anyway)
    if model_id:
        print("14. DELETE /models/{id} ...", end=" ")
        try:
            req = urllib.request.Request(f"{BASE}/models/{model_id}", method="DELETE")
            with urllib.request.urlopen(req, timeout=10) as resp:
                assert resp.status == 204
            print("OK")
        except Exception as e:
            print("FAIL:", e)
            failed.append("delete model")

    # 15. Delete voice
    print("15. DELETE /voices/{id} ...", end=" ")
    try:
        req = urllib.request.Request(f"{BASE}/voices/{voice_id}", method="DELETE")
        with urllib.request.urlopen(req, timeout=10) as resp:
            assert resp.status == 204
        print("OK")
    except Exception as e:
        print("FAIL:", e)
        failed.append("delete voice")

    if failed:
        print("\nFailed:", failed)
    else:
        print("\nAll tests passed.")
    return failed


if __name__ == "__main__":
    sys.exit(0 if not main() else 1)
