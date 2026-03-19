from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from domain.meeting import BusinessRules, Transcript, TranscriptSegment
from domain.services import DiarizationService, ExtractionService, TranscriptionService


@dataclass
class ProcessingContext:
    wav_path: Path
    date: str
    segments: list[TranscriptSegment] = field(default_factory=list)
    transcript: "Transcript | None" = None
    business_rules: "BusinessRules | None" = None
    on_progress: "Callable[[str], None] | None" = None


class ProcessingHandler(ABC):
    def __init__(self) -> None:
        self._next: "ProcessingHandler | None" = None

    def set_next(self, handler: "ProcessingHandler") -> "ProcessingHandler":
        self._next = handler
        return handler

    @abstractmethod
    def handle(self, context: ProcessingContext) -> None: ...

    def _pass_to_next(self, context: ProcessingContext) -> None:
        if self._next:
            self._next.handle(context)


class TranscriptionHandler(ProcessingHandler):
    def __init__(self, service: TranscriptionService) -> None:
        super().__init__()
        self._service = service

    def handle(self, context: ProcessingContext) -> None:
        if context.on_progress:
            context.on_progress("transcribing")
        context.segments = self._service.transcribe_with_timestamps(context.wav_path)
        context.transcript = Transcript(segments=context.segments)
        self._pass_to_next(context)


class DiarizationHandler(ProcessingHandler):
    def __init__(self, service: DiarizationService) -> None:
        super().__init__()
        self._service = service

    def handle(self, context: ProcessingContext) -> None:
        if context.on_progress:
            context.on_progress("diarizing")
        if context.segments:
            context.segments = self._service.assign_speakers(
                context.segments, context.wav_path
            )
            context.transcript = Transcript(segments=context.segments)
        self._pass_to_next(context)


class ExtractionHandler(ProcessingHandler):
    def __init__(self, service: ExtractionService) -> None:
        super().__init__()
        self._service = service

    def handle(self, context: ProcessingContext) -> None:
        if context.on_progress:
            context.on_progress("extracting")
        if context.transcript:
            participants = list(
                dict.fromkeys(seg.speaker for seg in context.segments)
            )
            context.business_rules = self._service.extract(
                context.transcript.diarized_text,
                date=context.date,
                participants=participants,
            )
        self._pass_to_next(context)
