import asyncio
import os
import re

from openai import OpenAI

from prompts.normalizer import normalize_new_schema

from .base_prompt import BASE_PROMPT, TRAIN_OUTPUT_JSON, TRAIN_RELATIONS_JSON, TRAIN_TEXT
from .kggen_client import extract_with_kggen_temel
from .normalizer import normalize_app_schema
from .runtime import CACHE_DIR, LOCKS, get_openrouter_api_key, get_openrouter_base_url, resolve_model
from .schema_prompt import build_schema_user_prompt

CHAMPION_PATH = os.path.join(CACHE_DIR, "kggen_ape_champion.txt")

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            base_url=get_openrouter_base_url(),
            api_key=get_openrouter_api_key(),
        )
    return _client


def _call_llm(system_prompt: str, user_prompt: str, model: str, temperature: float = 0.1) -> str:
    response = _get_client().chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        max_tokens=8192,
    )
    return response.choices[0].message.content or ""


def _generate_candidates(model: str, num_candidates: int = 3) -> list[str]:
    proposal = f"""You are an expert prompt engineer. Improve this system prompt for converting KG-Gen relation tuples into strict JSON.

Base prompt:
---
{BASE_PROMPT}
---

Training input:
Source text:
{TRAIN_TEXT}

KG-Gen relations:
{TRAIN_RELATIONS_JSON}

Ideal output:
{TRAIN_OUTPUT_JSON}

Write {num_candidates} candidate system prompts. Keep all instructions in English, but enforce Turkish values in the JSON output.

Output strictly:
Candidate 1: ...
Candidate 2: ...
Candidate 3: ...
"""
    response = _get_client().chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": proposal}],
        temperature=0.7,
        max_tokens=8192,
    )
    content = response.choices[0].message.content or ""
    raw = re.split(r"Candidate \d+:", content)
    candidates = [item.strip() for item in raw if item.strip()]
    return candidates[:num_candidates]


def _score_candidate(candidate: str, model: str) -> float:
    output = _call_llm(
        candidate,
        build_schema_user_prompt(TRAIN_TEXT, [
            {"baş": "Mustafa Kemal Atatürk", "ilişki": "founded", "uç": "Republic of Turkey"}
        ]),
        model,
    )
    evaluation = f"""Score this KG-Gen schema conversion output from 0 to 100.

Expected properties:
- Valid JSON with a triplets list.
- Contains subject, relation, object, qualifiers, subject_type, object_type, kaynak_cumle.
- Values are Turkish.
- Does not invent unsupported facts.
- Captures birth/death years as qualifiers when present in source text.

Output:
{output}

Return only a number."""
    response = _get_client().chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": evaluation}],
        temperature=0.1,
        max_tokens=20,
    )
    raw = (response.choices[0].message.content or "").strip()
    try:
        return float(raw)
    except ValueError:
        return 0.0


def _build_or_load_champion(model: str) -> str:
    if os.path.exists(CHAMPION_PATH):
        with open(CHAMPION_PATH, encoding="utf-8") as f:
            return f.read().strip()

    candidates = _generate_candidates(model)
    champion = BASE_PROMPT
    best_score = -1.0
    for candidate in candidates or [BASE_PROMPT]:
        score = _score_candidate(candidate, model)
        if score > best_score:
            champion = candidate
            best_score = score

    with open(CHAMPION_PATH, "w", encoding="utf-8") as f:
        f.write(champion)
    return champion


async def extract_with_kggen_ape(text: str, model: str) -> list[dict]:
    raw_triplets = await extract_with_kggen_temel(text, model)
    resolved_model = resolve_model(model, "openai")

    async with LOCKS["ape"]:
        champion = await asyncio.to_thread(_build_or_load_champion, resolved_model)
        raw = await asyncio.to_thread(
            _call_llm,
            champion,
            build_schema_user_prompt(text, raw_triplets),
            resolved_model,
        )
    return normalize_app_schema(normalize_new_schema(raw))
