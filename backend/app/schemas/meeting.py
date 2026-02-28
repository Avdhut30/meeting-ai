from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class MeetingCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)


class ActionItem(BaseModel):
    task: str
    owner: str | None = None
    due_date: str | None = None


class TranscriptSegment(BaseModel):
    start_seconds: float
    end_seconds: float
    speaker: str
    text: str


class MeetingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    title: str
    status: str
    original_filename: str | None = None
    audio_path: str | None = None
    mime_type: str | None = None
    file_size_bytes: int | None = None
    transcript: str | None = None
    summary: str | None = None
    transcript_segments: list[TranscriptSegment] | None = None
    key_points: list[str] | None = None
    decisions: list[str] | None = None
    action_items: list[ActionItem] | None = None
    risks: list[str] | None = None
    error_message: str | None = None
    processing_task_id: str | None = None
    created_at: datetime
    processing_started_at: datetime | None = None
    processed_at: datetime | None = None


class MeetingUploadResponse(BaseModel):
    meeting: MeetingResponse
    filename: str
    saved_to: str


class MeetingProcessResponse(BaseModel):
    meeting: MeetingResponse
    message: str
