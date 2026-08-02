import json


def build_schema_user_prompt(text: str, raw_triplets: list[dict]) -> str:
    return (
        "Source text:\n"
        f"{text}\n\n"
        "KG-Gen relations:\n"
        f"{json.dumps(raw_triplets, ensure_ascii=False, indent=2)}\n\n"
        "Return the strict JSON output:"
    )

