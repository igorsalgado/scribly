from __future__ import annotations

import wave
from datetime import datetime
from pathlib import Path

from application.pipeline import ProcessingContext, ProcessingHandler
from domain.meeting import Meeting, Participant
from domain.repositories import MeetingRepository
from settings import MEETING_DATE_FORMAT, to_project_path


def _wav_duration(wav_path: Path) -> float:
    with wave.open(str(wav_path), "rb") as wav_file:
        return wav_file.getnframes() / wav_file.getframerate()


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
            date=datetime.now().strftime(MEETING_DATE_FORMAT),
        )
        self._pipeline.handle(context)

        meeting = Meeting.create(
            audio_path=to_project_path(wav_path),
            duration_seconds=_wav_duration(wav_path),
        )
        if context.transcript:
            meeting.transcript = context.transcript
            meeting.participants = [
                Participant(label=speaker)
                for speaker in dict.fromkeys(
                    segment.speaker for segment in context.segments
                )
            ]
        if context.business_rules:
            meeting.business_rules = context.business_rules

        self._repository.save(meeting)
        return meeting
