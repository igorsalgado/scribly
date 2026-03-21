from __future__ import annotations

from dataclasses import dataclass

from settings import MIN_MEETING_DURATION_SECONDS


def format_duration_label(duration_seconds: float) -> str:
    total_seconds = max(0, int(round(duration_seconds)))
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


@dataclass(slots=True)
class AudioTooShortError(ValueError):
    duration_seconds: float
    minimum_seconds: int = MIN_MEETING_DURATION_SECONDS

    def __post_init__(self) -> None:
        actual = format_duration_label(self.duration_seconds)
        minimum = format_duration_label(self.minimum_seconds)
        message = (
            "Gravacao descartada por duracao insuficiente. "
            f"Duracao atual: {actual}. Minimo exigido: {minimum}."
        )
        super().__init__(message)

    @property
    def user_message(self) -> str:
        actual = format_duration_label(self.duration_seconds)
        minimum = format_duration_label(self.minimum_seconds)
        return f"Gravacao descartada: {actual} de audio. O minimo exigido e {minimum}."


def validate_meeting_duration(
    duration_seconds: float,
    minimum_seconds: int = MIN_MEETING_DURATION_SECONDS,
) -> None:
    if duration_seconds < minimum_seconds:
        raise AudioTooShortError(
            duration_seconds=duration_seconds,
            minimum_seconds=minimum_seconds,
        )
