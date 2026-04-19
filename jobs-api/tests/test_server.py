"""Coverage for jobs-api auth + validation + concurrency."""


class FakePopen:
    """Behaves like a never-finishing Popen for tests."""

    pid = 4242

    def poll(self):
        return None  # still running


def test_health_open_no_auth_required(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["auth_configured"] is True


def test_post_jobs_rejects_without_token(client):
    r = client.post("/jobs", json={"hotels": ["100"], "dates": "2026-04-25"})
    assert r.status_code == 401
    assert "invalid internal token" in r.json()["detail"]


def test_post_jobs_rejects_non_numeric_hotel(client, auth_header):
    r = client.post(
        "/jobs",
        json={"hotels": ["abc"], "dates": "2026-04-25"},
        headers=auth_header,
    )
    assert r.status_code == 422
    msg = str(r.json())
    assert "hotel id must be numeric" in msg


def test_post_jobs_rejects_malformed_dates(client, auth_header):
    r = client.post(
        "/jobs",
        json={"hotels": ["100"], "dates": "; rm -rf /"},
        headers=auth_header,
    )
    assert r.status_code == 422
    msg = str(r.json())
    assert "dates must match" in msg


def test_post_jobs_accepts_valid(client, server_module, auth_header, monkeypatch):
    monkeypatch.setattr(server_module.subprocess, "Popen", lambda *a, **kw: FakePopen())
    monkeypatch.setattr(server_module, "RUN_JOB_PY", _existing_path())
    r = client.post(
        "/jobs",
        json={
            "hotels": ["100"],
            "dates": "2026-04-25",
            "ota": "bookingdotcom",
            "los": 7,
            "persons": 2,
            "refresh": False,
        },
        headers=auth_header,
    )
    assert r.status_code == 202
    body = r.json()
    assert body["pid"] == FakePopen.pid
    assert body["job_id"]


def test_post_jobs_429_when_at_capacity(client, server_module, auth_header, monkeypatch):
    monkeypatch.setattr(server_module.subprocess, "Popen", lambda *a, **kw: FakePopen())
    monkeypatch.setattr(server_module, "RUN_JOB_PY", _existing_path())
    monkeypatch.setattr(server_module, "MAX_PARALLEL", 1)

    payload = {"hotels": ["100"], "dates": "2026-04-25", "ota": "bookingdotcom"}
    first = client.post("/jobs", json=payload, headers=auth_header)
    assert first.status_code == 202
    second = client.post("/jobs", json=payload, headers=auth_header)
    assert second.status_code == 429
    assert "Max parallel" in second.json()["detail"]


def test_get_status_404_for_unknown_job(client, auth_header):
    r = client.get("/jobs/does-not-exist/status", headers=auth_header)
    assert r.status_code == 404


def _existing_path():
    """Return any path that exists so the existence check inside create_job
    doesn't bail before our mocked Popen runs."""
    from pathlib import Path

    return Path(__file__)
