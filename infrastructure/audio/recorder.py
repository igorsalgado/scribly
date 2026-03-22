import tempfile
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd
from scipy import signal

from domain.services import TranscriptionService
from settings import AUDIO_SAMPLE_RATE, LIVE_TRANSCRIPTION_CHUNK_SECONDS


def list_input_devices() -> list[dict]:
    devices = sd.query_devices()
    hostapis = sd.query_hostapis()
    wasapi_index = next(
        (i for i, h in enumerate(hostapis) if h["name"] == "Windows WASAPI"), -1
    )

    input_devices = []
    for i, dev in enumerate(devices):
        name = dev["name"]
        is_wasapi = wasapi_index != -1 and dev["hostapi"] == wasapi_index

        # Microfones e Stereo Mix (MME/DirectSound/WASAPI)
        if dev["max_input_channels"] > 0:
            input_devices.append(
                {
                    "index": i,
                    "name": f"{name} ({hostapis[dev['hostapi']]['name']})",
                    "channels": dev["max_input_channels"],
                }
            )

        # WASAPI Loopback (Dispositivos de saída tratados como entrada)
        elif is_wasapi and dev["max_output_channels"] > 0:
            input_devices.append(
                {
                    "index": i,
                    "name": f"{name} (Loopback)",
                    "channels": dev["max_output_channels"],
                }
            )

    return input_devices


class AudioRecorder:
    def __init__(self, transcription_service: TranscriptionService) -> None:
        self._transcription = transcription_service

    def record_chunk(self, device: "int | None" = None) -> np.ndarray:
        extra_settings = None
        hw_channels = 1
        hw_samplerate = AUDIO_SAMPLE_RATE

        if device is not None:
            dev_info = sd.query_devices(device)
            hostapis = sd.query_hostapis()
            wasapi_index = next(
                (i for i, h in enumerate(hostapis) if h["name"] == "Windows WASAPI"), -1
            )

            # Detect if it's a Loopback device (WASAPI and no native input channels)
            if (
                dev_info["max_input_channels"] == 0
                and dev_info["hostapi"] == wasapi_index
            ):
                extra_settings = sd.WasapiSettings(loopback=True)
                hw_channels = int(dev_info["max_output_channels"])
            else:
                hw_channels = int(dev_info["max_input_channels"])

            # Check if 16kHz is supported; if not, use device default samplerate
            try:
                sd.check_input_settings(
                    device=device,
                    channels=hw_channels,
                    samplerate=hw_samplerate,
                    extra_settings=extra_settings,
                )
            except Exception:
                hw_samplerate = int(dev_info["default_samplerate"])

        audio = sd.rec(
            int(LIVE_TRANSCRIPTION_CHUNK_SECONDS * hw_samplerate),
            samplerate=hw_samplerate,
            channels=hw_channels,
            dtype="float32",
            device=device,
            extra_settings=extra_settings,
        )
        sd.wait()

        # Resample if hardware samplerate differs from target
        if hw_samplerate != AUDIO_SAMPLE_RATE:
            # Downmix first if multi-channel to simplify resampling
            if hw_channels > 1:
                audio = np.mean(audio, axis=1, keepdims=True)
            
            num_samples = int(len(audio) * AUDIO_SAMPLE_RATE / hw_samplerate)
            audio = signal.resample(audio, num_samples)
            
            # Since we downmixed before resampling if hw_channels > 1, 
            # the result is already mono. Let's make sure it's 2D for consistency.
            if audio.ndim == 1:
                audio = audio[:, np.newaxis]
        else:
            # Only downmix to mono if it wasn't resampled (resampling already downmixed)
            if hw_channels > 1:
                audio = np.mean(audio, axis=1, keepdims=True)

        return audio

    def transcribe_chunk_quick(self, chunk: np.ndarray) -> str:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        self.save_wav(chunk, tmp_path)
        text = self._transcription.transcribe_quick(tmp_path)
        tmp_path.unlink(missing_ok=True)
        return text

    def save_wav(self, audio: np.ndarray, path: Path) -> None:
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(AUDIO_SAMPLE_RATE)
            wf.writeframes((audio.flatten() * 32767).astype(np.int16).tobytes())
