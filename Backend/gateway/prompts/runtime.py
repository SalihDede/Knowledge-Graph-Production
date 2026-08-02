"""
APE / DSPy / TextGrad pipeline'ları için ortak runtime yardımcıları.

- Cache klasörü
- OpenRouter API anahtarı (llm.py ile aynı fallback mantığı)
- Model adı çözümleme (openai vs litellm/dspy formatı)
- Concurrency lock'ları (DSPy/TextGrad global state'i mutate ediyor)
- TextGrad environment init (OPENAI_API_KEY / OPENAI_BASE_URL)
"""

import asyncio
import os
from typing import Literal

from dotenv import dotenv_values, find_dotenv, load_dotenv

load_dotenv(find_dotenv())

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR    = os.path.dirname(__file__)
BACKEND_DIR = os.path.dirname(BASE_DIR)
PROJECT_DIR = os.path.dirname(BACKEND_DIR)
CACHE_DIR   = os.path.join(BASE_DIR, "cache")
os.makedirs(CACHE_DIR, exist_ok=True)


# ── API key resolution (llm.py ile aynı üçlü fallback) ────────────────────────
_PLACEHOLDER_VALUES = {
    "",
    "your_openrouter_api_key_here",
    "your_openrouter_api_key",
}


def _is_missing(value: str | None) -> bool:
    return not value or value.strip() in _PLACEHOLDER_VALUES


def _read_env(name: str, default: str = "") -> str:
    """os.environ → backend/.env → proje/.env sırasıyla okur, placeholder atlanır."""
    candidates = [
        os.getenv(name),
        dotenv_values(os.path.join(BACKEND_DIR, ".env")).get(name),
        dotenv_values(os.path.join(PROJECT_DIR, ".env")).get(name),
    ]
    for value in candidates:
        if not _is_missing(value):
            return str(value).strip()
    return default


def get_openrouter_api_key() -> str:
    key = _read_env("OPENROUTER_API_KEY")
    if _is_missing(key):
        raise RuntimeError(
            "OpenRouter API key is missing. Set OPENROUTER_API_KEY in backend/.env or project .env."
        )
    return key


def get_openrouter_base_url() -> str:
    return _read_env("LLM_BASE_ADDRESS", "https://openrouter.ai/api/v1").rstrip("/")


# ── Model name resolution ─────────────────────────────────────────────────────
def resolve_model(user_model: str, target: Literal["openai", "dspy"]) -> str:
    """
    DSPy/TextGrad litellm üzerinden çalıştığı için 'openrouter/' prefix ister.
    OpenAI SDK doğrudan model adını kabul eder.
    """
    if target == "dspy":
        if user_model.startswith("openrouter/"):
            return user_model
        return f"openrouter/{user_model}"
    return user_model


# ── Concurrency locks ─────────────────────────────────────────────────────────
LOCKS: dict[str, asyncio.Lock] = {
    "ape": asyncio.Lock(),
    "dspy": asyncio.Lock(),
    "textgrad": asyncio.Lock(),
}


# ── TextGrad env (idempotent) ─────────────────────────────────────────────────
_textgrad_env_initialized = False


def init_textgrad_env() -> None:
    """TextGrad litellm üzerinden OpenAI-compatible endpoint kullanır."""
    global _textgrad_env_initialized
    if _textgrad_env_initialized:
        return
    os.environ["OPENAI_API_KEY"] = get_openrouter_api_key()
    os.environ["OPENAI_BASE_URL"] = get_openrouter_base_url()
    _textgrad_env_initialized = True
