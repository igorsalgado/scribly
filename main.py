import os
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

load_dotenv()

from application.pipeline import DiarizationHandler, ExtractionHandler, TranscriptionHandler
from application.record_meeting import RecordMeetingUseCase
from application.reprocess_meeting import ReprocessMeetingUseCase
from infrastructure.audio.recorder import AudioRecorder, list_input_devices
from infrastructure.diarization.pyannote import PyannoteDiarizer
from infrastructure.extraction.ollama import OllamaExtractor
from infrastructure.persistence.sqlite_repository import SQLiteMeetingRepository
from infrastructure.transcription.whisper import WhisperTranscriber

console = Console()


def build_pipeline(whisper: WhisperTranscriber, hf_token: str) -> TranscriptionHandler:
    pyannote = PyannoteDiarizer(hf_token=hf_token)
    ollama = OllamaExtractor(
        model=os.getenv("OLLAMA_MODEL", "mistral"),
        url=os.getenv("OLLAMA_URL", "http://localhost:11434"),
    )

    head = TranscriptionHandler(whisper)
    head.set_next(DiarizationHandler(pyannote)).set_next(ExtractionHandler(ollama))
    return head


def select_device() -> "int | None":
    devices = list_input_devices()
    console.print("\n[bold cyan]Dispositivos de entrada disponíveis:[/bold cyan]\n")
    for dev in devices:
        console.print(f"  [yellow]{dev['index']}[/yellow]: {dev['name']}")
    console.print(
        "\n[dim]Para capturar áudio do sistema (Teams / Meet / Zoom):\n"
        "  Painel de Som → Gravação → clique direito → Mostrar dispositivos desabilitados\n"
        "  Ative 'Stereo Mix' ou 'What U Hear' e selecione-o aqui.[/dim]\n"
    )
    choice = Prompt.ask("Número do dispositivo", default="")
    return int(choice) if choice.strip() else None


def main() -> None:
    console.print(
        Panel.fit(
            "[bold green]Meeting Scribe[/bold green]\n"
            "[dim]Whisper + Pyannote + Ollama — 100% offline[/dim]"
        )
    )

    hf_token = os.getenv("HF_TOKEN", "")
    if not hf_token:
        console.print(
            "[red bold]HF_TOKEN não configurado.[/red bold]\n"
            "[dim]Configure no arquivo .env — necessário para baixar os modelos de diarização.\n"
            "Consulte o README para instruções.[/dim]"
        )
        return

    whisper = WhisperTranscriber(model_size=os.getenv("WHISPER_MODEL", "small"))
    pipeline = build_pipeline(whisper, hf_token)
    recorder = AudioRecorder(transcription_service=whisper)
    repository = SQLiteMeetingRepository(db_path=Path("scribly.db"))

    device = select_device()

    use_case = RecordMeetingUseCase(
        recorder=recorder,
        pipeline=pipeline,
        repository=repository,
    )
    meeting = use_case.execute(device=device)

    if meeting.transcript:
        console.print(
            Panel(
                meeting.transcript.diarized_text,
                title="[bold]Transcript Diarizado[/bold]",
                border_style="dim",
            )
        )
    if meeting.business_rules:
        console.print(
            Panel(
                meeting.business_rules.raw_markdown,
                title="[bold green]Regras de Negócio[/bold green]",
                border_style="green",
            )
        )

    ts = meeting.date.strftime("%Y%m%d_%H%M%S")
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)
    output_md = output_dir / f"reuniao_{ts}.md"

    if meeting.transcript and meeting.business_rules:
        output_md.write_text(
            f"# Transcript Diarizado\n\n{meeting.transcript.diarized_text}\n\n---\n\n{meeting.business_rules.raw_markdown}\n",
            encoding="utf-8",
        )
        console.print(f"\n[dim]Salvo em [bold]{output_md}[/bold][/dim]")


if __name__ == "__main__":
    main()
