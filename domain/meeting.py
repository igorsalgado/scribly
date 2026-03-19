from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4


@dataclass
class Participant:
    label: str


@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str
    speaker: str = "UNKNOWN"


@dataclass
class Transcript:
    segments: list[TranscriptSegment]

    @property
    def diarized_text(self) -> str:
        lines = []
        current_speaker = None
        buffer: list[str] = []
        for seg in self.segments:
            if seg.speaker != current_speaker:
                if current_speaker and buffer:
                    lines.append(f"**{current_speaker}**: {' '.join(buffer)}")
                current_speaker = seg.speaker
                buffer = [seg.text]
            else:
                buffer.append(seg.text)
        if current_speaker and buffer:
            lines.append(f"**{current_speaker}**: {' '.join(buffer)}")
        return "\n\n".join(lines)


@dataclass
class BusinessRules:
    raw_markdown: str


@dataclass
class Meeting:
    id: UUID
    date: datetime
    audio_path: str
    duration_seconds: float
    participants: list[Participant] = field(default_factory=list)
    transcript: "Transcript | None" = None
    business_rules: "BusinessRules | None" = None

    @staticmethod
    def create(audio_path: str, duration_seconds: float) -> "Meeting":
        return Meeting(
            id=uuid4(),
            date=datetime.now(),
            audio_path=audio_path,
            duration_seconds=duration_seconds,
        )
