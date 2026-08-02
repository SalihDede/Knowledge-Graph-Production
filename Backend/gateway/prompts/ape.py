"""
APE (Automatic Prompt Engineer) pipeline.

İlk çağrıda BASE_PROMPT üzerine 3 aday türetir, hakem LLM ile puanlar,
şampiyonu cache/ape_champion.txt'e yazar. Sonraki çağrılar dosyadan okur.
"""

import asyncio
import os
import re

from openai import OpenAI

from .base_prompt import BASE_PROMPT, TRAIN_EXAMPLE_INPUT, TRAIN_EXAMPLE_OUTPUT
from .normalizer import normalize_new_schema
from .runtime import CACHE_DIR, LOCKS, get_openrouter_api_key, get_openrouter_base_url, resolve_model

CHAMPION_PATH = os.path.join(CACHE_DIR, "ape_champion.txt")

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            base_url=get_openrouter_base_url(),
            api_key=get_openrouter_api_key(),
        )
    return _client


def _call_llm(system_prompt: str, user_text: str, model: str, temperature: float = 0.1) -> str:
    response = _get_client().chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": f"Text: {user_text}\nOutput:"},
        ],
        temperature=temperature,
    )
    return response.choices[0].message.content or ""


def _generate_candidates(model: str, num_candidates: int = 3) -> list[str]:
    examples_str = f"Example 1:\nInput: {TRAIN_EXAMPLE_INPUT}\nOutput: {TRAIN_EXAMPLE_OUTPUT}\n\n"
    proposal = f"""You are an expert Prompt Engineer. Your task is to OPTIMIZE and IMPROVE a base system prompt to ensure it perfectly transforms text inputs into desired JSON knowledge graphs.

Here is the Base Prompt provided by the user:
---
{BASE_PROMPT}
---

Review the following ideal input-output examples that the final prompt must be able to generate perfectly:
{examples_str}

Please act as an optimizer. Write {num_candidates} different candidate system prompts that improve upon the Base Prompt. Make the rules stricter, clearer, and more robust to prevent any LLM hallucinations. All instructions in your candidate prompts MUST be written in English. Ensure the "TURKISH OUTPUT REQUIREMENT" is heavily emphasized in your candidates.

Make sure to EXPLICITLY instruct the model in your candidate prompts to ALWAYS output the "qualifiers" key. Tell the model: 'If there are no qualifiers, you MUST still include the "qualifiers" key with an empty list [].'

Output your response strictly in the following format:
Candidate 1: [Improved Prompt text]
Candidate 2: [Improved Prompt text]
"""
    response = _get_client().chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": proposal}],
        temperature=0.7,
    )
    content = response.choices[0].message.content or ""
    raw = re.split(r"Candidate \d+:", content)
    candidates = [c.strip() for c in raw if c.strip()]
    return candidates[:num_candidates]


def _score_candidate(candidate: str, model: str, test_input: str) -> float:
    output = _call_llm(candidate, test_input, model)

    evaluation = f"""You are evaluating a knowledge graph extraction system.

Input Text: {test_input}
System Output: {output}

Rules for Evaluation:
1. Is the output strictly a valid JSON object containing a "triplets" list?
2. Are all required keys present: 'subject', 'relation', 'object', 'qualifiers', 'subject_type', 'object_type', 'kaynak_cumle'?
3. Are ALL extracted values (entities, relations, types) strictly in Turkish? (Keys must be English).
4. Are all details from the input text comprehensively extracted?
5. Are the relations logical verbs or phrases?

Based on these rules, give the system output a score between 0 and 100. Your output MUST BE ONLY A NUMBER. Do not write any other explanation."""

    eval_response = _get_client().chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": evaluation}],
        temperature=0.1,
        max_tokens=8192,
    )
    raw = (eval_response.choices[0].message.content or "").strip()
    try:
        return float(raw)
    except ValueError:
        return 0.0


def _build_or_load_champion(model: str, target_text: str) -> str:
    if os.path.exists(CHAMPION_PATH):
        with open(CHAMPION_PATH, encoding="utf-8") as f:
            return f.read().strip()

    candidates = _generate_candidates(model, num_candidates=3)
    if not candidates:
        champion = BASE_PROMPT
    else:
        champion = candidates[0]
        best_score = 0.0
        for cand in candidates:
            score = _score_candidate(cand, model, target_text)
            if score > best_score:
                best_score = score
                champion = cand

    with open(CHAMPION_PATH, "w", encoding="utf-8") as f:
        f.write(champion)
    return champion


def _run(text: str, model: str) -> list[dict]:
    target_text = text or TRAIN_EXAMPLE_INPUT
    champion = _build_or_load_champion(model, target_text)
    raw = _call_llm(champion, text, model)
    return normalize_new_schema(raw)


async def extract_with_ape(text: str, model: str) -> list[dict]:
    resolved_model = resolve_model(model, "openai")
    async with LOCKS["ape"]:
        return await asyncio.to_thread(_run, text, resolved_model)
