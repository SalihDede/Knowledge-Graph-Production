"""
DSPy pipeline.

İlk çağrıda BootstrapFewShot ile compile eder ve cache/dspy_compiled.json'a kaydeder.
Sonraki çağrılar yüklenmiş modülü kullanır.

NOT: dspy.settings global state'i mutate eder, bu yüzden LOCKS["dspy"] altında çalışır.
"""

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor

import dspy

from .base_prompt import TRAIN_EXAMPLE_INPUT, TRAIN_EXAMPLE_OUTPUT
from .normalizer import normalize_new_schema
from .runtime import CACHE_DIR, LOCKS, get_openrouter_api_key, get_openrouter_base_url, resolve_model

# DSPy 3.x: dspy.settings.configure() yalnızca initial thread'den çağrılabilir.
# Tüm DSPy çağrılarını tek bir worker thread üzerinden geçiriyoruz.
_DSPY_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dspy-worker")
_lm_configured = False

COMPILED_PATH = os.path.join(CACHE_DIR, "dspy_compiled.json")


class KnowledgeGraphExtraction(dspy.Signature):
    """You are an algorithm designed to extract structured knowledge from texts to build a Wikidata-like knowledge graph consisting of triplets (subject, relation, object) and their qualifiers.

    - **Subject**: A named entity or a concept that describes a group of people, events, or any abstract objects that serves as the source of the relation.
    - **Relation**: A Wikidata-style predicate that connects the subject and object.
    - **Object**: A named entity or a concept that describes a group of people, events, or any abstract objects that is related to the subject.

    Additionally, some triplets may have **qualifiers** that provide more context (e.g., date, place, or other attributes). Qualifiers should have relations and object like triplets do, but instead of subject their relation connects an object and the triplet qualifier belongs to. **Qualifiers must always be attached to a triplet** and never exist as standalone triplets.

    **IMPORTANT NOTE (TURKISH OUTPUT REQUIREMENT):** Regardless of the input text's language, all extracted entities (subject, object), relations, and type labels (subject_type, object_type) MUST BE STRICTLY IN TURKISH. The JSON keys themselves must remain in English.

    STRICT RULES:
    1. The output MUST BE STRICTLY in JSON format containing a "triplets" list.
    2. Each triplet dictionary MUST ONLY contain:
        - "subject": Subject entity.
        - "relation": Relation connecting subject and object.
        - "object": Object entity.
        - "qualifiers": List of dictionaries, where each dictionary contains:
            - "relation": Relation connecting triplet and object,
            - "object": Object entity connected to the main triplet
        - "subject_type": a class that describes the subject
        - "object_type": a class that describes the object
        - "kaynak_cumle": original sentence from the text where this relationship was found
    3. Qualifiers must always be attached to a main triplet and must follow the [{'relation': '...', 'object': '...'}] structure.
    4. **TURKISH LANGUAGE REQUIREMENT:** The JSON keys must remain in English (subject, relation, etc.), BUT all extracted values corresponding to these keys (entities, relations, types) MUST BE STRICTLY IN TURKISH.
    5. NEVER compress the JSON output into a single line! DO NOT use Markdown (```json) blocks. Output pure JSON.
    """
    girdi_metni  = dspy.InputField(desc="The raw text to be analyzed.")
    bilgi_grafigi = dspy.OutputField(desc="A valid, error-free JSON object strictly containing the 'triplets' key.")


_TRAIN_EXAMPLES = [
    dspy.Example(
        girdi_metni=TRAIN_EXAMPLE_INPUT,
        bilgi_grafigi=TRAIN_EXAMPLE_OUTPUT,
    ).with_inputs("girdi_metni")
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
    module = dspy.ChainOfThought(KnowledgeGraphExtraction)

    if os.path.exists(COMPILED_PATH):
        module.load(COMPILED_PATH)
        return module

    optimizer = dspy.teleprompt.BootstrapFewShot(metric=_simple_metric, max_bootstrapped_demos=1)
    compiled = optimizer.compile(module, trainset=_TRAIN_EXAMPLES)
    compiled.save(COMPILED_PATH)
    return compiled


def _run(text: str, model: str) -> list[dict]:
    module = _load_or_compile(model)
    prediction = module(girdi_metni=text)
    raw = getattr(prediction, "bilgi_grafigi", "")
    return normalize_new_schema(raw)


async def extract_with_dspy(text: str, model: str) -> list[dict]:
    resolved_model = resolve_model(model, "dspy")
    async with LOCKS["dspy"]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(_DSPY_EXECUTOR, _run, text, resolved_model)
