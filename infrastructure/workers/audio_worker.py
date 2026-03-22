from __future__ import annotations

import asyncio
import os
import threading
import wave
from datetime import datetime
from pathlib import Path
from typing import BinaryIO, Callable
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
        self._lock = threading.Lock()
        self._last_runtime_error: str | None = None

        # Streaming to disk to reduce RAM usage
        self._temp_raw_path: Path | None = None
        self._temp_file: BinaryIO | None = None
        self._chunk_sizes: list[int] = []

    def start(self, device: int | None = None) -> None:
        self._stop_event.clear()
        self._last_runtime_error = None
        with self._lock:
            self._cleanup_temp_files()

            LIVE_CHUNKS_DIR.mkdir(parents=True, exist_ok=True)
            self._temp_raw_path = LIVE_CHUNKS_DIR / f'session_{uuid4().hex}.raw'
            self._temp_file = open(self._temp_raw_path, 'wb+')
            self._chunk_sizes = []

        self._thread = threading.Thread(
            target=self._run,
            args=(device,),
            daemon=True,
            name='audio-worker',
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
            self._cleanup_temp_files()

    def set_muted(self, muted: bool) -> None:
        self._muted = muted

    def ignore_last_chunk(self) -> None:
        with self._lock:
            if self._chunk_sizes and self._temp_file:
                size = self._chunk_sizes.pop()
                self._temp_file.seek(0, os.SEEK_END)
                current_pos = self._temp_file.tell()
                new_pos = max(0, current_pos - size)
                self._temp_file.truncate(new_pos)
                self._temp_file.seek(0, os.SEEK_END)

    def _cleanup_temp_files(self) -> None:
        if self._temp_file:
            try:
                self._temp_file.close()
            except Exception:
                pass
            self._temp_file = None

        if self._temp_raw_path and self._temp_raw_path.exists():
            try:
                self._temp_raw_path.unlink()
            except Exception:
                pass
            self._temp_raw_path = None

        self._chunk_sizes = []

    def _append_chunk_to_temp(self, audio: np.ndarray) -> None:
        if self._temp_file is None:
            return

        # PCM 16-bit (matches _write_wav)
        data = (audio.flatten() * 32767).astype(np.int16).tobytes()
        self._temp_file.write(data)
        self._temp_file.flush()
        self._chunk_sizes.append(len(data))

    def _run(self, device: int | None) -> None:
        while not self._stop_event.is_set():
            frame_count = int(LIVE_TRANSCRIPTION_CHUNK_SECONDS * AUDIO_SAMPLE_RATE)
            audio = sd.rec(
                frame_count,
                samplerate=AUDIO_SAMPLE_RATE,
                channels=1,
                dtype='float32',
                device=device,
            )
            sd.wait()

            with self._lock:
                self._append_chunk_to_temp(audio)

            if self._stop_event.is_set():
                break

            if self._muted:
                continue

            chunk_path = None
            try:
                chunk_path = self._save_chunk_wav(audio)
                future = asyncio.run_coroutine_threadsafe(
                    self._enqueue_and_get(to_project_path(chunk_path)),
                    self._async_loop,
                )
                text = future.result(timeout=60)
                if text:
                    self._last_runtime_error = None
                    self._on_live_text(text)
            except Exception as exc:
                self._emit_runtime_error(
                    f'Transcricao ao vivo indisponivel. Detalhe: {exc}'
                )
            finally:
                if chunk_path:
                    try:
                        chunk_path.unlink(missing_ok=True)
                    except Exception:
                        pass

    async def _enqueue_and_get(self, wav_path: str) -> str:
        pool = await create_pool(REDIS_SETTINGS)
        try:
            job = await pool.enqueue_job('transcribe_chunk', wav_path)
            if job is None:
                return ''
            result = await job.result(timeout=60)
            return result or ''
        finally:
            await pool.aclose()

    def _save_chunk_wav(self, audio: np.ndarray) -> Path:
        LIVE_CHUNKS_DIR.mkdir(parents=True, exist_ok=True)
        chunk_path = LIVE_CHUNKS_DIR / f'chunk_{uuid4().hex}.wav'
        _write_wav(audio, chunk_path)
        return chunk_path

    def _save_full_wav(self) -> tuple[str, float]:
        with self._lock:
            if self._temp_file:
                try:
                    self._temp_file.close()
                except Exception:
                    pass
                self._temp_file = None

            temp_path = self._temp_raw_path
            self._temp_raw_path = None
            self._chunk_sizes = []

        if not temp_path or not temp_path.exists():
            return '', 0.0

        try:
            file_size = temp_path.stat().st_size
            total_samples = file_size // 2  # int16 = 2 bytes
            duration = total_samples / AUDIO_SAMPLE_RATE

            validate_meeting_duration(duration)

            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            wav_path = OUTPUT_DIR / f'reuniao_{timestamp}.wav'

            with wave.open(str(wav_path).encode('utf-8'), 'wb') as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(AUDIO_SAMPLE_RATE)

                with open(temp_path, 'rb') as raw_file:
                    while True:
                        data = raw_file.read(64 * 1024)
                        if not data:
                            break
                        wav_file.writeframes(data)

            return str(wav_path), duration
        finally:
            if temp_path and temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass

    def _emit_runtime_error(self, message: str) -> None:
        if self._on_error is None or message == self._last_runtime_error:
            return
        self._last_runtime_error = message
        self._on_error(message)


def _write_wav(audio: np.ndarray, path: Path) -> None:
    # Usar bytes em vez de string para evitar problemas de encoding no Windows
    with wave.open(str(path).encode('utf-8'), 'wb') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(AUDIO_SAMPLE_RATE)
        wav_file.writeframes((audio.flatten() * 32767).astype(np.int16).tobytes())
