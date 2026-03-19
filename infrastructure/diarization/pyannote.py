from __future__ import annotations

from pathlib import Path

from pyannote.audio import Pipeline

from domain.meeting import TranscriptSegment
from domain.services import DiarizationService


def _dominant_speaker(seg_start: float, seg_end: float, diarization) -> str:
    overlap: dict[str, float] = {}
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        start = max(seg_start, turn.start)
        end = min(seg_end, turn.end)
        if end > start:
            overlap[speaker] = overlap.get(speaker, 0.0) + (end - start)
    return max(overlap, key=overlap.get) if overlap else "UNKNOWN"


class PyannoteDiarizer(DiarizationService):
    def __init__(self, hf_token: str | None = None) -> None:
        self._pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            use_auth_token=hf_token or None,
        )

    def assign_speakers(
        self,
        segments: list[TranscriptSegment],
        wav_path: Path,
    ) -> list[TranscriptSegment]:
        diarization = self._pipeline(str(wav_path))

        label_map: dict[str, str] = {}
        for _, _, label in diarization.itertracks(yield_label=True):
            if label not in label_map:
                label_map[label] = f"Participante {len(label_map) + 1}"

        for segment in segments:
            raw_speaker = _dominant_speaker(segment.start, segment.end, diarization)
            segment.speaker = label_map.get(raw_speaker, "Desconhecido")

        return segments
