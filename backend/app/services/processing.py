from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any
import logging
import json
import re
import mimetypes
import wave

from backend.app.core.config import settings

logger = logging.getLogger(__name__)


def _detect_duration_seconds(path: Path) -> float | None:
    """Return WAV duration if possible, otherwise None."""
    try:
        with wave.open(str(path), "rb") as wav_file:
            frame_count = wav_file.getnframes()
            frame_rate = wav_file.getframerate()
            if frame_rate <= 0:
                return None
            return frame_count / float(frame_rate)
    except (wave.Error, OSError, EOFError):
        return None


def _read_file_metadata(path: Path) -> dict[str, Any]:
    stat = path.stat()
    mime_type, _ = mimetypes.guess_type(path.name)
    return {
        "file_size_bytes": stat.st_size,
        "mime_type": mime_type,
        "duration_seconds": _detect_duration_seconds(path),
    }


def _build_placeholder_result(
    meeting_title: str,
    path: Path,
    original_filename: str | None,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    size_bytes = metadata["file_size_bytes"]
    mime_type = metadata["mime_type"]
    duration_seconds = metadata["duration_seconds"]

    checksum = sha256(path.read_bytes()).hexdigest()[:16]
    duration_text = (
        f"{duration_seconds:.1f} seconds"
        if duration_seconds is not None
        else "duration unavailable (non-WAV or invalid audio header)"
    )
    filename_text = original_filename or path.name

    transcript = (
        f"Meeting transcript (generated placeholder)\n\n"
        f"Title: {meeting_title}\n"
        f"Source file: {filename_text}\n"
        f"Stored path: {path.as_posix()}\n"
        f"MIME type: {mime_type or 'unknown'}\n"
        f"File size: {size_bytes} bytes\n"
        f"Estimated duration: {duration_text}\n"
        f"Checksum (sha256, short): {checksum}\n\n"
        f"Transcript placeholder:\n"
        f"- Speaker 1: Opened the meeting and aligned on agenda.\n"
        f"- Speaker 2: Shared updates, blockers, and decisions.\n"
        f"- Team: Agreed to follow up with tasks and due dates.\n"
    )

    summary = (
        f"Summary for '{meeting_title}': "
        f"Audio file '{filename_text}' was uploaded and processed on "
        f"{datetime.now(timezone.utc).isoformat()}. "
        f"This MVP generates placeholder transcript/summary content and records file metadata "
        f"(size={size_bytes} bytes, mime={mime_type or 'unknown'}, checksum={checksum})."
    )
    key_points = [
        "Agenda alignment and meeting kickoff were completed.",
        "Status updates and blockers were discussed by participants.",
        "Follow-up tasks and ownership expectations were acknowledged.",
    ]
    decisions = [
        "Team will proceed with current plan and track blockers in follow-up notes.",
    ]
    action_items = [
        {"task": "Document discussed blockers and owners", "owner": "Project lead", "due_date": None},
        {"task": "Share meeting recap with stakeholders", "owner": "Meeting organizer", "due_date": None},
    ]
    risks = [
        "Some blockers may delay delivery if not resolved in follow-up.",
    ]
    effective_duration = max(duration_seconds or 90.0, 30.0)
    segment_window = effective_duration / 3.0
    transcript_segments = [
        {
            "start_seconds": 0.0,
            "end_seconds": round(segment_window, 2),
            "speaker": "Speaker 1",
            "text": "Opened the meeting and aligned on the agenda.",
        },
        {
            "start_seconds": round(segment_window, 2),
            "end_seconds": round(segment_window * 2.0, 2),
            "speaker": "Speaker 2",
            "text": "Shared status updates and current blockers.",
        },
        {
            "start_seconds": round(segment_window * 2.0, 2),
            "end_seconds": round(effective_duration, 2),
            "speaker": "Team",
            "text": "Agreed on follow-up tasks and ownership.",
        },
    ]

    return {
        "transcript": transcript,
        "summary": summary,
        "transcript_segments": transcript_segments,
        "key_points": key_points,
        "decisions": decisions,
        "action_items": action_items,
        "risks": risks,
        "mime_type": mime_type,
        "file_size_bytes": size_bytes,
        "processed_at": datetime.now(timezone.utc),
        "duration_seconds": duration_seconds,
    }


def _coerce_transcription_text(response: Any) -> str:
    if response is None:
        return ""
    if isinstance(response, str):
        return response

    text = getattr(response, "text", None)
    if isinstance(text, str):
        return text

    if isinstance(response, dict):
        value = response.get("text")
        if isinstance(value, str):
            return value

    return str(response)


def _coerce_summary_text(response: Any) -> str:
    if response is None:
        return ""

    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    try:
        choices = getattr(response, "choices", None)
        if choices:
            message = choices[0].message
            content = getattr(message, "content", None)
            if isinstance(content, str):
                return content.strip()
            if isinstance(content, list):
                parts: list[str] = []
                for item in content:
                    part_text = getattr(item, "text", None)
                    if isinstance(part_text, str):
                        parts.append(part_text)
                    elif isinstance(item, dict) and isinstance(item.get("text"), str):
                        parts.append(item["text"])
                if parts:
                    return "\n".join(parts).strip()
    except Exception:
        logger.exception("Unable to parse summary response payload")

    if isinstance(response, str):
        return response.strip()
    if isinstance(response, dict):
        for key in ("summary", "text", "output_text"):
            value = response.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

    return str(response).strip()


def _build_summary_prompt(meeting_title: str, transcript: str) -> str:
    transcript_limit = max(500, settings.OPENAI_SUMMARY_TRANSCRIPT_CHAR_LIMIT)
    clipped = transcript[:transcript_limit]
    if len(transcript) > transcript_limit:
        clipped += "\n\n[Transcript truncated for summarization.]"

    return (
        f"Meeting title: {meeting_title}\n\n"
        "Return ONLY valid JSON with this exact structure:\n"
        "{\n"
        '  "summary": "string",\n'
        '  "key_points": ["string"],\n'
        '  "decisions": ["string"],\n'
        '  "action_items": [{"task":"string","owner":"string|null","due_date":"string|null"}],\n'
        '  "risks": ["string"]\n'
        "}\n\n"
        "Rules:\n"
        "- Keep summary concise and factual.\n"
        "- If no decision/action/risk exists, return an empty list for that field.\n"
        "- Do not return markdown or code fences.\n\n"
        "Transcript:\n"
        f"{clipped}"
    )


def _coerce_json_payload(text: str) -> dict[str, Any] | None:
    candidate = text.strip()
    if not candidate:
        return None

    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if len(lines) >= 3:
            candidate = "\n".join(lines[1:-1]).strip()

    def _try_parse(value: str) -> dict[str, Any] | None:
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    parsed = _try_parse(candidate)
    if parsed is not None:
        return parsed

    start = candidate.find("{")
    end = candidate.rfind("}")
    if start >= 0 and end > start:
        parsed = _try_parse(candidate[start : end + 1])
        if parsed is not None:
            return parsed

    return None


def _normalize_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if isinstance(item, str):
            text = item.strip()
            if text:
                result.append(text)
    return result


def _normalize_action_items(value: Any) -> list[dict[str, str | None]]:
    if not isinstance(value, list):
        return []
    items: list[dict[str, str | None]] = []
    for row in value:
        if not isinstance(row, dict):
            continue
        task = row.get("task")
        if not isinstance(task, str) or not task.strip():
            continue
        owner = row.get("owner")
        due_date = row.get("due_date")
        items.append(
            {
                "task": task.strip(),
                "owner": owner.strip() if isinstance(owner, str) and owner.strip() else None,
                "due_date": due_date.strip() if isinstance(due_date, str) and due_date.strip() else None,
            }
        )
    return items


def _coerce_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_speaker_prefix(text: str) -> tuple[str | None, str]:
    match = re.match(r"^\s*([A-Za-z][\w ]{0,30})\s*:\s*(.+)$", text)
    if not match:
        return None, text.strip()
    speaker = match.group(1).strip()
    body = match.group(2).strip()
    if not body:
        return None, text.strip()
    return speaker, body


def _normalize_transcript_segments(
    value: Any,
    fallback_transcript: str,
    duration_seconds: float | None,
) -> list[dict[str, Any]]:
    rows = value if isinstance(value, list) else []
    segments: list[dict[str, Any]] = []
    previous_end = 0.0

    for row in rows:
        if isinstance(row, dict):
            row_data = row
        else:
            row_data = {
                "text": getattr(row, "text", None),
                "start": getattr(row, "start", None),
                "end": getattr(row, "end", None),
                "speaker": getattr(row, "speaker", None),
            }

        raw_text = row_data.get("text")
        if not isinstance(raw_text, str) or not raw_text.strip():
            continue
        speaker_hint, normalized_text = _extract_speaker_prefix(raw_text.strip())
        if not normalized_text:
            continue

        start_value = _coerce_float(
            row_data.get("start_seconds", row_data.get("start_time", row_data.get("start")))
        )
        end_value = _coerce_float(
            row_data.get("end_seconds", row_data.get("end_time", row_data.get("end")))
        )
        start_seconds = start_value if start_value is not None else previous_end
        if start_seconds < 0:
            start_seconds = 0.0

        if end_value is None or end_value <= start_seconds:
            end_seconds = start_seconds + 1.0
        else:
            end_seconds = end_value

        speaker = row_data.get("speaker")
        if not isinstance(speaker, str) or not speaker.strip():
            speaker = speaker_hint or "Speaker 1"

        segments.append(
            {
                "start_seconds": round(start_seconds, 2),
                "end_seconds": round(end_seconds, 2),
                "speaker": speaker.strip(),
                "text": normalized_text,
            }
        )
        previous_end = end_seconds

    if segments:
        return segments

    transcript_text = fallback_transcript.strip()
    if not transcript_text:
        return []

    end_seconds = duration_seconds if duration_seconds and duration_seconds > 0 else 1.0
    return [
        {
            "start_seconds": 0.0,
            "end_seconds": round(float(end_seconds), 2),
            "speaker": "Speaker 1",
            "text": transcript_text,
        }
    ]


def _extract_transcript_segments(
    transcription_response: Any,
    transcript_text: str,
    duration_seconds: float | None,
) -> list[dict[str, Any]]:
    raw_segments: Any = None
    if isinstance(transcription_response, dict):
        raw_segments = transcription_response.get("segments")
    if raw_segments is None:
        raw_segments = getattr(transcription_response, "segments", None)

    normalized = _normalize_transcript_segments(raw_segments, transcript_text, duration_seconds)
    if normalized:
        return normalized
    return _normalize_transcript_segments([], transcript_text, duration_seconds)


def _extract_structured_insights(summary_text: str, meeting_title: str) -> dict[str, Any]:
    parsed = _coerce_json_payload(summary_text) or {}
    summary = parsed.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        summary = (
            f"Summary for '{meeting_title}': structured extraction fallback was used because "
            "JSON output was incomplete."
        )

    return {
        "summary": summary.strip(),
        "key_points": _normalize_string_list(parsed.get("key_points")),
        "decisions": _normalize_string_list(parsed.get("decisions")),
        "action_items": _normalize_action_items(parsed.get("action_items")),
        "risks": _normalize_string_list(parsed.get("risks")),
    }


def _build_openai_result(
    meeting_title: str,
    path: Path,
    original_filename: str | None,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    if not settings.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is required when PROCESSING_PROVIDER=openai")

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("OpenAI SDK is not installed. Install the `openai` package to use PROCESSING_PROVIDER=openai") from exc

    client_kwargs: dict[str, Any] = {"api_key": settings.OPENAI_API_KEY}
    if settings.OPENAI_BASE_URL:
        client_kwargs["base_url"] = settings.OPENAI_BASE_URL
    client = OpenAI(**client_kwargs)

    with path.open("rb") as audio_file:
        transcript_response = client.audio.transcriptions.create(
            model=settings.OPENAI_TRANSCRIPTION_MODEL,
            file=audio_file,
            response_format="verbose_json",
            timestamp_granularities=["segment"],
        )

    transcript = _coerce_transcription_text(transcript_response).strip()
    if not transcript:
        raise RuntimeError("Transcription completed but returned empty text")
    transcript_segments = _extract_transcript_segments(
        transcript_response,
        transcript,
        metadata["duration_seconds"],
    )

    summary_prompt = _build_summary_prompt(meeting_title, transcript)
    summary_response = client.chat.completions.create(
        model=settings.OPENAI_SUMMARY_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You summarize meeting transcripts for internal teams. "
                    "Be accurate, structured, and concise."
                ),
            },
            {"role": "user", "content": summary_prompt},
        ],
        temperature=0.2,
    )
    summary = _coerce_summary_text(summary_response)
    insights = _extract_structured_insights(summary, meeting_title)

    return {
        "transcript": transcript,
        "summary": insights["summary"],
        "transcript_segments": transcript_segments,
        "key_points": insights["key_points"],
        "decisions": insights["decisions"],
        "action_items": insights["action_items"],
        "risks": insights["risks"],
        "mime_type": metadata["mime_type"],
        "file_size_bytes": metadata["file_size_bytes"],
        "processed_at": datetime.now(timezone.utc),
        "duration_seconds": metadata["duration_seconds"],
        "original_filename": original_filename or path.name,
    }


def build_meeting_notes(meeting_title: str, file_path: str, original_filename: str | None = None) -> dict[str, Any]:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Uploaded file not found: {path}")

    metadata = _read_file_metadata(path)
    provider = settings.PROCESSING_PROVIDER.strip().lower()
    if not provider:
        provider = "placeholder"

    if provider == "placeholder":
        return _build_placeholder_result(meeting_title, path, original_filename, metadata)

    if provider == "openai":
        try:
            return _build_openai_result(meeting_title, path, original_filename, metadata)
        except Exception:
            if not settings.PROCESSING_FALLBACK_TO_PLACEHOLDER:
                raise
            logger.exception("OpenAI processing failed. Falling back to placeholder output.")
            result = _build_placeholder_result(meeting_title, path, original_filename, metadata)
            fallback_note = (
                "OpenAI processing failed and placeholder output was generated instead. "
                "Check backend logs for the original error."
            )
            result["summary"] = f"{result['summary']}\n\nFallback note: {fallback_note}"
            return result

    raise ValueError(
        f"Unsupported PROCESSING_PROVIDER '{settings.PROCESSING_PROVIDER}'. "
        "Expected 'placeholder' or 'openai'."
    )
