from abc import ABC, abstractmethod
from pathlib import Path

from domain.meeting import BusinessRules, TranscriptSegment


class TranscriptionService(ABC):
    @abstractmethod
    def transcribe_quick(self, wav_path: Path) -> str: ...

    @abstractmethod
    def transcribe_with_timestamps(self, wav_path: Path) -> list[TranscriptSegment]: ...


class DiarizationService(ABC):
    @abstractmethod
    def assign_speakers(
        self, segments: list[TranscriptSegment], wav_path: Path
    ) -> list[TranscriptSegment]: ...


class ExtractionService(ABC):
    @abstractmethod
    def extract(
        self, diarized_text: str, date: str, participants: list[str]
    ) -> BusinessRules: ...
