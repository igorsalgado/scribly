"""
Pre-download all models needed for offline operation.

Run this ONCE before your first meeting:
    python download_models.py

Models downloaded:
  - Whisper (faster-whisper): cached in ~/.cache/huggingface/hub
  - Pyannote diarization:     cached in ~/.cache/torch/pyannote
  - Ollama LLM:               pulled via Docker (docker compose must be running)

Requirements before running:
  1. Copy .env.example → .env and fill in HF_TOKEN
  2. Accept model terms at:
       https://huggingface.co/pyannote/speaker-diarization-3.1
       https://huggingface.co/pyannote/segmentation-3.0
  3. docker compose up -d   (starts Ollama)
"""

import json
import os
import sys

import httpx
from dotenv import load_dotenv
from rich.console import Console

load_dotenv()
console = Console()


def download_whisper(model_size: str) -> None:
    console.print(f"\n[cyan]1/3 — Whisper [bold]{model_size}[/bold][/cyan]")
    from faster_whisper import WhisperModel
    WhisperModel(model_size, device="cpu", compute_type="int8")
    console.print("[green]Whisper pronto[/green]")


def download_pyannote(hf_token: str) -> None:
    console.print("\n[cyan]2/3 — Pyannote diarization[/cyan]")
    from pyannote.audio import Pipeline
    Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1",
        use_auth_token=hf_token,
    )
    console.print("[green]Pyannote pronto[/green]")


def pull_ollama_model(model: str, url: str) -> None:
    console.print(f"\n[cyan]3/3 — Ollama model [bold]{model}[/bold][/cyan]")
    console.print("[dim]Isso pode demorar vários minutos dependendo do tamanho do modelo...[/dim]")

    try:
        httpx.get(f"{url}/api/tags", timeout=5.0).raise_for_status()
    except Exception:
        console.print(
            f"[red]Ollama não está acessível em {url}.[/red]\n"
            "[dim]Execute: docker compose up -d[/dim]"
        )
        return

    with httpx.stream(
        "POST",
        f"{url}/api/pull",
        json={"name": model},
        timeout=None,
    ) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if '"status"' in line:
                data = json.loads(line)
                status = data.get("status", "")
                if "pulling" in status or "downloading" in status:
                    completed = data.get("completed", 0)
                    total = data.get("total", 0)
                    if total:
                        pct = completed / total * 100
                        console.print(f"\r[dim]{status} {pct:.1f}%[/dim]", end="")
                elif status:
                    console.print(f"\n[dim]{status}[/dim]")

    console.print(f"\n[green]{model} pronto[/green]")


def main() -> None:
    hf_token = os.getenv("HF_TOKEN", "")
    whisper_model = os.getenv("WHISPER_MODEL", "small")
    ollama_model = os.getenv("OLLAMA_MODEL", "mistral")
    ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434")

    if not hf_token or hf_token == "hf_...":
        console.print(
            "[red]HF_TOKEN não configurado no .env[/red]\n"
            "1. Crie uma conta em https://huggingface.co\n"
            "2. Gere um token em https://huggingface.co/settings/tokens\n"
            "3. Aceite os termos:\n"
            "   https://huggingface.co/pyannote/speaker-diarization-3.1\n"
            "   https://huggingface.co/pyannote/segmentation-3.0\n"
            "4. Adicione HF_TOKEN=hf_... no arquivo .env"
        )
        sys.exit(1)

    console.print("[bold green]Meeting Scribe — Download de Modelos[/bold green]\n")

    download_whisper(whisper_model)
    download_pyannote(hf_token)
    pull_ollama_model(ollama_model, ollama_url)

    console.print("\n[bold green]Todos os modelos prontos! Execute: python main.py[/bold green]")


if __name__ == "__main__":
    main()
