from __future__ import annotations

import httpx

from domain.meeting import BusinessRules
from domain.services import ExtractionService
from infrastructure.extraction.prompts import (
    BUSINESS_RULES_OUTPUT_TEMPLATE,
    EXTRACTION_SYSTEM_PROMPT,
    EXTRACTION_USER_TEMPLATE,
)


def _extract_section(text: str, header: str, skip_header: bool = False) -> str:
    lines = text.splitlines()
    capturing = False
    result: list[str] = []
    for line in lines:
        if line.strip() == header:
            capturing = True
            if skip_header:
                result = []
            continue
        if capturing and line.startswith("## "):
            break
        if capturing:
            result.append(line)
    return "\n".join(result).strip() or "(nao identificado)"


class OllamaExtractor(ExtractionService):
    def __init__(
        self,
        model: str = "mistral",
        url: str = "http://localhost:11434",
    ) -> None:
        self._model = model
        self._url = url.rstrip("/")

    def extract(
        self,
        diarized_text: str,
        date: str,
        participants: list[str],
    ) -> BusinessRules:
        prompt = EXTRACTION_USER_TEMPLATE.format(transcript=diarized_text)

        response = httpx.post(
            f"{self._url}/api/generate",
            json={
                "model": self._model,
                "system": EXTRACTION_SYSTEM_PROMPT,
                "prompt": prompt,
                "stream": False,
            },
            timeout=120.0,
        )
        response.raise_for_status()
        extracted = response.json()["response"].strip()

        raw_markdown = BUSINESS_RULES_OUTPUT_TEMPLATE.format(
            date=date,
            participants="\n".join(f"- {participant}" for participant in participants),
            summary=_extract_section(extracted, "## Resumo Executivo"),
            decisions=_extract_section(extracted, "## Decisoes Tomadas"),
            rules_table=_extract_section(
                extracted,
                "## Regras de Negocio Identificadas",
                skip_header=True,
            ),
            actions=_extract_section(extracted, "## Acoes / Next Steps"),
            open_questions=_extract_section(extracted, "## Duvidas em Aberto"),
        )

        return BusinessRules(raw_markdown=raw_markdown)
