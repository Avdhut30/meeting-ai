# Meeting AI

Meeting AI is a full-stack application for turning meeting audio into structured outcomes.

## Live Demo

- App: https://meeting-ai-45ug.onrender.com/app/

It supports:
- User authentication
- Meeting creation and audio upload
- Asynchronous processing with Celery + Redis
- Transcript + summary generation
- Structured insights (key points, decisions, action items, risks)
- Speaker timeline segments
- Task execution workflow (create, import, update, delete follow-up tasks)

## Tech Stack

- Backend: FastAPI, SQLAlchemy, Alembic
- Database: PostgreSQL
- Queue: Celery + Redis
- Frontend: Vanilla JS + static assets served by FastAPI
- Optional AI provider: OpenAI

## Repository Structure

```text
backend/
  app/
    core/        # config, db, auth
    models/      # SQLAlchemy models
    schemas/     # Pydantic schemas
    services/    # processing logic
    worker/      # Celery app + tasks
  alembic/       # DB migrations
frontend/        # static UI at /app
docker-compose.yml
docker-compose.prod.yml
alembic.ini
```

## Local Development

### Prerequisites

- Python 3.11+
- Docker Desktop (or Docker Engine + Compose)

### 1) Setup

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Git Bash:

```bash
source .venv/Scripts/activate
```

Install dependencies:

```bash
pip install --upgrade pip
pip install -r backend/requirements.txt
```

Create local env file:

```bash
cp backend/.env.example backend/.env
```

### 2) Start dependencies + migrate DB

```bash
docker compose up -d db redis
python -m alembic upgrade head
```

### 3) Run app services

Terminal 1 (API):

```bash
uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8010
```

Terminal 2 (Worker):

```bash
celery -A backend.app.worker.celery_app.celery_app worker --pool=solo --loglevel=info
```

### 4) Open app

- UI: `http://127.0.0.1:8010/app/`
- API docs: `http://127.0.0.1:8010/docs`

## Production Deployment (Docker Compose)

### 1) Prepare environment file

```bash
cp .env.production.example .env.production
```

Edit `.env.production` and set at least:
- `POSTGRES_PASSWORD`
- `SECRET_KEY`
- `OPENAI_API_KEY` (if using `PROCESSING_PROVIDER=openai`)

### 2) Start production stack

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build
docker compose --env-file .env.production -f docker-compose.prod.yml ps
```

Default URLs:
- UI: `http://<server-ip>:8010/app/`
- API docs: `http://<server-ip>:8010/docs`

Useful commands:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml logs -f api
docker compose --env-file .env.production -f docker-compose.prod.yml logs -f worker
docker compose --env-file .env.production -f docker-compose.prod.yml exec api alembic upgrade head
docker compose --env-file .env.production -f docker-compose.prod.yml restart api worker
```

## Free Deployment (Render)

This project can run on Render free tier (HTTPS included).

### 1) Create Web Service from GitHub repo

- Runtime: `Python`
- Build command:

```bash
pip install -r backend/requirements.txt
```

- Start command:

```bash
python -m alembic upgrade head && uvicorn backend.app.main:app --host 0.0.0.0 --port $PORT
```

You can also use the provided `render.yaml` blueprint.

### 2) Set required environment variables in Render

- `DATABASE_URL` (required for persistent DB, e.g. Neon PostgreSQL URL)
- `SECRET_KEY` (strong random string)
- `PROCESSING_PROVIDER=placeholder`
- `PROCESS_SYNC_WHEN_PROVIDER_PLACEHOLDER=true`
- `CELERY_FALLBACK_TO_INLINE=true`

Optional:
- `OPENAI_API_KEY` (if `PROCESSING_PROVIDER=openai`)

### 3) Open your live app

- `https://<your-render-service>.onrender.com/app/`
- `https://<your-render-service>.onrender.com/docs`

## Processing Modes

- `placeholder`: local mock output, no external AI required
- `openai`: real transcription + structured summary

Set in env:

```env
PROCESSING_PROVIDER=placeholder
```

or

```env
PROCESSING_PROVIDER=openai
OPENAI_API_KEY=your_key
```

## API Overview

Authentication:
- `POST /auth/register`
- `POST /auth/login`
- `GET /me`

Meetings:
- `POST /meetings`
- `GET /meetings`
- `GET /meetings/{meeting_id}`
- `POST /meetings/{meeting_id}/upload`
- `POST /meetings/{meeting_id}/process`
- `GET /meetings/{meeting_id}/download`

Tasks:
- `GET /meetings/{meeting_id}/tasks`
- `POST /meetings/{meeting_id}/tasks`
- `PATCH /meetings/{meeting_id}/tasks/{task_id}`
- `DELETE /meetings/{meeting_id}/tasks/{task_id}`
- `POST /meetings/{meeting_id}/tasks/import-action-items`

## Testing

```bash
python -m pytest -q
```

## Troubleshooting

- DB schema errors (`UndefinedColumn`):
  - run `python -m alembic upgrade head`
- Processing stuck:
  - check `redis` and `worker` are running
- OpenAI errors:
  - verify `OPENAI_API_KEY` and provider env settings
- Render startup error: `DATABASE_URL Field required`:
  - set `DATABASE_URL` in Render service environment variables

## Production Notes

- Use strong secrets in production.
- Put Nginx/Caddy in front of the app for HTTPS.
- Keep PostgreSQL/Redis ports private (not publicly exposed).
