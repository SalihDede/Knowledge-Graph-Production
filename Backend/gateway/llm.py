"""
OpenRouter üzerinden LLM çağrısı yapar ve triplet listesi döndürür.
Sistem promptu backend/wikipedia/systemPrompt.jsonl'den yüklenir.
"""

import json
import os
import re

import httpx
from dotenv import dotenv_values, find_dotenv, load_dotenv

load_dotenv(find_dotenv())

BASE_DIR = os.path.dirname(__file__)
PROJECT_DIR = os.path.dirname(BASE_DIR)


def _is_missing(value: str | None) -> bool:
    return not value or value.strip() in {
        "",
        "your_openrouter_api_key_here",
        "your_openrouter_api_key",
    }


def _get_env(name: str, default: str = "") -> str:
    """Read env values, falling back to project .env when backend/.env is a template."""
    candidates = [
        os.getenv(name),
        dotenv_values(os.path.join(BASE_DIR, ".env")).get(name),
        dotenv_values(os.path.join(PROJECT_DIR, ".env")).get(name),
    ]
    for value in candidates:
        if not _is_missing(value):
            return str(value).strip()
    return default


BASE_URL = _get_env("LLM_BASE_ADDRESS", "https://openrouter.ai/api/v1").rstrip("/")
API_KEY  = _get_env("OPENROUTER_API_KEY")


def _load_system_prompt() -> str:
    path = os.path.join(os.path.dirname(__file__), "wikipedia", "systemPrompt.jsonl")
    ns: dict = {}
    with open(path, encoding="utf-8") as f:
        exec(f.read(), ns)          # dosya Python scripti olduğu için exec
    return ns.get("system_prompt_tr", "")


SYSTEM_PROMPT = _load_system_prompt()


def _parse_triplets(raw: str) -> list[dict]:
    """LLM yanıtından JSON triplet listesini çıkarır."""
    # Önce direkt parse dene
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return parsed
        # {"triplets": [...]} gibi sarmalı aç
        for v in parsed.values():
            if isinstance(v, list):
                return v
    except json.JSONDecodeError:
        pass

    # JSON bloğunu metinden bul
    match = re.search(r'\[.*\]', raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return []


async def extract_triplets(text: str, model: str) -> list[dict]:
    """
    Verilen metinden bilgi grafı tripletlerini çıkarır.

    Returns
    -------
    [{"baş": ..., "baş_tipi": ..., "ilişki": ..., "uç": ..., "uç_tipi": ...}, ...]
    """
    if _is_missing(API_KEY):
        raise RuntimeError(
            "OpenRouter API key is missing. Set OPENROUTER_API_KEY in backend/.env or project .env."
        )

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:5173",
        "X-Title":      "SDP Knowledge Graph",
    }

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": text},
        ],
    }

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{BASE_URL}/chat/completions",
            json=payload,
            headers=headers,
        )
        resp.raise_for_status()

    raw = resp.json()["choices"][0]["message"]["content"]
    return _parse_triplets(raw)
