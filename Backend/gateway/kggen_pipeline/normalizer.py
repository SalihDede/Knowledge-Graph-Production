from collections.abc import Iterable
from typing import Any


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_qualifiers(value: Any) -> list[dict]:
    if not isinstance(value, list):
        return []

    qualifiers: list[dict] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        relation = _as_text(item.get("relation") or item.get("ilişki"))
        obj = _as_text(item.get("object") or item.get("uç"))
        if relation or obj:
            qualifiers.append({"relation": relation, "object": obj})
    return qualifiers


def normalize_triplet_dict(row: dict) -> dict:
    return {
        "baş": _as_text(row.get("baş") or row.get("subject")),
        "baş_tipi": _as_text(row.get("baş_tipi") or row.get("subject_type")),
        "ilişki": _as_text(row.get("ilişki") or row.get("relation")),
        "uç": _as_text(row.get("uç") or row.get("object")),
        "uç_tipi": _as_text(row.get("uç_tipi") or row.get("object_type")),
        "qualifiers": _normalize_qualifiers(row.get("qualifiers")),
        "kaynak_cumle": _as_text(row.get("kaynak_cumle") or row.get("source_sentence")),
    }


def normalize_kggen_graph(graph: Any) -> list[dict]:
    relations = getattr(graph, "relations", None)
    if relations is None and isinstance(graph, dict):
        relations = graph.get("relations")
    if not isinstance(relations, Iterable):
        return []

    triplets: list[dict] = []
    for relation in relations:
        if not isinstance(relation, (list, tuple)) or len(relation) != 3:
            continue
        subject, predicate, obj = relation
        row = {
            "baş": _as_text(subject),
            "baş_tipi": "",
            "ilişki": _as_text(predicate),
            "uç": _as_text(obj),
            "uç_tipi": "",
            "qualifiers": [],
            "kaynak_cumle": "",
        }
        if row["baş"] and row["ilişki"] and row["uç"]:
            triplets.append(row)
    return triplets


def normalize_app_schema(rows: Any) -> list[dict]:
    if isinstance(rows, dict):
        rows = rows.get("triplets", [])
    if not isinstance(rows, list):
        return []

    triplets: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        item = normalize_triplet_dict(row)
        if item["baş"] and item["ilişki"] and item["uç"]:
            triplets.append(item)
    return triplets

