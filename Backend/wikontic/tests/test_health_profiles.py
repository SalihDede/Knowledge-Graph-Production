from __future__ import annotations

from fastapi.testclient import TestClient

import api

client = TestClient(api.app)


class _FakeCollection:
    def __init__(self, count: int):
        self._count = count

    def estimated_document_count(self) -> int:
        return self._count


class _FakeDatabase:
    def __init__(self, collections: dict):
        self._collections = collections

    def list_collection_names(self) -> list:
        return list(self._collections)

    def __getitem__(self, name):
        return self._collections[name]


class _FakeMongoClient:
    def __init__(self, databases: dict):
        self._databases = databases

    def list_database_names(self) -> list:
        return list(self._databases)

    def __getitem__(self, name):
        return self._databases[name]


def test_profiles_reports_ok_when_databases_are_populated(monkeypatch) -> None:
    monkeypatch.setenv("WIKONTIC_PROFILES", "en__contriever")
    fake_client = _FakeMongoClient({
        "ontology__en": _FakeDatabase({"entities": _FakeCollection(10)}),
        "triplets": _FakeDatabase({}),
    })
    monkeypatch.setattr(api, "_get_mongo", lambda: fake_client)

    response = client.get("/health/profiles")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["profiles"]["en__contriever"]["ok"] is True


def test_profiles_reports_degraded_when_ontology_db_is_missing(monkeypatch) -> None:
    monkeypatch.setenv("WIKONTIC_PROFILES", "en__contriever")
    fake_client = _FakeMongoClient({"triplets": _FakeDatabase({})})
    monkeypatch.setattr(api, "_get_mongo", lambda: fake_client)

    response = client.get("/health/profiles")

    body = response.json()
    assert body["status"] == "degraded"
    assert body["profiles"]["en__contriever"]["ok"] is False
    assert body["profiles"]["en__contriever"]["ontology_db_ready"] is False


def test_profiles_reports_degraded_when_ontology_db_is_empty(monkeypatch) -> None:
    monkeypatch.setenv("WIKONTIC_PROFILES", "en__contriever")
    fake_client = _FakeMongoClient({
        "ontology__en": _FakeDatabase({"entities": _FakeCollection(0)}),
        "triplets": _FakeDatabase({}),
    })
    monkeypatch.setattr(api, "_get_mongo", lambda: fake_client)

    response = client.get("/health/profiles")

    body = response.json()
    assert body["status"] == "degraded"
    assert body["profiles"]["en__contriever"]["ontology_db_ready"] is False


def test_profiles_reports_error_for_unknown_profile_id(monkeypatch) -> None:
    monkeypatch.setenv("WIKONTIC_PROFILES", "xx__doesnotexist")
    monkeypatch.setattr(api, "_get_mongo", lambda: _FakeMongoClient({}))

    response = client.get("/health/profiles")

    body = response.json()
    assert body["status"] == "degraded"
    assert "error" in body["profiles"]["xx__doesnotexist"]


def test_profiles_reports_degraded_when_mongo_is_unreachable(monkeypatch) -> None:
    def _raise():
        raise RuntimeError("no mongo connection")

    monkeypatch.setattr(api, "_get_mongo", _raise)

    response = client.get("/health/profiles")

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"


def test_profiles_checks_every_configured_profile(monkeypatch) -> None:
    monkeypatch.setenv("WIKONTIC_PROFILES", "en__contriever, en__contriever")
    fake_client = _FakeMongoClient({
        "ontology__en": _FakeDatabase({"entities": _FakeCollection(10)}),
        "triplets": _FakeDatabase({}),
    })
    monkeypatch.setattr(api, "_get_mongo", lambda: fake_client)

    response = client.get("/health/profiles")

    # Duplicate entries in WIKONTIC_PROFILES collapse to one result key.
    assert list(response.json()["profiles"].keys()) == ["en__contriever"]
