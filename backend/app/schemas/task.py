from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

TaskStatus = Literal["open", "in_progress", "done"]
TaskPriority = Literal["low", "normal", "high"]


class TaskCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    owner: str | None = Field(default=None, max_length=255)
    due_date: date | None = None
    status: TaskStatus = "open"
    priority: TaskPriority = "normal"


class TaskUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    owner: str | None = Field(default=None, max_length=255)
    due_date: date | None = None
    status: TaskStatus | None = None
    priority: TaskPriority | None = None


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    meeting_id: int
    created_by_user_id: int
    title: str
    owner: str | None = None
    due_date: date | None = None
    status: TaskStatus
    priority: TaskPriority
    source: str
    source_action_item_index: int | None = None
    created_at: datetime
    updated_at: datetime


class TaskImportResponse(BaseModel):
    created_count: int
    skipped_count: int
    tasks: list[TaskResponse]
