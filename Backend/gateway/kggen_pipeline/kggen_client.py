import asyncio
from functools import lru_cache

from kg_gen import KGGen

from .normalizer import normalize_kggen_graph
from .runtime import (
    LOCKS,
    get_openrouter_api_key,
    get_openrouter_base_url,
    resolve_model,
)


@lru_cache(maxsize=8)
def _get_kggen(model: str) -> KGGen:
    return KGGen(
        model=model,
        temperature=0.0,
        max_tokens=8192,
        api_key=get_openrouter_api_key(),
        api_base=get_openrouter_base_url(),
    )


def _run_kggen(text: str, model: str):
    kg = _get_kggen(model)
    return kg.generate(input_data=text)


async def generate_kggen_graph(text: str, model: str):
    resolved_model = resolve_model(model, "kggen")
    async with LOCKS["temel"]:
        return await asyncio.to_thread(_run_kggen, text, resolved_model)


async def extract_with_kggen_temel(text: str, model: str) -> list[dict]:
    graph = await generate_kggen_graph(text, model)
    return normalize_kggen_graph(graph)

