from logic_platform.utils import ManusAPIClient, ManusAPIError


def test_poll_task_completion_retries_transient_404(monkeypatch):
    client = ManusAPIClient(api_key="test-key")
    calls = {"count": 0}
    sleeps = []

    def fake_get_task(task_id):
        calls["count"] += 1
        if calls["count"] == 1:
            raise ManusAPIError("API request failed: 404", 404)
        return {"status": "completed", "output": []}

    monkeypatch.setattr(client, "get_task", fake_get_task)
    monkeypatch.setattr("logic_platform.utils.time.sleep", sleeps.append)

    task = client.poll_task_completion(
        "task-1",
        poll_interval=1,
        max_wait=30,
        initial_delay=0,
    )

    assert task["status"] == "completed"
    assert calls["count"] == 2
    assert sleeps == [1]


def test_create_task_reuses_registered_task(monkeypatch, tmp_path):
    monkeypatch.setenv("LOGIC_PLATFORM_MANUS_TASK_REGISTRY", str(tmp_path / "manus_tasks.json"))
    client = ManusAPIClient(api_key="test-key")
    post_calls = {"count": 0}

    def fake_request(method, endpoint, **kwargs):
        if method == "GET":
            return {"status": "running", "output": []}
        post_calls["count"] += 1
        return {
            "task_id": "task-123",
            "task_title": "Mapping",
            "task_url": "https://manus.im/app/task-123",
        }

    monkeypatch.setattr(client, "_request", fake_request)

    first = client.create_task("same prompt", agent_profile="manus-1.6", task_mode="agent")
    second = client.create_task("same prompt", agent_profile="manus-1.6", task_mode="agent")

    assert first.task_id == "task-123"
    assert second.task_id == "task-123"
    assert post_calls["count"] == 1


def test_create_task_reuses_recent_registered_404(monkeypatch, tmp_path):
    monkeypatch.setenv("LOGIC_PLATFORM_MANUS_TASK_REGISTRY", str(tmp_path / "manus_tasks.json"))
    client = ManusAPIClient(api_key="test-key")
    post_calls = {"count": 0}

    def fake_request(method, endpoint, **kwargs):
        if method == "GET":
            raise ManusAPIError("API request failed: 404", 404)
        post_calls["count"] += 1
        return {
            "task_id": "task-404",
            "task_title": "Logic",
            "task_url": "https://manus.im/app/task-404",
        }

    monkeypatch.setattr(client, "_request", fake_request)

    first = client.create_task("same prompt", agent_profile="manus-1.6", task_mode="agent")
    second = client.create_task("same prompt", agent_profile="manus-1.6", task_mode="agent")

    assert first.task_id == "task-404"
    assert second.task_id == "task-404"
    assert post_calls["count"] == 1


def test_exhausted_404_marks_registered_task_not_found(monkeypatch, tmp_path):
    monkeypatch.setenv("LOGIC_PLATFORM_MANUS_TASK_REGISTRY", str(tmp_path / "manus_tasks.json"))
    client = ManusAPIClient(api_key="test-key")
    post_calls = {"count": 0}

    def fake_request(method, endpoint, **kwargs):
        if method == "GET":
            raise ManusAPIError("API request failed: 404", 404)
        post_calls["count"] += 1
        return {
            "task_id": "missing-task",
            "task_title": "Logic",
            "task_url": "https://manus.im/app/missing-task",
        }

    monkeypatch.setattr(client, "_request", fake_request)
    monkeypatch.setattr("logic_platform.utils.time.sleep", lambda _: None)
    created = client.create_task("prompt", agent_profile="manus-1.6", task_mode="agent")

    try:
        client.poll_task_completion(
            created.task_id,
            poll_interval=1,
            max_wait=1,
            initial_delay=0,
        )
    except ManusAPIError:
        pass

    assert client.create_task("prompt", agent_profile="manus-1.6", task_mode="agent").task_id == "missing-task"
    assert post_calls["count"] == 2
