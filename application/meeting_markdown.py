from __future__ import annotations

from pathlib import Path

from domain.meeting import Meeting
from settings import OUTPUT_DIR, resolve_project_path


def build_meeting_markdown(meeting: Meeting) -> str | None:
    if not meeting.transcript or not meeting.business_rules:
        return None

    return (
        "# Transcript Diarizado\n\n"
        f"{meeting.transcript.diarized_text}\n\n---\n\n"
        f"{meeting.business_rules.raw_markdown}\n"
    )


def get_meeting_markdown_path(meeting: Meeting) -> Path:
    if meeting.audio_path:
        audio_path = resolve_project_path(meeting.audio_path)
        if audio_path.suffix.lower() == ".wav":
            return audio_path.with_suffix(".md")

    timestamp = meeting.date.strftime("%Y%m%d_%H%M%S")
    return OUTPUT_DIR / f"reuniao_{timestamp}.md"


def write_meeting_markdown(meeting: Meeting) -> Path | None:
    content = build_meeting_markdown(meeting)
    if content is None:
        return None

    markdown_path = get_meeting_markdown_path(meeting)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(content, encoding="utf-8-sig")
    return markdown_path
