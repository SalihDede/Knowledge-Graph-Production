from __future__ import annotations

import os

from catalog import registry as model_registry

MAX_EXTRACTION_CHARS = int(os.getenv("MAX_EXTRACTION_CHARS", "100000"))
MAX_ACTIVE_JOBS_PER_WORKSPACE = int(os.getenv("MAX_ACTIVE_JOBS_PER_WORKSPACE", "3"))

VALID_KG_TYPES = {"wikipedia", "wicontic", "kggen"}
VALID_PROMPT_TYPES = {"temel", "ape", "dspy", "textgrad"}
VALID_EMBEDDING_MODELS = {
    "contriever",
    "bge_m3",
    "turkish_e5_large",
    "turkish_sbert_mean_nli_stsb",
    "mft_random",
}
VALID_ONTOLOGY_LANGUAGES = {"en", "tr"}


class PolicyError(Exception):
    def __init__(self, message: str, *, status_code: int = 422):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class ActiveJobLimitExceeded(PolicyError):
    def __init__(self, limit: int):
        super().__init__(
            f"Çalışma alanı başına en fazla {limit} aktif (queued/running) iş çalıştırılabilir",
            status_code=429,
        )
        self.limit = limit


def validate_text_length(text: str) -> None:
    if len(text) > MAX_EXTRACTION_CHARS:
        raise PolicyError(
            f"Metin en fazla {MAX_EXTRACTION_CHARS} karakter olabilir "
            f"(gönderilen: {len(text)})"
        )


def validate_pipeline(
    *,
    model: str,
    kg_type: str,
    prompt_type: str,
    embedding_model: str,
    ontology_language: str,
    is_anonymous: bool,
) -> None:
    if kg_type not in VALID_KG_TYPES:
        raise PolicyError(f"Bilinmeyen kg_type: {kg_type}")
    if prompt_type not in VALID_PROMPT_TYPES:
        raise PolicyError(f"Bilinmeyen prompt_type: {prompt_type}")
    if embedding_model not in VALID_EMBEDDING_MODELS:
        raise PolicyError(f"Bilinmeyen embedding_model: {embedding_model}")
    if ontology_language not in VALID_ONTOLOGY_LANGUAGES:
        raise PolicyError(f"Bilinmeyen ontology_language: {ontology_language}")
    if not model_registry.is_model_allowed(model, is_anonymous=is_anonymous):
        raise PolicyError(f"Model izin verilenler listesinde değil: {model}")
