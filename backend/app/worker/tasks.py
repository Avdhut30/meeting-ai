from __future__ import annotations

import logging

from backend.app.core.db import SessionLocal
from backend.app.models import Meeting
from backend.app.services import build_meeting_notes
from backend.app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="meeting_ai.process_meeting", ignore_result=True)
def process_meeting_task(meeting_id: int, user_id: int) -> dict[str, int | str]:
    db = SessionLocal()
    meeting: Meeting | None = None
    try:
        meeting = (
            db.query(Meeting)
            .filter(Meeting.id == meeting_id, Meeting.user_id == user_id)
            .first()
        )
        if meeting is None:
            logger.warning(
                "Meeting not found for worker task (meeting_id=%s, user_id=%s)",
                meeting_id,
                user_id,
            )
            return {"status": "missing", "meeting_id": meeting_id}

        if not meeting.audio_path:
            meeting.status = "error"
            meeting.error_message = "Upload audio before processing"
            meeting.transcript = None
            meeting.summary = None
            meeting.transcript_segments = []
            meeting.key_points = []
            meeting.decisions = []
            meeting.action_items = []
            meeting.risks = []
            meeting.processed_at = None
            db.add(meeting)
            db.commit()
            return {"status": "error", "meeting_id": meeting_id}

        result = build_meeting_notes(
            meeting_title=meeting.title,
            file_path=meeting.audio_path,
            original_filename=meeting.original_filename,
        )
        meeting.transcript = result["transcript"]
        meeting.summary = result["summary"]
        meeting.transcript_segments = result.get("transcript_segments") or []
        meeting.key_points = result.get("key_points") or []
        meeting.decisions = result.get("decisions") or []
        meeting.action_items = result.get("action_items") or []
        meeting.risks = result.get("risks") or []
        meeting.mime_type = result["mime_type"] or meeting.mime_type
        meeting.file_size_bytes = result["file_size_bytes"] or meeting.file_size_bytes
        meeting.processed_at = result["processed_at"]
        meeting.status = "processed"
        meeting.error_message = None
        db.add(meeting)
        db.commit()
        logger.info("Meeting processed by celery worker (meeting_id=%s)", meeting_id)
        return {"status": "processed", "meeting_id": meeting_id}
    except Exception as exc:
        logger.exception("Celery task failed for meeting_id=%s", meeting_id)
        db.rollback()
        try:
            if meeting is None:
                meeting = (
                    db.query(Meeting)
                    .filter(Meeting.id == meeting_id, Meeting.user_id == user_id)
                    .first()
                )
            if meeting is not None:
                meeting.status = "error"
                meeting.error_message = str(exc)
                meeting.transcript_segments = []
                meeting.key_points = []
                meeting.decisions = []
                meeting.action_items = []
                meeting.risks = []
                meeting.processed_at = None
                db.add(meeting)
                db.commit()
        except Exception:
            db.rollback()
            logger.exception("Failed to persist task error for meeting_id=%s", meeting_id)
        raise
    finally:
        db.close()
