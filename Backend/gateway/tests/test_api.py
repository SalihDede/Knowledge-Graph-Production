from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

import main


client = TestClient(main.app)


def test_live_and_models_contract() -> None:
    assert client.get("/api/health/live").json() == {
        "status": "ok",
        "service": "backend",
    }
    response = client.get("/api/models")
    assert response.status_code == 200
    assert response.json()
    assert {"id", "label"}.issubset(response.json()[0])


def test_extract_routes_wikontic_and_preserves_evidence(monkeypatch) -> None:
    captured = {}

    async def fake_extract(text, llm_model, embedding_model, ontology_language, prompt_type):
        captured.update(
            text=text,
            llm_model=llm_model,
            embedding_model=embedding_model,
            ontology_language=ontology_language,
            prompt_type=prompt_type,
        )
        return [
            {
                "baş": "Einstein",
                "baş_tipi": "person",
                "ilişki": "award received",
                "uç": "Nobel Prize",
                "uç_tipi": "award",
                "qualifiers": [{"relation": "year", "object": "1921"}],
                "kaynak_cumle": "Einstein received the Nobel Prize.",
            }
        ]

    monkeypatch.setattr(main, "_extract_wikontic", fake_extract)
    response = client.post(
        "/api/extract",
        json={
            "text": "Einstein received the Nobel Prize.",
            "model": "google/gemini-2.5-flash-lite",
            "prompt_type": "temel",
            "kg_type": "wicontic",
            "embedding_model": "turkish_e5_large",
            "ontology_language": "tr",
        },
    )

    assert response.status_code == 200
    assert captured["embedding_model"] == "turkish_e5_large"
    assert captured["ontology_language"] == "tr"
    assert response.json()["triplets"][0]["kaynak_cumle"]
    assert response.json()["triplets"][0]["qualifiers"] == [
        {"relation": "year", "object": "1921"}
    ]
    assert response.json()["highlight"] == ["Einstein"]


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

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            return response

    monkeypatch.setattr(main.httpx, "AsyncClient", FakeAsyncClient)
    triplets = await main._extract_wikontic("text", "model", "contriever", "en")

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


def test_visualization_contracts_return_html(monkeypatch) -> None:
    monkeypatch.setattr(main, "build_graph_html", lambda *args, **kwargs: "<html>graph</html>")
    monkeypatch.setattr(main, "build_source_graph_html", lambda *args, **kwargs: "<html>source</html>")

    triple = {"baş": "A", "ilişki": "rel", "uç": "B"}
    single = client.post("/api/visualize", json={"triplets": [triple], "highlight": ["A"]})
    combined = client.post(
        "/api/visualize/source",
        json={"sources": [{"id": "slot-1", "triplets": [triple]}]},
    )

    assert single.status_code == 200
    assert single.headers["content-type"].startswith("text/html")
    assert combined.status_code == 200
    assert combined.headers["content-type"].startswith("text/html")
