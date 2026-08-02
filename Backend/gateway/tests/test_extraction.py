from __future__ import annotations

import httpx
import pytest

from extraction.errors import ExtractionError
from extraction.service import run_extraction
import extraction.wikontic_adapter as wikontic_adapter


class FakeAsyncClient:
    def __init__(self, response=None, exc=None):
        self._response = response
        self._exc = exc

    def __call__(self, *args, **kwargs):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def post(self, *args, **kwargs):
        if self._exc is not None:
            raise self._exc
        return self._response


@pytest.mark.asyncio
async def test_wikontic_adapter_preserves_fields(monkeypatch) -> None:
    response = httpx.Response(
        200,
        json={
            "triplets": [
                {
                    "subject": "A",
                    "subject_type": "Type A",
                    "relation": "rel",
                    "object": "B",
                    "object_type": "Type B",
                    "qualifiers": [{"relation": "time", "object": "2026"}],
                    "kaynak_cumle": "A rel B.",
                }
            ],
            "count": 1,
        },
    )
    monkeypatch.setattr(wikontic_adapter.httpx, "AsyncClient", FakeAsyncClient(response=response))

    triplets = await wikontic_adapter.extract_via_wikontic(
        text="text", model="model", embedding_model="contriever", ontology_language="en", prompt_type="temel"
    )

    assert triplets == [
        {
            "baş": "A",
            "baş_tipi": "Type A",
            "ilişki": "rel",
            "uç": "B",
            "uç_tipi": "Type B",
            "qualifiers": [{"relation": "time", "object": "2026"}],
            "kaynak_cumle": "A rel B.",
        }
    ]


@pytest.mark.asyncio
async def test_wikontic_adapter_maps_timeout_to_retryable_error(monkeypatch) -> None:
    monkeypatch.setattr(
        wikontic_adapter.httpx,
        "AsyncClient",
        FakeAsyncClient(exc=httpx.TimeoutException("boom")),
    )

    with pytest.raises(ExtractionError) as exc_info:
        await wikontic_adapter.extract_via_wikontic(
            text="text", model="model", embedding_model="contriever", ontology_language="en", prompt_type="temel"
        )

    assert exc_info.value.status_code == 504
    assert exc_info.value.retryable is True


@pytest.mark.asyncio
async def test_wikontic_adapter_passes_through_client_errors_as_non_retryable(monkeypatch) -> None:
    response = httpx.Response(409, json={"detail": "Doküman zaten var"})
    monkeypatch.setattr(wikontic_adapter.httpx, "AsyncClient", FakeAsyncClient(response=response))

    with pytest.raises(ExtractionError) as exc_info:
        await wikontic_adapter.extract_via_wikontic(
            text="text", model="model", embedding_model="contriever", ontology_language="en", prompt_type="temel"
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.retryable is False


@pytest.mark.asyncio
async def test_run_extraction_dispatches_to_wikontic(monkeypatch) -> None:
    async def fake_wikontic(**kwargs):
        fake_wikontic.called_with = kwargs
        return [{"baş": "A"}]

    monkeypatch.setattr("extraction.service.extract_via_wikontic", fake_wikontic)

    result = await run_extraction(
        text="t", model="m", kg_type="wicontic", prompt_type="temel",
        embedding_model="contriever", ontology_language="en",
    )

    assert result == [{"baş": "A"}]
    assert fake_wikontic.called_with["model"] == "m"


@pytest.mark.asyncio
async def test_run_extraction_dispatches_to_openrouter_for_wikipedia_and_kggen(monkeypatch) -> None:
    calls = []

    async def fake_openrouter(**kwargs):
        calls.append(kwargs["kg_type"])
        return []

    monkeypatch.setattr("extraction.service.extract_via_openrouter", fake_openrouter)

    await run_extraction(
        text="t", model="m", kg_type="wikipedia", prompt_type="temel",
        embedding_model="contriever", ontology_language="en",
    )
    await run_extraction(
        text="t", model="m", kg_type="kggen", prompt_type="temel",
        embedding_model="contriever", ontology_language="en",
    )

    assert calls == ["wikipedia", "kggen"]


@pytest.mark.asyncio
async def test_run_extraction_rejects_unknown_kg_type() -> None:
    with pytest.raises(ExtractionError) as exc_info:
        await run_extraction(
            text="t", model="m", kg_type="unknown", prompt_type="temel",
            embedding_model="contriever", ontology_language="en",
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.retryable is False
