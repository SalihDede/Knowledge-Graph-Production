from __future__ import annotations

import logging

from llm import extract_triplets
from prompts import extract_with_ape, extract_with_dspy, extract_with_textgrad
from kggen_pipeline import (
    extract_with_kggen_ape,
    extract_with_kggen_dspy,
    extract_with_kggen_temel,
    extract_with_kggen_textgrad,
)

from .errors import ExtractionError

logger = logging.getLogger(__name__)


async def extract_via_openrouter(*, text: str, model: str, kg_type: str, prompt_type: str) -> list[dict]:
    """Dispatches to the OpenRouter-backed extraction pipelines. Only called by
    `extraction.service.run_extraction` for kg_type in {"wikipedia", "kggen"}."""
    try:
        if kg_type == "kggen":
            if prompt_type == "ape":
                return await extract_with_kggen_ape(text, model)
            if prompt_type == "dspy":
                return await extract_with_kggen_dspy(text, model)
            if prompt_type == "textgrad":
                return await extract_with_kggen_textgrad(text, model)
            return await extract_with_kggen_temel(text, model)

        if prompt_type == "ape":
            return await extract_with_ape(text, model)
        if prompt_type == "dspy":
            return await extract_with_dspy(text, model)
        if prompt_type == "textgrad":
            return await extract_with_textgrad(text, model)
        return await extract_triplets(text, model)
    except ExtractionError:
        raise
    except Exception as exc:
        logger.error("OpenRouter extraction failed: %s", type(exc).__name__)
        raise ExtractionError(
            "Triple çıkarma işlemi tamamlanamadı", status_code=502, retryable=True
        ) from exc
