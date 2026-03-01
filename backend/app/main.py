import logging
import socket
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.core.db import get_db
from backend.app.core.security import (
    create_access_token,
    get_password_hash,
    verify_password,
    decode_access_token,
)
from backend.app.models import Meeting, Task, User
from backend.app.schemas import (
    LoginRequest,
    MeetingCreateRequest,
    MeetingProcessResponse,
    MeetingResponse,
    MeetingUploadResponse,
    TaskCreateRequest,
    TaskImportResponse,
    TaskResponse,
    TaskUpdateRequest,
    TokenResponse,
    UserCreateRequest,
    UserResponse,
)
from backend.app.worker.celery_app import celery_app
from backend.app.worker.tasks import process_meeting_task

app = FastAPI(title= "Meeting AI", version="0.1.0" )
bearer_scheme = HTTPBearer(auto_error=False)
logger = logging.getLogger(__name__)


def _is_broker_available(timeout_seconds: float = 0.4) -> bool:
    parsed = urlparse(settings.CELERY_BROKER_URL)
    if parsed.scheme not in {"redis", "rediss"}:
        return True

    host = parsed.hostname or "localhost"
    port = parsed.port or 6379
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return True
    except OSError:
        return False


def _is_worker_available(timeout_seconds: float = 0.8) -> bool:
    try:
        inspector = celery_app.control.inspect(timeout=timeout_seconds)
        if inspector is None:
            return False
        response = inspector.ping()
        return bool(response)
    except Exception:
        return False


def _run_inline_processing_fallback(meeting: Meeting, user_id: int, db: Session, reason: str) -> MeetingProcessResponse:
    logger.warning(
        "Processing inline for meeting_id=%s because queue path is unavailable (%s)",
        meeting.id,
        reason,
    )
    try:
        process_meeting_task.run(meeting.id, user_id)
    except Exception as inline_exc:
        logger.exception("Inline fallback processing failed for meeting_id=%s", meeting.id)
        meeting.status = "error"
        meeting.error_message = f"Inline fallback processing failed: {inline_exc}"
        meeting.transcript_segments = []
        meeting.processing_task_id = None
        db.add(meeting)
        db.commit()
        db.refresh(meeting)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to process meeting (queue unavailable and inline fallback failed)",
        ) from inline_exc

    db.refresh(meeting)
    if reason == "placeholder_sync_mode":
        message = "Meeting processed inline"
    else:
        message = "Queue unavailable; processed inline"
    return MeetingProcessResponse(
        meeting=MeetingResponse.model_validate(meeting),
        message=message,
    )


def _normalize_content_type(content_type: str | None) -> str | None:
    if content_type is None:
        return None
    normalized = content_type.split(";", 1)[0].strip().lower()
    return normalized or None


def _validate_upload_file(filename: str, content_type: str | None) -> str | None:
    extension = Path(filename).suffix.lower()
    if not extension:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File extension is required",
        )

    allowed_extensions = settings.upload_allowed_extensions_set
    if extension not in allowed_extensions:
        allowed_text = ", ".join(sorted(allowed_extensions))
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file extension '{extension}'. Allowed: {allowed_text}",
        )

    normalized_content_type = _normalize_content_type(content_type)
    if normalized_content_type:
        allowed_mime_types = settings.upload_allowed_mime_types_set
        if normalized_content_type not in allowed_mime_types:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=f"Unsupported media type '{normalized_content_type}'",
            )

    return normalized_content_type


def _max_upload_size_label() -> str:
    bytes_in_mb = 1024 * 1024
    max_mb = settings.UPLOAD_MAX_SIZE_BYTES / bytes_in_mb
    if float(max_mb).is_integer():
        return f"{int(max_mb)} MB"
    return f"{max_mb:.1f} MB"


