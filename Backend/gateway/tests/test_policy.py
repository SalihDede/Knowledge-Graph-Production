from __future__ import annotations

import pytest

from catalog import registry as model_registry
import policy


ALLOWED_MODEL = "google/gemini-2.5-flash-lite"
ANOTHER_ALLOWED_MODEL = "openai/gpt-4o-mini"


def _valid_kwargs(**overrides):
    base = dict(
        model=ALLOWED_MODEL,
        kg_type="wikipedia",
        prompt_type="temel",
        embedding_model="contriever",
        ontology_language="en",
        is_anonymous=False,
    )
    base.update(overrides)
    return base


def test_validate_pipeline_accepts_valid_combination() -> None:
    policy.validate_pipeline(**_valid_kwargs())  # should not raise


@pytest.mark.parametrize(
    "field,value",
    [
        ("kg_type", "not-a-real-kg-type"),
        ("prompt_type", "not-a-real-prompt-type"),
        ("embedding_model", "not-a-real-embedding-model"),
        ("ontology_language", "fr"),
    ],
)
def test_validate_pipeline_rejects_unknown_field_values(field: str, value: str) -> None:
    with pytest.raises(policy.PolicyError) as exc_info:
        policy.validate_pipeline(**_valid_kwargs(**{field: value}))
    assert exc_info.value.status_code == 422
    assert value in exc_info.value.message


def test_validate_pipeline_rejects_model_outside_full_catalog() -> None:
    with pytest.raises(policy.PolicyError) as exc_info:
        policy.validate_pipeline(**_valid_kwargs(model="not-a-real-model", is_anonymous=False))
    assert exc_info.value.status_code == 422


def test_validate_pipeline_rejects_model_outside_anonymous_allowlist(monkeypatch) -> None:
    monkeypatch.delenv("ANONYMOUS_MODEL_ALLOWLIST", raising=False)
    with pytest.raises(policy.PolicyError):
        policy.validate_pipeline(
            **_valid_kwargs(model=ANOTHER_ALLOWED_MODEL, is_anonymous=True)
        )


def test_validate_pipeline_allows_default_anonymous_model(monkeypatch) -> None:
    monkeypatch.delenv("ANONYMOUS_MODEL_ALLOWLIST", raising=False)
    policy.validate_pipeline(**_valid_kwargs(model=ALLOWED_MODEL, is_anonymous=True))


def test_validate_text_length_accepts_text_within_limit() -> None:
    policy.validate_text_length("a" * policy.MAX_EXTRACTION_CHARS)


def test_validate_text_length_rejects_text_over_limit() -> None:
    with pytest.raises(policy.PolicyError) as exc_info:
        policy.validate_text_length("a" * (policy.MAX_EXTRACTION_CHARS + 1))
    assert exc_info.value.status_code == 422


def test_active_job_limit_exceeded_uses_429() -> None:
    error = policy.ActiveJobLimitExceeded(3)
    assert error.status_code == 429
    assert "3" in error.message


def test_catalog_allowed_model_ids_include_full_catalog() -> None:
    ids = model_registry.allowed_model_ids()
    assert ALLOWED_MODEL in ids
    assert ANOTHER_ALLOWED_MODEL in ids
    assert "not-a-real-model" not in ids


def test_catalog_anonymous_model_ids_defaults_to_flash_lite(monkeypatch) -> None:
    monkeypatch.delenv("ANONYMOUS_MODEL_ALLOWLIST", raising=False)
    assert model_registry.anonymous_model_ids() == {ALLOWED_MODEL}


def test_catalog_anonymous_model_ids_respects_env_override(monkeypatch) -> None:
    monkeypatch.setenv("ANONYMOUS_MODEL_ALLOWLIST", f"{ALLOWED_MODEL},{ANOTHER_ALLOWED_MODEL}")
    assert model_registry.anonymous_model_ids() == {ALLOWED_MODEL, ANOTHER_ALLOWED_MODEL}


def test_catalog_anonymous_model_ids_never_exceeds_full_catalog(monkeypatch) -> None:
    monkeypatch.setenv("ANONYMOUS_MODEL_ALLOWLIST", "not-a-real-model,also-fake")
    assert model_registry.anonymous_model_ids() == set()


def test_catalog_is_model_allowed_distinguishes_identity(monkeypatch) -> None:
    monkeypatch.delenv("ANONYMOUS_MODEL_ALLOWLIST", raising=False)
    assert model_registry.is_model_allowed(ALLOWED_MODEL, is_anonymous=True) is True
    assert model_registry.is_model_allowed(ANOTHER_ALLOWED_MODEL, is_anonymous=True) is False
    assert model_registry.is_model_allowed(ANOTHER_ALLOWED_MODEL, is_anonymous=False) is True
    assert model_registry.is_model_allowed("not-a-real-model", is_anonymous=False) is False
