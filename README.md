# Meeting AI (MVP)

Meeting AI is a FastAPI + PostgreSQL app for:

- user registration/login (JWT auth)
- meeting creation
- audio upload per meeting
- durable queued processing (Celery + Redis)
- structured insights extraction (key points, decisions, action items, risks)
- speaker timeline segments (timestamped transcript chunks)
- execution tasks (create/import/update/delete meeting follow-up tasks)
- viewing results in a built-in frontend (`/app`)

The app runs in two processing modes:

- `placeholder` (default): no external API required
- `openai`: real transcription + structured summary if configured

## Project Structure

```text
backend/
  app/
    core/        # config, db, auth helpers
    models/      # SQLAlchemy models
    schemas/     # Pydantic schemas
    services/    # processing logic (placeholder/openai)
    worker/      # Celery app + task workers
  alembic/       # database migrations
frontend/        # static UI served by FastAPI at /app
docker-compose.yml
alembic.ini
```

## Local Run (Windows PowerShell)

From the project root:

```powershell
cd "C:\Users\Avdhut Shinde\AI Projects\meeting-ai"

python -m venv .venv
.\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
pip install -r backend\requirements.txt

Copy-Item backend\.env.example backend\.env
docker compose up -d db redis
alembic upgrade head

# Terminal 1: API
uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8010

# Terminal 2: Celery worker
celery -A backend.app.worker.celery_app.celery_app worker --pool=solo --loglevel=info
```

Open:

- Frontend: `http://127.0.0.1:8010/app/`
- API docs: `http://127.0.0.1:8010/docs`

## Daily Run

```powershell
cd "C:\Users\Avdhut Shinde\AI Projects\meeting-ai"
.\.venv\Scripts\Activate.ps1
docker compose up -d db redis
```

Run API:

```powershell
uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8010
```

Run worker (new terminal):

```powershell
celery -A backend.app.worker.celery_app.celery_app worker --pool=solo --loglevel=info
```

## Run Tests

From the project root:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pytest -q
```

## Using OpenAI Processing (Optional)

Edit `backend/.env`:

```env
PROCESSING_PROVIDER=openai
OPENAI_API_KEY=your_api_key_here
PROCESSING_FALLBACK_TO_PLACEHOLDER=true
```

Behavior:

- If OpenAI succeeds, transcript and summary come from the provider.
- If OpenAI fails and fallback is enabled, placeholder output is stored and the error is logged.

## Processing Flow

1. Create a meeting
2. Upload audio (`.wav` works well for metadata detection)
3. Click `Process Meeting`
4. Backend sets status to `processing`, records `processing_task_id`, and enqueues Celery task
5. Worker processes audio and writes `processed` or `error` back to DB
6. Frontend auto-polls until status becomes `processed` or `error`

## Structured Outputs

Each processed meeting now stores:

- `summary`: concise paragraph summary
- `key_points`: bullet list of major discussion points
- `decisions`: explicit decisions made in the meeting
- `action_items`: task list with optional owner and due date
- `risks`: known blockers or risks
- `transcript_segments`: timestamped timeline entries with speaker + text

## Task Execution APIs

Task workflow endpoints (all JWT-protected and meeting-owner scoped):

- `GET /meetings/{meeting_id}/tasks`
- `POST /meetings/{meeting_id}/tasks`
- `PATCH /meetings/{meeting_id}/tasks/{task_id}`
- `DELETE /meetings/{meeting_id}/tasks/{task_id}`
- `POST /meetings/{meeting_id}/tasks/import-action-items`

## Upload Validation Rules

By default, upload API enforces:

- max size: `25 MB` (`UPLOAD_MAX_SIZE_BYTES`)
- allowed extensions: `.wav,.mp3,.m4a,.mp4,.mpeg,.mpga,.webm,.ogg`
- allowed MIME types: configured by `UPLOAD_ALLOWED_MIME_TYPES`
- empty files are rejected

## Notes / Limitations

- Celery worker must be running for processing to complete.
- If Redis/Celery is down and `CELERY_FALLBACK_TO_INLINE=true`, processing falls back to inline mode.
- If `PROCESSING_PROVIDER=placeholder` and `PROCESS_SYNC_WHEN_PROVIDER_PLACEHOLDER=true`, processing is immediate inline by default.
- Audio files are stored locally under `backend/uploads/`.
- `placeholder` mode generates sample transcript/summary content plus file metadata.

## Troubleshooting

If login/register fails:

```powershell
docker compose ps
alembic upgrade head
```

If PowerShell blocks venv activation:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```
