from pathlib import Path

from faster_whisper import WhisperModel

from domain.meeting import TranscriptSegment
from domain.services import TranscriptionService


class WhisperTranscriber(TranscriptionService):
    def __init__(self, model_size: str = "small") -> None:
        self._model = WhisperModel(model_size, device="cpu", compute_type="int8")

    def transcribe_quick(self, wav_path: Path) -> str:
        segments, _ = self._model.transcribe(str(wav_path), language="pt")
        return " ".join(s.text.strip() for s in segments if s.text.strip())

    def transcribe_with_timestamps(self, wav_path: Path) -> list[TranscriptSegment]:
        raw_segments, _ = self._model.transcribe(
            str(wav_path),
            language="pt",
            word_timestamps=True,
        )
        return [
            TranscriptSegment(start=s.start, end=s.end, text=s.text.strip())
            for s in raw_segments
            if s.text.strip()
        ]
