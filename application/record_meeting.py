from __future__ import annotations

from datetime import datetime

import numpy as np
from rich.console import Console

from application.pipeline import ProcessingContext, ProcessingHandler
from domain.meeting import Meeting, Participant
from domain.repositories import MeetingRepository
from infrastructure.audio.recorder import AudioRecorder
from settings import (
    AUDIO_SAMPLE_RATE,
    MEETING_DATE_FORMAT,
    OUTPUT_DIR,
    to_project_path,
)

console = Console()


class RecordMeetingUseCase:
    def __init__(
        self,
        recorder: AudioRecorder,
        pipeline: ProcessingHandler,
        repository: MeetingRepository,
    ) -> None:
        self._recorder = recorder
        self._pipeline = pipeline
        self._repository = repository

    def execute(self, device: "int | None" = None) -> Meeting:
        console.print(
            "[bold]Gravando...[/bold] Pressione [red]Ctrl+C[/red] para encerrar.\n"
        )

        all_chunks: list[np.ndarray] = []
        try:
            while True:
                chunk = self._recorder.record_chunk(device=device)
                all_chunks.append(chunk)
                text = self._recorder.transcribe_chunk_quick(chunk)
                if text:
                    console.print(f"[dim]{text}[/dim]")
        except KeyboardInterrupt:
            pass

        console.print(
            "\n[bold yellow]Reuniao encerrada. Processando...[/bold yellow]\n"
        )

        if not all_chunks:
            raise ValueError("Nenhum audio gravado.")

        full_audio = np.concatenate(all_chunks, axis=0)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        duration = len(full_audio) / AUDIO_SAMPLE_RATE
        wav_path = OUTPUT_DIR / f"reuniao_{timestamp}.wav"
        self._recorder.save_wav(full_audio, wav_path)
        console.print(f"[dim]Audio salvo em {wav_path}[/dim]\n")

        meeting = Meeting.create(
            audio_path=to_project_path(wav_path),
            duration_seconds=duration,
        )

        context = ProcessingContext(
            wav_path=wav_path,
            date=datetime.now().strftime(MEETING_DATE_FORMAT),
        )
        self._pipeline.handle(context)

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
