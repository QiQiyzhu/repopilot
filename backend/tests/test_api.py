import time

from fastapi.testclient import TestClient
from repopilot.api import create_app


def wait_for_task(client, task_id):
    for _ in range(150):
        task = client.get(f"/tasks/{task_id}").json()
        if task["status"] in {"succeeded", "failed", "cancelled", "timed_out"}:
            return task
        time.sleep(0.03)
    raise AssertionError("Task did not finish")


def test_api_end_to_end_sse_reconnection_and_retry(tmp_path):
    app = create_app(tmp_path / "data", tmp_path)
    with TestClient(app) as client:
        health = client.get("/health").json()
        response = client.post(
            "/tasks",
            json={
                "repository": health["demo_repository"],
                "task": "Fix clamp",
                "allow_repository_code": True,
            },
        )
        assert response.status_code == 202
        task_id = response.json()["task_id"]
        task = wait_for_task(client, task_id)
        assert task["status"] == "succeeded", task
        events = client.get(f"/tasks/{task_id}/events").text
        assert "event: trace" in events and "event: done" in events
        last = task["trace"][-1]["sequence"]
        resumed = client.get(f"/tasks/{task_id}/events", headers={"Last-Event-ID": str(last)}).text
        assert "event: trace" not in resumed and "event: done" in resumed
        assert client.get(f"/tasks/{task_id}/context").json()["context_tokens"] > 0
        assert client.get("/dashboard").json()["task_count"] == 1
        assert len(client.get("/skills").json()) == 5
        assert client.post(f"/tasks/{task_id}/retry").status_code == 202
        assert client.get("/tasks/missing").status_code == 404


def test_api_rejects_external_repo_origin_and_bad_request(tmp_path):
    with TestClient(create_app(tmp_path / "data", tmp_path)) as client:
        assert client.post("/tasks", json={"repository": "/", "task": "Fix bug"}).status_code == 422
        assert client.get("/health", headers={"origin": "https://evil.example"}).status_code == 403
        assert (
            client.post("/tasks", json={"repository": str(tmp_path), "task": "x"}).status_code
            == 422
        )


def test_optional_api_auth(tmp_path, monkeypatch):
    monkeypatch.setenv("REPOPILOT_API_TOKEN", "local-test-token")
    with TestClient(create_app(tmp_path / "data", tmp_path)) as client:
        assert client.get("/health").status_code == 401
        assert (
            client.get("/health", headers={"authorization": "Bearer local-test-token"}).status_code
            == 200
        )
