"""
Pre-build CLI: APE / DSPy / TextGrad cache dosyalarını sırayla üretir.

Kullanım:
    python -m prompts.prebuild [--model google/gemini-2.5-flash-lite]

Cache dosyası varsa o pipeline atlanır (idempotent). API key yoksa exit 1.
"""

import argparse
import asyncio
import os
import sys

from . import extract_with_ape, extract_with_dspy, extract_with_textgrad
from .ape import CHAMPION_PATH as APE_CACHE
from .dspy_pipeline import COMPILED_PATH as DSPY_CACHE
from .runtime import get_openrouter_api_key
from .textgrad_pipeline import CHAMPION_PATH as TEXTGRAD_CACHE

DEFAULT_MODEL = "google/gemini-2.5-flash-lite"

WARMUP_TEXT = (
    "Mustafa Kemal Atatürk (1881-1938) Türkiye Cumhuriyeti'nin kurucusu ve "
    "ilk cumhurbaşkanıdır. 1923'te cumhuriyeti ilan etti."
)


def _exists(path: str) -> bool:
    return os.path.exists(path) and os.path.getsize(path) > 0


async def _run(model: str) -> int:
    steps = [
        ("APE",      APE_CACHE,      extract_with_ape),
        ("DSPy",     DSPY_CACHE,     extract_with_dspy),
        ("TextGrad", TEXTGRAD_CACHE, extract_with_textgrad),
    ]
    for name, cache_path, fn in steps:
        if _exists(cache_path):
            print(f"[{name}] cache mevcut, atlanıyor: {os.path.basename(cache_path)}")
            continue
        print(f"[{name}] cache yok, optimize ediliyor... (bu işlem dakikalar sürebilir)")
        triplets = await fn(WARMUP_TEXT, model)
        print(f"[{name}] tamam — {len(triplets)} triplet, cache yazıldı.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Prompt cache pre-builder")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="OpenRouter model adı")
    args = parser.parse_args()

    try:
        get_openrouter_api_key()
    except RuntimeError as exc:
        print(f"HATA: {exc}", file=sys.stderr)
        return 1

    return asyncio.run(_run(args.model))


if __name__ == "__main__":
    sys.exit(main())
