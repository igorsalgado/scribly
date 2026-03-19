import asyncio
import os
from pathlib import Path

from arq.connections import RedisSettings
from dotenv import load_dotenv

load_dotenv()

REDIS_PROGRESS_CHANNEL = "scribly:progress"


async def startup(ctx: dict) -> None:
    from infrastructure.diarization.pyannote import PyannoteDiarizer
    from infrastructure.extraction.ollama import OllamaExtractor
    from infrastructure.persistence.sqlite_repository import SQLiteMeetingRepository
    from infrastructure.transcription.whisper import WhisperTranscriber
    from application.pipeline import (
        DiarizationHandler,
        ExtractionHandler,
        TranscriptionHandler,
    )

    hf_token = os.getenv("HF_TOKEN", "")
    whisper_model = os.getenv("WHISPER_MODEL", "medium")
    ollama_model = os.getenv("OLLAMA_MODEL", "mistral")
    ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434")

    whisper = WhisperTranscriber(model_size=whisper_model)

    pyannote = PyannoteDiarizer(hf_token=hf_token)

    ollama = OllamaExtractor(model=ollama_model, url=ollama_url)

    head = TranscriptionHandler(whisper)
    head.set_next(DiarizationHandler(pyannote)).set_next(ExtractionHandler(ollama))

    repository = SQLiteMeetingRepository(db_path=Path("scribly.db"))

    ctx["whisper"] = whisper
    ctx["pipeline"] = head
    ctx["repository"] = repository
    ctx["async_loop"] = asyncio.get_event_loop()


async def shutdown(ctx: dict) -> None:
    pass


async def transcribe_chunk(ctx: dict, wav_path: str) -> str:
    loop = asyncio.get_event_loop()
    whisper = ctx["whisper"]

    def _transcribe() -> str:
        return whisper.transcribe_quick(Path(wav_path))

    text: str = await loop.run_in_executor(None, _transcribe)
    return text


async def process_meeting(ctx: dict, wav_path: str, duration: float) -> str:
    from application.pipeline import ProcessingContext
    from domain.meeting import Meeting

    loop = asyncio.get_event_loop()
    pipeline = ctx["pipeline"]
    repository = ctx["repository"]
    redis = ctx["redis"]

    async def _publish(stage: str) -> None:
        await redis.publish(REDIS_PROGRESS_CHANNEL, stage)

    def _on_progress(stage: str) -> None:
        asyncio.run_coroutine_threadsafe(_publish(stage), loop)

    def _run_pipeline() -> ProcessingContext:
        from datetime import datetime

        context = ProcessingContext(
            wav_path=Path(wav_path),
            date=datetime.now().strftime("%Y-%m-%d"),
            on_progress=_on_progress,
        )
        pipeline.handle(context)
        return context

    context: ProcessingContext = await loop.run_in_executor(None, _run_pipeline)

    meeting = Meeting.create(audio_path=wav_path, duration_seconds=duration)
    meeting.transcript = context.transcript
    meeting.business_rules = context.business_rules

    if context.transcript:
        from domain.meeting import Participant

        seen: list[str] = []
        for seg in context.segments:
            if seg.speaker not in seen:
                seen.append(seg.speaker)
        meeting.participants = [Participant(label=s) for s in seen]

    repository.save(meeting)

    await redis.publish(REDIS_PROGRESS_CHANNEL, "done")

    return str(meeting.id)


class WorkerSettings:
    functions = [transcribe_chunk, process_meeting]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings(
        host=os.getenv("REDIS_HOST", "redis"),
        port=int(os.getenv("REDIS_PORT", "6379")),
    )
