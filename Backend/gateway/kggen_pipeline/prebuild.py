import argparse
import asyncio
import os

from .ape import CHAMPION_PATH as APE_CHAMPION_PATH, extract_with_kggen_ape
from .base_prompt import TRAIN_TEXT
from .dspy_pipeline import COMPILED_PATH as DSPY_COMPILED_PATH, extract_with_kggen_dspy
from .runtime import get_openrouter_api_key
from .textgrad_pipeline import CHAMPION_PATH as TEXTGRAD_CHAMPION_PATH, extract_with_kggen_textgrad


DEFAULT_MODEL = "google/gemini-2.5-flash-lite"


async def _maybe_build(label: str, path: str, fn, model: str) -> None:
    if os.path.exists(path):
        print(f"[KG-Gen {label}] cache mevcut, atlanıyor: {os.path.basename(path)}")
        return

    print(f"[KG-Gen {label}] cache yok, optimize ediliyor...")
    triplets = await fn(TRAIN_TEXT, model)
    print(f"[KG-Gen {label}] tamam — {len(triplets)} triplet, cache yazıldı.")


async def main_async(model: str) -> None:
    get_openrouter_api_key()
    await _maybe_build("APE", APE_CHAMPION_PATH, extract_with_kggen_ape, model)
    await _maybe_build("DSPy", DSPY_COMPILED_PATH, extract_with_kggen_dspy, model)
    await _maybe_build("TextGrad", TEXTGRAD_CHAMPION_PATH, extract_with_kggen_textgrad, model)


def main() -> int:
    parser = argparse.ArgumentParser(description="KG-Gen prompt cache pre-builder")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="OpenRouter model adı")
    args = parser.parse_args()

    try:
        asyncio.run(main_async(args.model))
    except Exception as exc:
        print(f"[KG-Gen prebuild] hata: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

