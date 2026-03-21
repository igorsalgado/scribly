from __future__ import annotations

import httpx

from application.business_rules_report import build_business_rules_markdown
from domain.meeting import BusinessRules
from domain.services import ExtractionService
from infrastructure.extraction.prompts import (
    EXTRACTION_SYSTEM_PROMPT,
    EXTRACTION_USER_TEMPLATE,
)


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

        raw_markdown = build_business_rules_markdown(
            extracted,
            date=date,
            participants=participants,
        )

        return BusinessRules(raw_markdown=raw_markdown)
