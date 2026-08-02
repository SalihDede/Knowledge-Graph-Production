import asyncio
import os

import textgrad as tg
from textgrad.engine.openai import ChatOpenAI

from prompts.normalizer import normalize_new_schema

from .base_prompt import BASE_PROMPT, TRAIN_RELATIONS_JSON, TRAIN_TEXT
from .kggen_client import extract_with_kggen_temel
from .normalizer import normalize_app_schema
from .runtime import CACHE_DIR, LOCKS, init_textgrad_env, resolve_model
from .schema_prompt import build_schema_user_prompt

CHAMPION_PATH = os.path.join(CACHE_DIR, "kggen_textgrad_champion.txt")


def _make_engine(model: str) -> ChatOpenAI:
    init_textgrad_env()
    return ChatOpenAI(model_string=model, temperature=0.1, max_tokens=8192)


def _optimize(engine: ChatOpenAI) -> str:
    tg.set_backward_engine(engine, override=True)

    system_prompt_var = tg.Variable(
        value=BASE_PROMPT,
        requires_grad=True,
        role_description="System prompt for converting KG-Gen relations into strict Turkish JSON schema.",
    )
    optimizer = tg.TGD(parameters=[system_prompt_var])
    model = tg.BlackboxLLM(engine=engine, system_prompt=system_prompt_var)

    user_input = tg.Variable(
        value=(
            f"Source text:\n{TRAIN_TEXT}\n\n"
            f"KG-Gen relations:\n{TRAIN_RELATIONS_JSON}\n\n"
            "Return the strict JSON output:"
        ),
        requires_grad=False,
        role_description="Training input for KG-Gen schema conversion.",
    )
    response = model(user_input)

    evaluation_prompt = (
        "Evaluate the JSON schema conversion output. Penalize invalid JSON, missing keys, "
        "non-Turkish values, unsupported hallucinations, missing qualifiers, and missing kaynak_cumle. "
        "Give textual gradient instructions that improve the system prompt."
    )
    loss = tg.TextLoss(evaluation_prompt)(response)
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


def _run(text: str, raw_triplets: list[dict], model: str) -> list[dict]:
    engine = _make_engine(model)
    champion = _load_or_build_champion(engine)

    prompt_var = tg.Variable(
        value=champion,
        requires_grad=False,
        role_description="Optimized KG-Gen schema conversion prompt.",
    )
    blackbox = tg.BlackboxLLM(engine=engine, system_prompt=prompt_var)
    user_input = tg.Variable(
        value=build_schema_user_prompt(text, raw_triplets),
        requires_grad=False,
        role_description="Source text plus KG-Gen relations.",
    )
    response = blackbox(user_input)
    return normalize_new_schema(response.value)


async def extract_with_kggen_textgrad(text: str, model: str) -> list[dict]:
    raw_triplets = await extract_with_kggen_temel(text, model)
    resolved_model = resolve_model(model, "openai")
    async with LOCKS["textgrad"]:
        result = await asyncio.to_thread(_run, text, raw_triplets, resolved_model)
    return normalize_app_schema(result)

