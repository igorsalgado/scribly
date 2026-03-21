import tempfile
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd

from domain.services import TranscriptionService
from settings import AUDIO_SAMPLE_RATE, LIVE_TRANSCRIPTION_CHUNK_SECONDS


def list_input_devices() -> list[dict]:
    devices = sd.query_devices()
    return [
        {"index": i, "name": dev["name"], "channels": dev["max_input_channels"]}
        for i, dev in enumerate(devices)
        if dev["max_input_channels"] > 0
    ]


class AudioRecorder:
    def __init__(self, transcription_service: TranscriptionService) -> None:
        self._transcription = transcription_service

    def record_chunk(self, device: "int | None" = None) -> np.ndarray:
        audio = sd.rec(
            int(LIVE_TRANSCRIPTION_CHUNK_SECONDS * AUDIO_SAMPLE_RATE),
            samplerate=AUDIO_SAMPLE_RATE,
            channels=1,
            dtype="float32",
            device=device,
        )
        sd.wait()
        return audio

    def transcribe_chunk_quick(self, chunk: np.ndarray) -> str:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        self.save_wav(chunk, tmp_path)
        text = self._transcription.transcribe_quick(tmp_path)
        tmp_path.unlink(missing_ok=True)
        return text

    def save_wav(self, audio: np.ndarray, path: Path) -> None:
        # Usar bytes em vez de string para evitar problemas de encoding no Windows
        with wave.open(str(path).encode("utf-8"), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(AUDIO_SAMPLE_RATE)
            wf.writeframes((audio * 32767).astype(np.int16).tobytes())
