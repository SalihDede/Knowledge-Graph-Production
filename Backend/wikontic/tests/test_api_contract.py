from __future__ import annotations

from fastapi.testclient import TestClient

import api


client = TestClient(api.app)


def test_live_does_not_require_models_or_database() -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "wikontic"}


def test_blank_text_is_rejected_before_pipeline() -> None:
    response = client.post("/extract", json={"text": "   "})
    assert response.status_code == 422
    assert response.json()["detail"] == "text must not be empty"


def test_missing_openrouter_key_is_explicit(monkeypatch) -> None:
    monkeypatch.setattr(api, "_API_KEY", None)
    response = client.post("/extract", json={"text": "A relation B."})
    assert response.status_code == 503
    assert "OpenRouter API key" in response.json()["detail"]


def test_readiness_requires_openrouter_key(monkeypatch) -> None:
    monkeypatch.setattr(api, "_API_KEY", None)
    monkeypatch.setattr(api, "_check_mongo", lambda: None)
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert "OpenRouter API key" in response.json()["detail"]


def test_incompatible_embedding_language_is_rejected(monkeypatch) -> None:
    monkeypatch.setattr(api, "_API_KEY", "test-key")
    monkeypatch.setattr(api, "_check_mongo", lambda: None)
    response = client.post(
        "/extract",
        json={
            "text": "A relation B.",
            "embedding_model": "contriever",
            "ontology_language": "tr",
            "prompt_type": "temel",
        },
    )
    assert response.status_code == 422
    assert "not compatible" in response.json()["detail"].lower()
