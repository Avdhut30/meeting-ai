from pydantic_settings import BaseSettings, SettingsConfigDict


def _normalize_database_url(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if cleaned.startswith("postgres://"):
        return "postgresql+psycopg2://" + cleaned[len("postgres://") :]
    return cleaned


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="backend/.env", extra="ignore")

    DATABASE_URL: str | None = None
    RENDER_DATABASE_URL: str | None = None
    INTERNAL_DATABASE_URL: str | None = None
    POSTGRES_URL: str | None = None
    UPLOADS_DIR: str = "backend/uploads"
    SECRET_KEY: str = "change-this-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    PROCESSING_PROVIDER: str = "placeholder"  # placeholder | openai
    PROCESSING_FALLBACK_TO_PLACEHOLDER: bool = True
    OPENAI_API_KEY: str | None = None
    OPENAI_BASE_URL: str | None = None
    OPENAI_TRANSCRIPTION_MODEL: str = "whisper-1"
    OPENAI_SUMMARY_MODEL: str = "gpt-4o-mini"
    OPENAI_SUMMARY_TRANSCRIPT_CHAR_LIMIT: int = 12000
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"
    CELERY_TASK_ALWAYS_EAGER: bool = False
    CELERY_TASK_EAGER_PROPAGATES: bool = False
    CELERY_TASK_SOFT_TIME_LIMIT_SECONDS: int = 300
    CELERY_TASK_TIME_LIMIT_SECONDS: int = 600
    CELERY_FALLBACK_TO_INLINE: bool = True
    PROCESS_SYNC_WHEN_PROVIDER_PLACEHOLDER: bool = True
    UPLOAD_MAX_SIZE_BYTES: int = 25 * 1024 * 1024
    UPLOAD_ALLOWED_EXTENSIONS: str = ".wav,.mp3,.m4a,.mp4,.mpeg,.mpga,.webm,.ogg"
    UPLOAD_ALLOWED_MIME_TYPES: str = (
        "audio/wav,audio/x-wav,audio/wave,audio/mpeg,audio/mp3,"
        "audio/mp4,audio/x-m4a,audio/m4a,audio/webm,audio/ogg,application/ogg,video/mp4"
    )

    @property
    def upload_allowed_extensions_set(self) -> set[str]:
        return {
            ext.strip().lower()
            for ext in self.UPLOAD_ALLOWED_EXTENSIONS.split(",")
            if ext.strip()
        }

    @property
    def upload_allowed_mime_types_set(self) -> set[str]:
        return {
            mime_type.strip().lower()
            for mime_type in self.UPLOAD_ALLOWED_MIME_TYPES.split(",")
            if mime_type.strip()
        }

    @property
    def resolved_database_url(self) -> str:
        for candidate in (
            self.DATABASE_URL,
            self.RENDER_DATABASE_URL,
            self.INTERNAL_DATABASE_URL,
            self.POSTGRES_URL,
        ):
            normalized = _normalize_database_url(candidate)
            if normalized is not None:
                return normalized

        # Render-safe fallback for first deploy demos.
        # For production durability, explicitly set DATABASE_URL.
        return "sqlite:///./backend/local.db"

settings = Settings()
