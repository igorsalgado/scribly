import wave
from datetime import datetime
from pathlib import Path

from application.pipeline import ProcessingContext, ProcessingHandler
from domain.meeting import Meeting, Participant
from domain.repositories import MeetingRepository


def _wav_duration(wav_path: Path) -> float:
    with wave.open(str(wav_path), "rb") as wf:
        return wf.getnframes() / wf.getframerate()


class ReprocessMeetingUseCase:
    def __init__(
        self,
        pipeline: ProcessingHandler,
        repository: MeetingRepository,
    ) -> None:
        self._pipeline = pipeline
        self._repository = repository

    def execute(self, wav_path: Path) -> Meeting:
        context = ProcessingContext(
            wav_path=wav_path,
            date=datetime.now().strftime("%d/%m/%Y %H:%M"),
        )
        self._pipeline.handle(context)

        meeting = Meeting.create(audio_path=str(wav_path), duration_seconds=_wav_duration(wav_path))
        if context.transcript:
            meeting.transcript = context.transcript
            meeting.participants = [
                Participant(label=sp)
                for sp in dict.fromkeys(seg.speaker for seg in context.segments)
            ]
        if context.business_rules:
            meeting.business_rules = context.business_rules

        self._repository.save(meeting)
        return meeting
