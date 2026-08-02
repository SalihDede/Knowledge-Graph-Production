from __future__ import annotations

from .errors import ExtractionError
from .openrouter_provider import extract_via_openrouter
from .wikontic_adapter import extract_via_wikontic


async def run_extraction(
    *,
    text: str,
    model: str,
    kg_type: str,
    prompt_type: str,
    embedding_model: str,
    ontology_language: str,
    request_id: str = "-",
) -> list[dict]:
    """Single dispatch point for every kg_type. Used by both the synchronous
    `/api/extract` endpoint and the Celery extraction worker so the two never
    drift apart."""
    if kg_type == "wicontic":
        return await extract_via_wikontic(
            text=text,
            model=model,
            embedding_model=embedding_model,
            ontology_language=ontology_language,
            prompt_type=prompt_type,
            request_id=request_id,
        )
    if kg_type in ("wikipedia", "kggen"):
        return await extract_via_openrouter(
            text=text, model=model, kg_type=kg_type, prompt_type=prompt_type
        )

    raise ExtractionError(f"Bilinmeyen kg_type: {kg_type}", status_code=400, retryable=False)
