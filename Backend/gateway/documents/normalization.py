from __future__ import annotations

import hashlib
import json
import re
import unicodedata

_TRAILING_WHITESPACE = re.compile(r"[ \t]+\n")
_BLANK_LINE_RUNS = re.compile(r"\n{3,}")

PIPELINE_VERSION = "v1"


def normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFC", text)
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = _TRAILING_WHITESPACE.sub("\n", normalized)
    normalized = _BLANK_LINE_RUNS.sub("\n\n", normalized)
    return normalized.strip()


def compute_content_hash(normalized_text: str) -> str:
    return hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()


def compute_pipeline_fingerprint(
    *,
    kg_type: str,
    prompt_type: str,
    embedding_model: str,
    ontology_language: str,
    model: str,
    pipeline_version: str = PIPELINE_VERSION,
) -> str:
    payload = {
        "version": pipeline_version,
        "kg_type": kg_type,
        "prompt_type": prompt_type,
        "embedding_model": embedding_model,
        "ontology_language": ontology_language,
        "model": model,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
