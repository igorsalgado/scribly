from __future__ import annotations

import asyncio
import os
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from arq.connections import RedisSettings
from dotenv import load_dotenv

load_dotenv()

if TYPE_CHECKING:
    from application.pipeline import ProcessingContext
    from infrastructure.transcription.whisper import WhisperTranscriber


APP_NAME = "Scribly"
REDIS_PROGRESS_CHANNEL = os.getenv("REDIS_PROGRESS_CHANNEL", "scribly:progress")

HF_TOKEN = os.getenv("HF_TOKEN", "").strip()
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "medium").strip()
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "mistral").strip()
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")

REDIS_HOST = os.getenv("REDIS_HOST", "localhost").strip()
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_URL = f"redis://{REDIS_HOST}:{REDIS_PORT}"
REDIS_SETTINGS = RedisSettings(host=REDIS_HOST, port=REDIS_PORT)

AUDIO_SAMPLE_RATE = int(os.getenv("AUDIO_SAMPLE_RATE", "16000"))
LIVE_TRANSCRIPTION_CHUNK_SECONDS = int(
    os.getenv("LIVE_TRANSCRIPTION_CHUNK_SECONDS", "5")
)
MEETING_DATE_FORMAT = os.getenv("MEETING_DATE_FORMAT", "%d/%m/%Y %H:%M")

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", BASE_DIR / "output"))
DB_PATH = Path(os.getenv("DB_PATH", BASE_DIR / "data" / "scribly.db"))
LIVE_CHUNKS_DIR = Path(os.getenv("LIVE_CHUNKS_DIR", BASE_DIR / "data" / "live_chunks"))

if not OUTPUT_DIR.is_absolute():
    OUTPUT_DIR = BASE_DIR / OUTPUT_DIR
if not DB_PATH.is_absolute():
    DB_PATH = BASE_DIR / DB_PATH
if not LIVE_CHUNKS_DIR.is_absolute():
    LIVE_CHUNKS_DIR = BASE_DIR / LIVE_CHUNKS_DIR


def ensure_directories() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    LIVE_CHUNKS_DIR.mkdir(parents=True, exist_ok=True)


def to_project_path(path: str | Path) -> str:
    raw_path = str(path)
    if not raw_path:
        return raw_path

    path_obj = Path(raw_path)
    if path_obj.is_absolute():
        candidate = path_obj.resolve()
    else:
        candidate = (BASE_DIR / path_obj).resolve()

    try:
        relative_path = candidate.relative_to(BASE_DIR.resolve())
    except ValueError:
        return raw_path

    return str(PurePosixPath(relative_path.as_posix()))


def resolve_project_path(path: str | Path) -> Path:
    path_obj = Path(str(path))
    if path_obj.is_absolute():
        return path_obj

    normalized = Path(PurePosixPath(str(path)))
    return (BASE_DIR / normalized).resolve()


def create_whisper_transcriber() -> "WhisperTranscriber":
    from infrastructure.transcription.whisper import WhisperTranscriber

    return WhisperTranscriber(model_size=WHISPER_MODEL)


def create_pipeline(whisper: "WhisperTranscriber | None" = None):
    from application.pipeline import (
        DiarizationHandler,
        ExtractionHandler,
        TranscriptionHandler,
    )
    from infrastructure.diarization.pyannote import PyannoteDiarizer
    from infrastructure.extraction.ollama import OllamaExtractor

    whisper = whisper or create_whisper_transcriber()
    pyannote = PyannoteDiarizer(hf_token=HF_TOKEN or None)
    ollama = OllamaExtractor(model=OLLAMA_MODEL, url=OLLAMA_URL)

    head = TranscriptionHandler(whisper)
    head.set_next(DiarizationHandler(pyannote)).set_next(ExtractionHandler(ollama))
    return head


def create_repository():
    from infrastructure.persistence.sqlite_repository import SQLiteMeetingRepository

    ensure_directories()
    return SQLiteMeetingRepository(db_path=DB_PATH)


async def startup(ctx: dict) -> None:
    whisper = create_whisper_transcriber()
    ctx["whisper"] = whisper
    ctx["pipeline"] = create_pipeline(whisper)
    ctx["repository"] = create_repository()


async def shutdown(ctx: dict) -> None:
    return None


async def transcribe_chunk(ctx: dict, wav_path: str) -> str:
    loop = asyncio.get_running_loop()
    whisper = ctx["whisper"]

    def _transcribe() -> str:
        return whisper.transcribe_quick(resolve_project_path(wav_path))

    return await loop.run_in_executor(None, _transcribe)


async def process_meeting(ctx: dict, wav_path: str, duration: float) -> str:
    from datetime import datetime

    from application.meeting_markdown import write_meeting_markdown
    from application.pipeline import ProcessingContext
    from domain.meeting import Meeting, Participant

    loop = asyncio.get_running_loop()
    pipeline = ctx["pipeline"]
    repository = ctx["repository"]
    redis = ctx["redis"]

    async def _publish(stage: str) -> None:
        await redis.publish(REDIS_PROGRESS_CHANNEL, stage)

    def _on_progress(stage: str) -> None:
        asyncio.run_coroutine_threadsafe(_publish(stage), loop)

    def _run_pipeline() -> "ProcessingContext":
        resolved_wav_path = resolve_project_path(wav_path)
        context = ProcessingContext(
            wav_path=resolved_wav_path,
            date=datetime.now().strftime(MEETING_DATE_FORMAT),
            on_progress=_on_progress,
        )
        pipeline.handle(context)
        return context

    context: "ProcessingContext" = await loop.run_in_executor(None, _run_pipeline)

    meeting = Meeting.create(
        audio_path=to_project_path(wav_path),
        duration_seconds=duration,
    )
    meeting.transcript = context.transcript
    meeting.business_rules = context.business_rules

    if context.transcript:
        seen: list[str] = []
        for segment in context.segments:
            if segment.speaker not in seen:
                seen.append(segment.speaker)
        meeting.participants = [Participant(label=label) for label in seen]

    repository.save(meeting)
    write_meeting_markdown(meeting)
    await redis.publish(REDIS_PROGRESS_CHANNEL, "done")
    return str(meeting.id)


class WorkerSettings:
    functions = [transcribe_chunk, process_meeting]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = REDIS_SETTINGS


ensure_directories()
