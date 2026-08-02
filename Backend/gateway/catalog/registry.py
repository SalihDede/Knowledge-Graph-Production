from __future__ import annotations

import json
import os

GATEWAY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS_FILE = os.path.join(GATEWAY_DIR, "allowedOpenroutherLLMModels.json")

_DEFAULT_ANONYMOUS_MODELS = frozenset({"google/gemini-2.5-flash-lite"})


def _parse_allowlist(value: str | None) -> frozenset[str] | None:
    if not value or not value.strip():
        return None
    return frozenset(item.strip() for item in value.split(",") if item.strip())


def load_models() -> list[dict]:
    with open(MODELS_FILE, encoding="utf-8") as f:
        return json.load(f)


def allowed_model_ids() -> frozenset[str]:
    return frozenset(entry["id"] for entry in load_models())


def anonymous_model_ids() -> frozenset[str]:
    configured = _parse_allowlist(os.getenv("ANONYMOUS_MODEL_ALLOWLIST")) or _DEFAULT_ANONYMOUS_MODELS
    # Never let a misconfigured env var grant anonymous access to a model
    # that isn't even in the full catalog.
    return configured & allowed_model_ids()


def is_model_allowed(model_id: str, *, is_anonymous: bool) -> bool:
    if is_anonymous:
        return model_id in anonymous_model_ids()
    return model_id in allowed_model_ids()
