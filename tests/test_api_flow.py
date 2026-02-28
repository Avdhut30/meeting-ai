import time
import wave
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def _build_wav_bytes(sample_count: int = 8000, sample_rate: int = 8000) -> bytes:
    buffer = BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\x00\x00" * sample_count)
    return buffer.getvalue()


def _register_and_login(client: TestClient, email: str, password: str) -> dict[str, str]:
    register_response = client.post(
        "/auth/register",
        json={"email": email, "password": password},
    )
    assert register_response.status_code == 201, register_response.text

    login_response = client.post(
        "/auth/login",
        json={"email": email, "password": password},
    )
    assert login_response.status_code == 200, login_response.text
    token = login_response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from backend.app import main as main_module
    from backend.app.core import config as config_module
    from backend.app.core.db import Base, get_db
    from backend.app.worker import tasks as worker_tasks_module
    from backend.app.worker.celery_app import celery_app

    database_path = tmp_path / "test.sqlite3"
    uploads_path = tmp_path / "uploads"
    uploads_path.mkdir(parents=True, exist_ok=True)

    engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False},
    )
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(config_module.settings, "UPLOADS_DIR", str(uploads_path))
    monkeypatch.setattr(config_module.settings, "PROCESSING_PROVIDER", "placeholder")
    monkeypatch.setattr(config_module.settings, "PROCESSING_FALLBACK_TO_PLACEHOLDER", True)
    monkeypatch.setattr(config_module.settings, "CELERY_TASK_ALWAYS_EAGER", True)
    monkeypatch.setattr(config_module.settings, "CELERY_TASK_EAGER_PROPAGATES", True)
    monkeypatch.setattr(worker_tasks_module, "SessionLocal", testing_session_local)

    original_task_always_eager = celery_app.conf.task_always_eager
    original_task_eager_propagates = celery_app.conf.task_eager_propagates
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True

    def override_get_db():
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    main_module.app.dependency_overrides[get_db] = override_get_db

    with TestClient(main_module.app) as test_client:
        yield test_client

    main_module.app.dependency_overrides.clear()
    celery_app.conf.task_always_eager = original_task_always_eager
    celery_app.conf.task_eager_propagates = original_task_eager_propagates
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def test_auth_register_login_and_me(client: TestClient) -> None:
    headers = _register_and_login(
        client,
        email="auth_flow@example.com",
        password="Password123!",
    )

    me_response = client.get("/me", headers=headers)
    assert me_response.status_code == 200, me_response.text
    payload = me_response.json()
    assert payload["email"] == "auth_flow@example.com"
    assert isinstance(payload["id"], int)


def test_meeting_upload_process_download_and_reupload(client: TestClient) -> None:
    headers = _register_and_login(
        client,
        email="meeting_flow@example.com",
        password="Password123!",
    )

    create_response = client.post("/meetings", json={"title": "Team Sync"}, headers=headers)
    assert create_response.status_code == 201, create_response.text
    meeting_id = create_response.json()["id"]

    upload_response = client.post(
        f"/meetings/{meeting_id}/upload",
        headers=headers,
        files={"file": ("meeting1.wav", _build_wav_bytes(8000), "audio/wav")},
    )
    assert upload_response.status_code == 200, upload_response.text
    uploaded_meeting = upload_response.json()["meeting"]
    assert uploaded_meeting["status"] == "uploaded"
    assert uploaded_meeting["transcript"] is None
    assert uploaded_meeting["summary"] is None
    assert uploaded_meeting["transcript_segments"] == []
    assert uploaded_meeting["key_points"] == []
    assert uploaded_meeting["decisions"] == []
    assert uploaded_meeting["action_items"] == []
    assert uploaded_meeting["risks"] == []
    assert uploaded_meeting["processed_at"] is None

    process_response = client.post(f"/meetings/{meeting_id}/process", headers=headers)
    assert process_response.status_code == 200, process_response.text
    process_payload = process_response.json()
    assert process_payload["meeting"]["status"] in {"processing", "processed"}
    if process_payload["meeting"]["status"] == "processing":
        assert process_payload["meeting"]["processing_task_id"]

    final_meeting = None
    for _ in range(40):
        meeting_response = client.get(f"/meetings/{meeting_id}", headers=headers)
        assert meeting_response.status_code == 200, meeting_response.text
        final_meeting = meeting_response.json()
        if final_meeting["status"] in {"processed", "error"}:
            break
        time.sleep(0.05)

    assert final_meeting is not None
    assert final_meeting["status"] == "processed"
    assert final_meeting["summary"]
    assert final_meeting["transcript"]
    assert isinstance(final_meeting["transcript_segments"], list)
    assert len(final_meeting["transcript_segments"]) > 0
    assert all("start_seconds" in segment and "end_seconds" in segment for segment in final_meeting["transcript_segments"])
    assert isinstance(final_meeting["key_points"], list)
    assert len(final_meeting["key_points"]) > 0
    assert isinstance(final_meeting["decisions"], list)
    assert isinstance(final_meeting["action_items"], list)
    assert len(final_meeting["action_items"]) > 0
    assert isinstance(final_meeting["risks"], list)
    assert all("task" in item and item["task"] for item in final_meeting["action_items"])
    assert final_meeting["processed_at"] is not None

    download_response = client.get(f"/meetings/{meeting_id}/download", headers=headers)
    assert download_response.status_code == 200, download_response.text
    assert len(download_response.content) > 0

    reupload_response = client.post(
        f"/meetings/{meeting_id}/upload",
        headers=headers,
        files={"file": ("meeting2.wav", _build_wav_bytes(4000), "audio/wav")},
    )
    assert reupload_response.status_code == 200, reupload_response.text
    reuploaded = reupload_response.json()["meeting"]
    assert reuploaded["status"] == "uploaded"
    assert reuploaded["transcript"] is None
    assert reuploaded["summary"] is None
    assert reuploaded["transcript_segments"] == []
    assert reuploaded["key_points"] == []
    assert reuploaded["decisions"] == []
    assert reuploaded["action_items"] == []
    assert reuploaded["risks"] == []
    assert reuploaded["processed_at"] is None


