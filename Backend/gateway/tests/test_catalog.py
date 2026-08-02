from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from catalog import install_catalog


def test_models_endpoint_returns_catalog() -> None:
    app = FastAPI()
    install_catalog(app)
    client = TestClient(app)

    response = client.get("/api/models")

    assert response.status_code == 200
    body = response.json()
    assert body
    assert {"id", "label"}.issubset(body[0])