def _save_upload_file(file: UploadFile, destination: Path) -> int:
    total_size = 0
    max_size = settings.UPLOAD_MAX_SIZE_BYTES

    try:
        with destination.open("wb") as out_file:
            while chunk := file.file.read(1024 * 1024):
                total_size += len(chunk)
                if total_size > max_size:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"File exceeds maximum allowed size of {_max_upload_size_label()}",
                    )
                out_file.write(chunk)
    except Exception:
        if destination.exists():
            destination.unlink()
        raise
    finally:
        file.file.close()

    if total_size <= 0:
        if destination.exists():
            destination.unlink()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty")

    return total_size


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing authentication token",
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise _unauthorized()

    subject = decode_access_token(credentials.credentials)
    if not subject:
        raise _unauthorized()

    try:
        user_id = int(subject)
    except ValueError as exc:
        raise _unauthorized() from exc

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise _unauthorized()

    return user


def get_owned_meeting_or_404(meeting_id: int, user_id: int, db: Session) -> Meeting:
    meeting = (
        db.query(Meeting)
        .filter(Meeting.id == meeting_id, Meeting.user_id == user_id)
        .first()
    )
    if meeting is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
    return meeting


TASK_ALLOWED_STATUS = {"open", "in_progress", "done"}


def get_owned_task_or_404(task_id: int, meeting_id: int, user_id: int, db: Session) -> Task:
    task = (
        db.query(Task)
        .join(Meeting, Task.meeting_id == Meeting.id)
        .filter(
            Task.id == task_id,
            Task.meeting_id == meeting_id,
            Meeting.user_id == user_id,
        )
        .first()
    )
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return task


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _normalize_task_title(value: str) -> str:
    return " ".join(value.strip().split())


def _parse_action_item_due_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None

    candidate = value.strip()
    if not candidate:
        return None

    for parser in (
        lambda text: date.fromisoformat(text),
        lambda text: datetime.strptime(text, "%d-%m-%Y").date(),
        lambda text: datetime.strptime(text, "%m/%d/%Y").date(),
    ):
        try:
            return parser(candidate)
        except ValueError:
            continue
    return None

@app.get("/health")
def health():
    return {"status": "ok", "app": "meeting-ai", "version": app.version}


@app.api_route("/", include_in_schema=False, methods=["GET", "HEAD"])
def root_redirect():
    return RedirectResponse(url="/app/")