def test_meeting_access_is_scoped_to_owner(client: TestClient) -> None:
    owner_headers = _register_and_login(
        client,
        email="owner@example.com",
        password="Password123!",
    )
    other_headers = _register_and_login(
        client,
        email="other@example.com",
        password="Password123!",
    )

    create_response = client.post("/meetings", json={"title": "Private Meeting"}, headers=owner_headers)
    assert create_response.status_code == 201, create_response.text
    meeting_id = create_response.json()["id"]

    forbidden_response = client.get(f"/meetings/{meeting_id}", headers=other_headers)
    assert forbidden_response.status_code == 404


def test_process_without_audio_returns_noop_message(client: TestClient) -> None:
    headers = _register_and_login(
        client,
        email="no_audio_process@example.com",
        password="Password123!",
    )
    create_response = client.post("/meetings", json={"title": "No Audio Yet"}, headers=headers)
    assert create_response.status_code == 201, create_response.text
    meeting_id = create_response.json()["id"]

    process_response = client.post(f"/meetings/{meeting_id}/process", headers=headers)
    assert process_response.status_code == 200, process_response.text
    payload = process_response.json()
    assert payload["message"] == "Upload audio before processing"
    assert payload["meeting"]["status"] == "created"
    assert payload["meeting"]["audio_path"] is None


