import asyncio
import os
from typing import Literal

from prompts.runtime import (
    get_openrouter_api_key,
    get_openrouter_base_url,
    init_textgrad_env,
)

PACKAGE_DIR = os.path.dirname(__file__)
CACHE_DIR = os.path.join(PACKAGE_DIR, "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

LOCKS: dict[str, asyncio.Lock] = {
    "temel": asyncio.Lock(),
    "ape": asyncio.Lock(),
    "dspy": asyncio.Lock(),
    "textgrad": asyncio.Lock(),
}


def resolve_model(user_model: str, target: Literal["openai", "dspy", "kggen"]) -> str:
    model = (user_model or "").strip()
    if not model:
        raise RuntimeError("Model adı boş olamaz.")

    if target == "openai":
        return model

    if model.startswith("openrouter/"):
        return model
    return f"openrouter/{model}"