@app.post("/auth/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(payload: UserCreateRequest, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()

    existing_user = db.query(User).filter(User.email == email).first()
    if existing_user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")

    user = User(email=email, hashed_password=get_password_hash(payload.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@app.post("/auth/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    user = db.query(User).filter(User.email == email).first()

    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    token = create_access_token(subject=str(user.id))
    return TokenResponse(access_token=token)


@app.get("/me", response_model=UserResponse)
def read_me(current_user: User = Depends(get_current_user)):
    return current_user


@app.post("/meetings", response_model=MeetingResponse, status_code=status.HTTP_201_CREATED)
def create_meeting(
    payload: MeetingCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    meeting = Meeting(user_id=current_user.id, title=payload.title.strip(), status="created")
    db.add(meeting)
    db.commit()
    db.refresh(meeting)
    return meeting


@app.get("/meetings", response_model=list[MeetingResponse])
def list_meetings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    meetings = (
        db.query(Meeting)
        .filter(Meeting.user_id == current_user.id)
        .order_by(Meeting.created_at.desc(), Meeting.id.desc())
        .all()
    )
    return meetings


@app.get("/meetings/{meeting_id}", response_model=MeetingResponse)
def get_meeting(
    meeting_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return get_owned_meeting_or_404(meeting_id, current_user.id, db)


@app.post("/meetings/{meeting_id}/upload", response_model=MeetingUploadResponse)
def upload_meeting_audio(
    meeting_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    meeting = get_owned_meeting_or_404(meeting_id, current_user.id, db)
    if meeting.status == "processing":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Meeting is currently processing")

    if not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Filename is required")

    filename = Path(file.filename).name
    if not filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid filename")
    normalized_content_type = _validate_upload_file(filename, file.content_type)

    uploads_root = Path(settings.UPLOADS_DIR)
    meeting_dir = uploads_root / str(current_user.id) / str(meeting.id)
    meeting_dir.mkdir(parents=True, exist_ok=True)

    suffix = Path(filename).suffix.lower()
    saved_name = f"{uuid4().hex}{suffix}" if suffix else uuid4().hex
    destination = meeting_dir / saved_name

    file_size_bytes = _save_upload_file(file, destination)
    meeting.status = "uploaded"
    meeting.original_filename = filename
    meeting.audio_path = str(destination)
    meeting.mime_type = normalized_content_type
    meeting.file_size_bytes = file_size_bytes
    meeting.transcript = None
    meeting.summary = None
    meeting.transcript_segments = []
    meeting.key_points = []
    meeting.decisions = []
    meeting.action_items = []
    meeting.risks = []
    meeting.processing_task_id = None
    meeting.processing_started_at = None
    meeting.processed_at = None
    meeting.error_message = None
    db.add(meeting)
    db.commit()
    db.refresh(meeting)

    return MeetingUploadResponse(
        meeting=MeetingResponse.model_validate(meeting),
        filename=filename,
        saved_to=str(destination),
    )


@app.post("/meetings/{meeting_id}/process", response_model=MeetingProcessResponse)
def process_meeting(
    meeting_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    meeting = get_owned_meeting_or_404(meeting_id, current_user.id, db)

    if not meeting.audio_path:
        return MeetingProcessResponse(
            meeting=MeetingResponse.model_validate(meeting),
            message="Upload audio before processing",
        )
    if meeting.status == "processing":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Meeting is already processing")

    meeting.status = "processing"
    meeting.transcript = None
    meeting.summary = None
    meeting.transcript_segments = []
    meeting.key_points = []
    meeting.decisions = []
    meeting.action_items = []
    meeting.risks = []
    meeting.processing_task_id = None
    meeting.processing_started_at = datetime.now(timezone.utc)
    meeting.processed_at = None
    meeting.error_message = None
    db.add(meeting)
    db.commit()
    db.refresh(meeting)

    provider = settings.PROCESSING_PROVIDER.strip().lower()
    if settings.PROCESS_SYNC_WHEN_PROVIDER_PLACEHOLDER and provider == "placeholder":
        return _run_inline_processing_fallback(meeting, current_user.id, db, "placeholder_sync_mode")

    if settings.CELERY_FALLBACK_TO_INLINE and not _is_broker_available():
        return _run_inline_processing_fallback(meeting, current_user.id, db, "broker_connection_refused")
    if settings.CELERY_FALLBACK_TO_INLINE and not _is_worker_available():
        return _run_inline_processing_fallback(meeting, current_user.id, db, "worker_unavailable")

    try:
        task_result = process_meeting_task.apply_async(args=[meeting.id, current_user.id], ignore_result=True)
    except Exception as exc:
        logger.exception("Failed to enqueue processing task for meeting_id=%s", meeting.id)
        if settings.CELERY_FALLBACK_TO_INLINE:
            return _run_inline_processing_fallback(meeting, current_user.id, db, "enqueue_failure")

        meeting.status = "error"
        meeting.error_message = f"Failed to enqueue processing task: {exc}"
        meeting.processing_task_id = None
        meeting.processing_started_at = None
        db.add(meeting)
        db.commit()
        db.refresh(meeting)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to start processing job",
        ) from exc

    db.query(Meeting).filter(Meeting.id == meeting.id).update(
        {"processing_task_id": task_result.id},
        synchronize_session=False,
    )
    db.commit()
    meeting.processing_task_id = task_result.id

    return MeetingProcessResponse(
        meeting=MeetingResponse.model_validate(meeting),
        message="Meeting processing started",
    )


@app.get("/meetings/{meeting_id}/tasks", response_model=list[TaskResponse])
def list_tasks(
    meeting_id: int,
    task_status: str | None = Query(default=None, alias="status"),
    owner: str | None = Query(default=None),
    overdue_only: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    meeting = get_owned_meeting_or_404(meeting_id, current_user.id, db)

    query = db.query(Task).filter(Task.meeting_id == meeting.id)

    if task_status is not None:
        normalized_status = task_status.strip().lower()
        if normalized_status not in TASK_ALLOWED_STATUS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid task status filter. Use: open, in_progress, done",
            )
        query = query.filter(Task.status == normalized_status)

    if owner is not None and owner.strip():
        owner_text = owner.strip()
        query = query.filter(Task.owner.isnot(None), Task.owner.ilike(f"%{owner_text}%"))

    if overdue_only:
        query = query.filter(
            Task.due_date.isnot(None),
            Task.due_date < date.today(),
            Task.status != "done",
        )

    tasks = query.order_by(Task.created_at.desc(), Task.id.desc()).all()
    return tasks


@app.post("/meetings/{meeting_id}/tasks", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
def create_task(
    meeting_id: int,
    payload: TaskCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    meeting = get_owned_meeting_or_404(meeting_id, current_user.id, db)
    title = _normalize_task_title(payload.title)
    if not title:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Task title cannot be blank")

    task = Task(
        meeting_id=meeting.id,
        created_by_user_id=current_user.id,
        title=title,
        owner=_normalize_optional_text(payload.owner),
        due_date=payload.due_date,
        status=payload.status,
        priority=payload.priority,
        source="manual",
        source_action_item_index=None,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


@app.patch("/meetings/{meeting_id}/tasks/{task_id}", response_model=TaskResponse)
def update_task(
    meeting_id: int,
    task_id: int,
    payload: TaskUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task = get_owned_task_or_404(task_id, meeting_id, current_user.id, db)
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields provided for update")

    if "title" in updates:
        title = _normalize_task_title(updates["title"] or "")
        if not title:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Task title cannot be blank")
        task.title = title

    if "owner" in updates:
        task.owner = _normalize_optional_text(updates["owner"])

    if "due_date" in updates:
        task.due_date = updates["due_date"]

    if "status" in updates:
        task.status = updates["status"]

    if "priority" in updates:
        task.priority = updates["priority"]

    db.add(task)
    db.commit()
    db.refresh(task)
    return task


@app.delete("/meetings/{meeting_id}/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(
    meeting_id: int,
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task = get_owned_task_or_404(task_id, meeting_id, current_user.id, db)
    db.delete(task)
    db.commit()


@app.post("/meetings/{meeting_id}/tasks/import-action-items", response_model=TaskImportResponse)
def import_action_items_as_tasks(
    meeting_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    meeting = get_owned_meeting_or_404(meeting_id, current_user.id, db)
    raw_action_items = meeting.action_items if isinstance(meeting.action_items, list) else []

    existing_title_keys = {
        _normalize_task_title(existing.title).lower()
        for existing in db.query(Task).filter(Task.meeting_id == meeting.id).all()
    }

    created_tasks: list[Task] = []
    skipped_count = 0

    for idx, item in enumerate(raw_action_items):
        if not isinstance(item, dict):
            skipped_count += 1
            continue

        task_value = item.get("task")
        if not isinstance(task_value, str):
            skipped_count += 1
            continue

        task_title = _normalize_task_title(task_value)
        if not task_title:
            skipped_count += 1
            continue

        title_key = task_title.lower()
        if title_key in existing_title_keys:
            skipped_count += 1
            continue

        imported_task = Task(
            meeting_id=meeting.id,
            created_by_user_id=current_user.id,
            title=task_title,
            owner=_normalize_optional_text(item.get("owner") if isinstance(item.get("owner"), str) else None),
            due_date=_parse_action_item_due_date(item.get("due_date")),
            status="open",
            priority="normal",
            source="insight_import",
            source_action_item_index=idx,
        )
        db.add(imported_task)
        created_tasks.append(imported_task)
        existing_title_keys.add(title_key)

    if created_tasks:
        db.commit()
        for created_task in created_tasks:
            db.refresh(created_task)
    else:
        db.rollback()

    return TaskImportResponse(
        created_count=len(created_tasks),
        skipped_count=skipped_count,
        tasks=[TaskResponse.model_validate(task) for task in created_tasks],
    )


@app.get("/meetings/{meeting_id}/download")
def download_meeting_audio(
    meeting_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    meeting = get_owned_meeting_or_404(meeting_id, current_user.id, db)
    if not meeting.audio_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No audio uploaded for this meeting")

    file_path = Path(meeting.audio_path)
    if not file_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stored audio file not found")

    return FileResponse(
        path=file_path,
        media_type=meeting.mime_type or "application/octet-stream",
        filename=meeting.original_filename or file_path.name,
    )


app.mount("/app", StaticFiles(directory="frontend", html=True), name="frontend")