def test_upload_rejects_unsupported_extension(client: TestClient) -> None:
    headers = _register_and_login(
        client,
        email="bad_extension@example.com",
        password="Password123!",
    )
    create_response = client.post("/meetings", json={"title": "Bad Extension"}, headers=headers)
    assert create_response.status_code == 201, create_response.text
    meeting_id = create_response.json()["id"]

    upload_response = client.post(
        f"/meetings/{meeting_id}/upload",
        headers=headers,
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert upload_response.status_code == 415, upload_response.text
    assert "Unsupported file extension" in upload_response.json()["detail"]

    meeting_response = client.get(f"/meetings/{meeting_id}", headers=headers)
    assert meeting_response.status_code == 200, meeting_response.text
    meeting = meeting_response.json()
    assert meeting["status"] == "created"
    assert meeting["audio_path"] is None


def test_upload_rejects_unsupported_mime_type(client: TestClient) -> None:
    headers = _register_and_login(
        client,
        email="bad_mime@example.com",
        password="Password123!",
    )
    create_response = client.post("/meetings", json={"title": "Bad Mime"}, headers=headers)
    assert create_response.status_code == 201, create_response.text
    meeting_id = create_response.json()["id"]

    upload_response = client.post(
        f"/meetings/{meeting_id}/upload",
        headers=headers,
        files={"file": ("audio.wav", _build_wav_bytes(1000), "text/plain")},
    )
    assert upload_response.status_code == 415, upload_response.text
    assert "Unsupported media type" in upload_response.json()["detail"]

    meeting_response = client.get(f"/meetings/{meeting_id}", headers=headers)
    assert meeting_response.status_code == 200, meeting_response.text
    meeting = meeting_response.json()
    assert meeting["status"] == "created"
    assert meeting["audio_path"] is None


def test_upload_rejects_oversized_file(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.app.core import config as config_module

    monkeypatch.setattr(config_module.settings, "UPLOAD_MAX_SIZE_BYTES", 256)

    headers = _register_and_login(
        client,
        email="oversized_upload@example.com",
        password="Password123!",
    )
    create_response = client.post("/meetings", json={"title": "Oversized Upload"}, headers=headers)
    assert create_response.status_code == 201, create_response.text
    meeting_id = create_response.json()["id"]

    upload_response = client.post(
        f"/meetings/{meeting_id}/upload",
        headers=headers,
        files={"file": ("audio.wav", _build_wav_bytes(1000), "audio/wav")},
    )
    assert upload_response.status_code == 413, upload_response.text
    assert "File exceeds maximum allowed size" in upload_response.json()["detail"]

    meeting_response = client.get(f"/meetings/{meeting_id}", headers=headers)
    assert meeting_response.status_code == 200, meeting_response.text
    meeting = meeting_response.json()
    assert meeting["status"] == "created"
    assert meeting["audio_path"] is None


def test_task_crud_and_import_from_action_items(client: TestClient) -> None:
    headers = _register_and_login(
        client,
        email="tasks_flow@example.com",
        password="Password123!",
    )

    create_response = client.post("/meetings", json={"title": "Task Meeting"}, headers=headers)
    assert create_response.status_code == 201, create_response.text
    meeting_id = create_response.json()["id"]

    upload_response = client.post(
        f"/meetings/{meeting_id}/upload",
        headers=headers,
        files={"file": ("meeting.wav", _build_wav_bytes(8000), "audio/wav")},
    )
    assert upload_response.status_code == 200, upload_response.text

    process_response = client.post(f"/meetings/{meeting_id}/process", headers=headers)
    assert process_response.status_code == 200, process_response.text

    for _ in range(40):
        meeting_response = client.get(f"/meetings/{meeting_id}", headers=headers)
        assert meeting_response.status_code == 200, meeting_response.text
        if meeting_response.json()["status"] == "processed":
            break
        time.sleep(0.05)

    import_response = client.post(f"/meetings/{meeting_id}/tasks/import-action-items", headers=headers)
    assert import_response.status_code == 200, import_response.text
    import_payload = import_response.json()
    assert import_payload["created_count"] >= 1
    assert len(import_payload["tasks"]) == import_payload["created_count"]

    list_response = client.get(f"/meetings/{meeting_id}/tasks", headers=headers)
    assert list_response.status_code == 200, list_response.text
    imported_tasks = list_response.json()
    assert len(imported_tasks) >= import_payload["created_count"]

    manual_create = client.post(
        f"/meetings/{meeting_id}/tasks",
        headers=headers,
        json={
            "title": "Finalize roadmap",
            "owner": "Alice",
            "due_date": "2030-01-15",
            "status": "open",
            "priority": "high",
        },
    )
    assert manual_create.status_code == 201, manual_create.text
    manual_task = manual_create.json()
    assert manual_task["source"] == "manual"
    assert manual_task["status"] == "open"

    manual_update = client.patch(
        f"/meetings/{meeting_id}/tasks/{manual_task['id']}",
        headers=headers,
        json={"status": "done", "owner": None},
    )
    assert manual_update.status_code == 200, manual_update.text
    updated_task = manual_update.json()
    assert updated_task["status"] == "done"
    assert updated_task["owner"] is None

    overdue_date = (date.today() - timedelta(days=2)).isoformat()
    overdue_create = client.post(
        f"/meetings/{meeting_id}/tasks",
        headers=headers,
        json={
            "title": "Fix overdue blocker",
            "due_date": overdue_date,
            "status": "open",
            "priority": "normal",
        },
    )
    assert overdue_create.status_code == 201, overdue_create.text

    overdue_response = client.get(f"/meetings/{meeting_id}/tasks?overdue_only=true", headers=headers)
    assert overdue_response.status_code == 200, overdue_response.text
    overdue_tasks = overdue_response.json()
    assert any(task["title"] == "Fix overdue blocker" for task in overdue_tasks)

    done_response = client.get(f"/meetings/{meeting_id}/tasks?status=done", headers=headers)
    assert done_response.status_code == 200, done_response.text
    done_tasks = done_response.json()
    assert any(task["id"] == manual_task["id"] for task in done_tasks)

    delete_response = client.delete(f"/meetings/{meeting_id}/tasks/{manual_task['id']}", headers=headers)
    assert delete_response.status_code == 204, delete_response.text

    deleted_check = client.get(f"/meetings/{meeting_id}/tasks?status=done", headers=headers)
    assert deleted_check.status_code == 200, deleted_check.text
    assert all(task["id"] != manual_task["id"] for task in deleted_check.json())


def test_task_endpoints_are_scoped_to_owner(client: TestClient) -> None:
    owner_headers = _register_and_login(
        client,
        email="task_owner@example.com",
        password="Password123!",
    )
    other_headers = _register_and_login(
        client,
        email="task_other@example.com",
        password="Password123!",
    )

    create_response = client.post("/meetings", json={"title": "Scoped Tasks"}, headers=owner_headers)
    assert create_response.status_code == 201, create_response.text
    meeting_id = create_response.json()["id"]

    task_create = client.post(
        f"/meetings/{meeting_id}/tasks",
        headers=owner_headers,
        json={"title": "Owner-only task", "status": "open", "priority": "normal"},
    )
    assert task_create.status_code == 201, task_create.text
    task_id = task_create.json()["id"]

    other_list = client.get(f"/meetings/{meeting_id}/tasks", headers=other_headers)
    assert other_list.status_code == 404

    other_patch = client.patch(
        f"/meetings/{meeting_id}/tasks/{task_id}",
        headers=other_headers,
        json={"status": "done"},
    )
    assert other_patch.status_code == 404

    other_delete = client.delete(f"/meetings/{meeting_id}/tasks/{task_id}", headers=other_headers)
    assert other_delete.status_code == 404
