from __future__ import annotations

import asyncio
import threading
import wave
from datetime import datetime
from pathlib import Path
from typing import Callable
from uuid import uuid4

import numpy as np
import sounddevice as sd
from arq import create_pool

from application.audio_policy import validate_meeting_duration
from settings import (
    AUDIO_SAMPLE_RATE,
    LIVE_CHUNKS_DIR,
    LIVE_TRANSCRIPTION_CHUNK_SECONDS,
    OUTPUT_DIR,
    REDIS_SETTINGS,
    to_project_path,
)


class AudioWorker:
    def __init__(
        self,
        async_loop: asyncio.AbstractEventLoop,
        on_live_text: Callable[[str], None],
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        self._async_loop = async_loop
        self._on_live_text = on_live_text
        self._on_error = on_error

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._muted = False
        self._chunks: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._last_runtime_error: str | None = None

    def start(self, device: int | None = None) -> None:
        self._stop_event.clear()
        self._chunks = []
        self._last_runtime_error = None
        self._thread = threading.Thread(
            target=self._run,
            args=(device,),
            daemon=True,
            name="audio-worker",
        )
        self._thread.start()

    def stop(self) -> tuple[str, float]:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=LIVE_TRANSCRIPTION_CHUNK_SECONDS + 2)
        return self._save_full_wav()

    def abort(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=LIVE_TRANSCRIPTION_CHUNK_SECONDS + 2)
        with self._lock:
            self._chunks = []

    def set_muted(self, muted: bool) -> None:
        self._muted = muted

    def ignore_last_chunk(self) -> None:
        with self._lock:
            if self._chunks:
                self._chunks.pop()

    def _run(self, device: int | None) -> None:
        while not self._stop_event.is_set():
            frame_count = int(LIVE_TRANSCRIPTION_CHUNK_SECONDS * AUDIO_SAMPLE_RATE)
            audio = sd.rec(
                frame_count,
                samplerate=AUDIO_SAMPLE_RATE,
                channels=1,
                dtype="float32",
                device=device,
            )
            sd.wait()

            if self._stop_event.is_set():
                with self._lock:
                    self._chunks.append(audio)
                break

            with self._lock:
                self._chunks.append(audio)

            if self._muted:
                continue

            chunk_path = self._save_chunk_wav(audio)
            future = asyncio.run_coroutine_threadsafe(
                self._enqueue_and_get(to_project_path(chunk_path)),
                self._async_loop,
            )
            try:
                text = future.result(timeout=60)
                if text:
                    self._last_runtime_error = None
                    self._on_live_text(text)
            except Exception as exc:
                self._emit_runtime_error(
                    f"Transcricao ao vivo indisponivel. Detalhe: {exc}"
                )
            finally:
                chunk_path.unlink(missing_ok=True)

    async def _enqueue_and_get(self, wav_path: str) -> str:
        pool = await create_pool(REDIS_SETTINGS)
        try:
            job = await pool.enqueue_job("transcribe_chunk", wav_path)
            if job is None:
                return ""
            result = await job.result(timeout=60)
            return result or ""
        finally:
            await pool.aclose()

    def _save_chunk_wav(self, audio: np.ndarray) -> Path:
        LIVE_CHUNKS_DIR.mkdir(parents=True, exist_ok=True)
        chunk_path = LIVE_CHUNKS_DIR / f"chunk_{uuid4().hex}.wav"
        _write_wav(audio, chunk_path)
        return chunk_path

    def _save_full_wav(self) -> tuple[str, float]:
        with self._lock:
            chunks = list(self._chunks)

        if chunks:
            full_audio = np.concatenate(chunks, axis=0)
        else:
            full_audio = np.empty((0, 1), dtype="float32")

        duration = len(full_audio) / AUDIO_SAMPLE_RATE
        validate_meeting_duration(duration)

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        wav_path = OUTPUT_DIR / f"reuniao_{timestamp}.wav"
        _write_wav(full_audio, wav_path)
        return str(wav_path), duration

    def _emit_runtime_error(self, message: str) -> None:
        if self._on_error is None or message == self._last_runtime_error:
            return
        self._last_runtime_error = message
        self._on_error(message)


def _write_wav(audio: np.ndarray, path: Path) -> None:
    # Usar bytes em vez de string para evitar problemas de encoding no Windows
    with wave.open(str(path).encode("utf-8"), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(AUDIO_SAMPLE_RATE)
        wav_file.writeframes((audio.flatten() * 32767).astype(np.int16).tobytes())
