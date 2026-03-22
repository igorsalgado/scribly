from __future__ import annotations

import asyncio
import os
import subprocess
import threading
from concurrent.futures import Future
from typing import Any, Callable, TYPE_CHECKING

from arq import create_pool

from application.meeting_markdown import get_meeting_markdown_path
from application.system_health import HealthReport, collect_health_report
from infrastructure.audio.recorder import list_input_devices
from infrastructure.workers.audio_worker import AudioWorker
from settings import (
    REDIS_PROGRESS_CHANNEL,
    REDIS_SETTINGS,
    REDIS_URL,
    create_repository,
    to_project_path,
)

if TYPE_CHECKING:
    from domain.meeting import Meeting

class ScriblyApplicationService:
    def __init__(self, async_loop: asyncio.AbstractEventLoop) -> None:
        self._async_loop = async_loop
        self._repository = create_repository()
        self._audio_worker: AudioWorker | None = None
        self._closing = False

    def get_history(self) -> list[Meeting]:
        return self._repository.find_all()

    def list_devices(self) -> list[dict]:
        return list_input_devices()

    def collect_health(self) -> HealthReport:
        return collect_health_report()

    def start_recording(
        self, 
        device_index: int, 
        on_live_text: Callable[[str], None], 
        on_error: Callable[[str], None]
    ) -> None:
        self._audio_worker = AudioWorker(
            async_loop=self._async_loop,
            on_live_text=on_live_text,
            on_error=on_error,
        )
        self._audio_worker.start(device=device_index)

    def stop_recording(self) -> Future[tuple[str, float]]:
        if self._audio_worker is None:
            raise RuntimeError("Nenhuma gravacao em curso.")
        
        worker = self._audio_worker
        self._audio_worker = None
        
        future: Future[tuple[str, float]] = Future()
        
        def _finalize() -> None:
            try:
                result = worker.stop()
                future.set_result(result)
            except Exception as exc:
                future.set_exception(exc)
        
        threading.Thread(target=_finalize, daemon=True, name="finalize-worker").start()
        return future

    def abort_recording(self) -> None:
        if self._audio_worker:
            self._audio_worker.abort()
            self._audio_worker = None

    def set_muted(self, muted: bool) -> None:
        if self._audio_worker:
            self._audio_worker.set_muted(muted)

    def ignore_last_chunk(self) -> None:
        if self._audio_worker:
            self._audio_worker.ignore_last_chunk()

    async def enqueue_processing(self, wav_path: str, duration: float) -> Any:
        pool = await create_pool(REDIS_SETTINGS)
        try:
            job = await pool.enqueue_job(
                "process_meeting",
                to_project_path(wav_path),
                duration,
            )
            if job is None:
                raise RuntimeError("Worker indisponivel.")
            return await job.result(timeout=3600)
        finally:
            await pool.aclose()

    async def subscribe_progress(self, callback: Callable[[str], None]) -> None:
        import redis.asyncio as aioredis
        from contextlib import suppress
        
        client = None
        pubsub = None
        try:
            client = aioredis.from_url(REDIS_URL)
            pubsub = client.pubsub()
            await pubsub.subscribe(REDIS_PROGRESS_CHANNEL)
            async for message in pubsub.listen():
                if self._closing:
                    break
                if message["type"] != "message":
                    continue
                stage = message["data"]
                if isinstance(stage, bytes):
                    stage = stage.decode()
                callback(stage)
        except asyncio.CancelledError:
            pass
        finally:
            if pubsub is not None:
                with suppress(Exception):
                    await pubsub.unsubscribe(REDIS_PROGRESS_CHANNEL)
                with suppress(Exception):
                    await pubsub.aclose()
            if client is not None:
                with suppress(Exception):
                    await client.aclose(close_connection_pool=True)

    def open_meeting_markdown(self, meeting: Meeting) -> bool:
        markdown_path = get_meeting_markdown_path(meeting)
        if not markdown_path.exists():
            return False
        
        if hasattr(os, "startfile"):
            os.startfile(str(markdown_path))
        else:
            subprocess.Popen(["xdg-open", str(markdown_path)])
        return True

    def shutdown(self) -> None:
        self._closing = True
        if self._audio_worker:
            self._audio_worker.abort()
