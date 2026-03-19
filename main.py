from __future__ import annotations

import argparse
from pathlib import Path

from application.meeting_markdown import write_meeting_markdown
from rich.console import Console
from rich.panel import Panel

from application.reprocess_meeting import ReprocessMeetingUseCase
from settings import APP_NAME, create_pipeline, create_repository

console = Console()


def _show_results(meeting) -> None:
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
                title="[bold green]Regras de Negocio[/bold green]",
                border_style="green",
            )
        )

    output_md = write_meeting_markdown(meeting)
    if output_md is not None:
        console.print(f"\n[dim]Salvo em [bold]{output_md}[/bold][/dim]")


def _process_file(wav_path: Path) -> None:
    console.print(
        Panel.fit(
            f"[bold green]{APP_NAME}[/bold green]\n"
            "[dim]Modo de reprocessamento de audio[/dim]"
        )
    )

    use_case = ReprocessMeetingUseCase(
        pipeline=create_pipeline(),
        repository=create_repository(),
    )
    meeting = use_case.execute(wav_path=wav_path)
    _show_results(meeting)


def main() -> None:
    parser = argparse.ArgumentParser(description=f"{APP_NAME} entry point")
    parser.add_argument(
        "--file",
        type=Path,
        default=None,
        help="Reprocess an existing WAV file instead of launching the UI",
    )
    args = parser.parse_args()

    if args.file:
        _process_file(args.file)
        return

    from ui.app import main as run_ui

    run_ui()


if __name__ == "__main__":
    main()
