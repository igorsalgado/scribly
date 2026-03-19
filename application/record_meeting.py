from datetime import datetime
from pathlib import Path

import numpy as np
from rich.console import Console

from application.pipeline import ProcessingContext, ProcessingHandler
from domain.meeting import Meeting, Participant
from domain.repositories import MeetingRepository
from infrastructure.audio.recorder import AudioRecorder

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
            "\n[bold yellow]Reunião encerrada. Processando...[/bold yellow]\n"
        )

        if not all_chunks:
            raise ValueError("Nenhum áudio gravado.")

        full_audio = np.concatenate(all_chunks, axis=0)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = Path("output")
        output_dir.mkdir(exist_ok=True)

        duration = len(full_audio) / 16000
        wav_path = output_dir / f"reuniao_{ts}.wav"
        self._recorder.save_wav(full_audio, wav_path)
        console.print(f"[dim]Áudio salvo em {wav_path}[/dim]\n")

        meeting = Meeting.create(audio_path=str(wav_path), duration_seconds=duration)

        context = ProcessingContext(
            wav_path=wav_path,
            date=datetime.now().strftime("%d/%m/%Y %H:%M"),
        )
        self._pipeline.handle(context)

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
