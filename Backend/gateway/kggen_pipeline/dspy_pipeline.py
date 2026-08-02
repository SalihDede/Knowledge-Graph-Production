import asyncio
import os
from concurrent.futures import ThreadPoolExecutor

import dspy

from prompts.normalizer import normalize_new_schema

from .base_prompt import BASE_PROMPT, TRAIN_OUTPUT_JSON, TRAIN_RELATIONS_JSON, TRAIN_TEXT
from .kggen_client import extract_with_kggen_temel
from .normalizer import normalize_app_schema
from .runtime import CACHE_DIR, LOCKS, get_openrouter_api_key, get_openrouter_base_url, resolve_model

COMPILED_PATH = os.path.join(CACHE_DIR, "kggen_dspy_compiled.json")
_DSPY_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="kggen-dspy-worker")
_lm_configured = False


class KGGenSchemaConversion(dspy.Signature):
    """Convert KG-Gen relation tuples into strict JSON.

    Use these rules:
    - Keep only source-supported relations.
    - Convert extracted values to Turkish.
    - Add subject_type, object_type, qualifiers, and kaynak_cumle when supported.
    - Return only valid JSON with a triplets list.

    Full rules:
    {BASE_PROMPT}
    """

    kaynak_metin = dspy.InputField(desc="Original source text.")
    kggen_iliskiler = dspy.InputField(desc="KG-Gen relations as JSON.")
    bilgi_grafigi = dspy.OutputField(desc="Valid JSON object with a triplets list.")


_TRAIN_EXAMPLES = [
    dspy.Example(
        kaynak_metin=TRAIN_TEXT,
        kggen_iliskiler=TRAIN_RELATIONS_JSON,
        bilgi_grafigi=TRAIN_OUTPUT_JSON,
    ).with_inputs("kaynak_metin", "kggen_iliskiler")
]


def _simple_metric(example, prediction, trace=None) -> bool:
    output = getattr(prediction, "bilgi_grafigi", "") or ""
    required = ["triplets", "subject", "relation", "object", "qualifiers", "kaynak_cumle"]
    return all(key in output for key in required)


def _configure_lm(model: str) -> None:
    global _lm_configured
    if _lm_configured:
        return
    lm = dspy.LM(
        api_base=get_openrouter_base_url(),
        api_key=get_openrouter_api_key(),
        model=model,
        max_tokens=8192,
        temperature=0.1,
    )
    dspy.settings.configure(lm=lm)
    _lm_configured = True


def _load_or_compile(model: str) -> dspy.Module:
    _configure_lm(model)
    module = dspy.ChainOfThought(KGGenSchemaConversion)

    if os.path.exists(COMPILED_PATH):
        module.load(COMPILED_PATH)
        return module

    optimizer = dspy.teleprompt.BootstrapFewShot(metric=_simple_metric, max_bootstrapped_demos=1)
    compiled = optimizer.compile(module, trainset=_TRAIN_EXAMPLES)
    compiled.save(COMPILED_PATH)
    return compiled


def _run(text: str, raw_triplets: list[dict], model: str) -> list[dict]:
    import json

    module = _load_or_compile(model)
    prediction = module(
        kaynak_metin=text,
        kggen_iliskiler=json.dumps(raw_triplets, ensure_ascii=False, indent=2),
    )
    raw = getattr(prediction, "bilgi_grafigi", "")
    return normalize_new_schema(raw)


async def extract_with_kggen_dspy(text: str, model: str) -> list[dict]:
    raw_triplets = await extract_with_kggen_temel(text, model)
    resolved_model = resolve_model(model, "dspy")
    async with LOCKS["dspy"]:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(_DSPY_EXECUTOR, _run, text, raw_triplets, resolved_model)
    return normalize_app_schema(result)

