from __future__ import annotations

import logging
import os

import httpx

from .errors import ExtractionError

logger = logging.getLogger(__name__)

WIKONTIC_URL = os.getenv("WIKONTIC_URL", "http://localhost:8001")
WIKONTIC_TIMEOUT_SECONDS = float(os.getenv("WIKONTIC_TIMEOUT_SECONDS", "170"))

_PASSTHROUGH_STATUSES = {400, 401, 403, 404, 409, 422}
_RETRYABLE_PASSTHROUGH_STATUSES = {503}


def _response_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text or response.reason_phrase
    if isinstance(payload, dict):
        return str(payload.get("detail") or payload)
    return str(payload)


async def extract_via_wikontic(
    *,
    text: str,
    model: str,
    embedding_model: str,
    ontology_language: str,
    prompt_type: str,
    request_id: str = "-",
) -> list[dict]:
    """Calls the Wikontic service and normalises its response to the app's Turkish field names."""
    payload = {
        "text": text,
        "embedding_model": embedding_model,
        "llm_model": model,
        "ontology_language": ontology_language,
        "prompt_type": prompt_type,
    }
    try:
        async with httpx.AsyncClient(timeout=WIKONTIC_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{WIKONTIC_URL}/extract",
                json=payload,
                headers={"X-Request-ID": request_id},
            )
    except httpx.TimeoutException as exc:
        raise ExtractionError(
            "Wikontic isteği zaman aşımına uğradı", status_code=504, retryable=True
        ) from exc
    except httpx.HTTPError as exc:
        raise ExtractionError(
            "Wikontic servisine ulaşılamadı", status_code=502, retryable=True
        ) from exc

    if not resp.is_success:
        upstream_status = resp.status_code
        detail = _response_detail(resp)
        if upstream_status in _PASSTHROUGH_STATUSES:
            raise ExtractionError(detail, status_code=upstream_status, retryable=False)
        if upstream_status in _RETRYABLE_PASSTHROUGH_STATUSES:
            raise ExtractionError(detail, status_code=upstream_status, retryable=True)
        raise ExtractionError(detail, status_code=502, retryable=True)

    raw_triplets = resp.json().get("triplets", [])

    normalised = []
    for t in raw_triplets:
        normalised.append({
            "baş":      t.get("subject", ""),
            "baş_tipi": t.get("subject_type", ""),
            "ilişki":   t.get("relation", ""),
            "uç":       t.get("object", ""),
            "uç_tipi":  t.get("object_type", ""),
            "qualifiers": t.get("qualifiers", []),
            "kaynak_cumle": t.get("kaynak_cumle", ""),
        })
    return normalised
