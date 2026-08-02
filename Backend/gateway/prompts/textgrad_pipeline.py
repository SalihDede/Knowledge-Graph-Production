"""
TextGrad pipeline.

İlk çağrıda BASE_PROMPT'u 'metinsel türev' ile optimize eder ve şampiyonu
cache/textgrad_champion.txt'e yazar. Sonraki çağrılar dosyadan okur.

NOT: TextGrad global engine'i set_backward_engine ile mutate ediyor; LOCKS["textgrad"]
altında çalıştırılır.
"""

import asyncio
import os

import textgrad as tg
from textgrad.engine.openai import ChatOpenAI

from .base_prompt import BASE_PROMPT, TEXTGRAD_TRAIN_TEXTS
from .normalizer import normalize_new_schema
from .runtime import CACHE_DIR, LOCKS, init_textgrad_env, resolve_model

CHAMPION_PATH = os.path.join(CACHE_DIR, "textgrad_champion.txt")


def _make_engine(model: str) -> ChatOpenAI:
    init_textgrad_env()
    return ChatOpenAI(model_string=model, temperature=0.1, max_tokens=8192)


def _optimize(engine: ChatOpenAI) -> str:
    tg.set_backward_engine(engine, override=True)

    system_prompt_var = tg.Variable(
        value=BASE_PROMPT,
        requires_grad=True,
        role_description="The main system prompt instructing the LLM to extract knowledge graph triplets in JSON format.",
    )
    optimizer = tg.TGD(parameters=[system_prompt_var])
    model = tg.BlackboxLLM(engine=engine, system_prompt=system_prompt_var)

    for train_text in TEXTGRAD_TRAIN_TEXTS:
        user_input = tg.Variable(
            value=f"Text: {train_text}\nOutput:",
            requires_grad=False,
            role_description="The raw input text to be analyzed.",
        )
        response = model(user_input)

        evaluation_prompt = (
            f"Carefully review the original input text:\n'{train_text}'\n\n"
            "Now evaluate the model's JSON output based on these STRICT CRITERIA:\n"
            "1. STRICT FORMAT CONTROL: The output must be a valid JSON object containing a 'triplets' list. Each object inside 'triplets' MUST ONLY contain these exact keys: 'subject', 'relation', 'object', 'qualifiers', 'subject_type', 'object_type', 'kaynak_cumle'.\n"
            "2. QUALIFIER STRUCTURE: The 'qualifiers' key must be a list containing objects with ONLY 'relation' and 'object' keys. It must be attached to the correct triplet.\n"
            "3. TURKISH CONTENT REQUIREMENT (Crucial): While the JSON keys MUST be in English, ALL extracted values (entities, relations, types) MUST be strictly in TURKISH. If any value is in English, heavily penalize it.\n"
            "4. COMPREHENSIVENESS: Have all important entities, events, and dates from the original text been successfully extracted?\n\n"
            "If the model violated the key structure, missed qualifiers, or failed the Turkish values rule, provide a strong textual gradient (criticism) instructing the system prompt to enforce these rules more aggressively. Focus only on how the system prompt should be updated."
        )
        loss_evaluator = tg.TextLoss(evaluation_prompt)
        loss = loss_evaluator(response)
        loss.backward()
        optimizer.step()
        optimizer.zero_grad()

    return system_prompt_var.value


def _load_or_build_champion(engine: ChatOpenAI) -> str:
    if os.path.exists(CHAMPION_PATH):
        with open(CHAMPION_PATH, encoding="utf-8") as f:
            return f.read().strip()

    champion = _optimize(engine)
    with open(CHAMPION_PATH, "w", encoding="utf-8") as f:
        f.write(champion)
    return champion


def _run(text: str, model: str) -> list[dict]:
    engine = _make_engine(model)
    champion = _load_or_build_champion(engine)

    prompt_var = tg.Variable(
        value=champion,
        requires_grad=False,
        role_description="The optimized system prompt instructing the LLM.",
    )
    blackbox = tg.BlackboxLLM(engine=engine, system_prompt=prompt_var)
    user_input = tg.Variable(
        value=f"Text: {text}\nOutput:",
        requires_grad=False,
        role_description="The raw input text to be analyzed.",
    )
    response = blackbox(user_input)
    return normalize_new_schema(response.value)


async def extract_with_textgrad(text: str, model: str) -> list[dict]:
    resolved_model = resolve_model(model, "openai")
    async with LOCKS["textgrad"]:
        return await asyncio.to_thread(_run, text, resolved_model)
