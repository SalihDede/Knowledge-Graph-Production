"""
Yeni şema → uygulama şeması normalizasyonu.

APE / DSPy / TextGrad pipeline'ları şu formatta dönüyor:
  {"triplets":[{subject, relation, object, qualifiers, subject_type, object_type, kaynak_cumle}, ...]}

Uygulama Türkçe anahtarları kullanıyor:
  [{baş, baş_tipi, ilişki, uç, uç_tipi, qualifiers, kaynak_cumle}, ...]
"""

import ast
import json
import re
from typing import Any


def _try_parse(text: str) -> Any:
    """JSON, sonra Python literal — DSPy bazen single-quote dict repr döndürüyor."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return None


def _extract_triplet_list(raw: Any) -> list[dict]:
    """Çeşitli wrapper formatlarını tek bir listeye indirir."""
    if isinstance(raw, str):
        cleaned = re.sub(r"```json\n?|\n?```", "", raw).strip()
        parsed = _try_parse(cleaned)
        if parsed is None:
            match = re.search(r"[\[{].*[\]}]", cleaned, re.DOTALL)
            if match:
                parsed = _try_parse(match.group())
        raw = parsed

    if isinstance(raw, list):
        return [t for t in raw if isinstance(t, dict)]

    if isinstance(raw, dict):
        for value in raw.values():
            if isinstance(value, list):
                return [t for t in value if isinstance(t, dict)]

    return []


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_qualifiers(raw: Any) -> list[dict]:
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        out.append({
            "relation": _stringify(item.get("relation", "")),
            "object":   _stringify(item.get("object", "")),
        })
    return out


def normalize_new_schema(raw: Any) -> list[dict]:
    """
    Pipeline çıktısını uygulama şemasına çevirir.
    Eksik alanlar boş string / boş liste ile doldurulur.
    """
    triplets = _extract_triplet_list(raw)
    normalized = []
    for t in triplets:
        subject = _stringify(t.get("subject", t.get("baş", "")))
        obj     = _stringify(t.get("object",  t.get("uç", "")))
        if not subject or not obj:
            continue
        normalized.append({
            "baş":          subject,
            "baş_tipi":     _stringify(t.get("subject_type", t.get("baş_tipi", ""))),
            "ilişki":       _stringify(t.get("relation",     t.get("ilişki", ""))),
            "uç":           obj,
            "uç_tipi":      _stringify(t.get("object_type",  t.get("uç_tipi", ""))),
            "qualifiers":   _normalize_qualifiers(t.get("qualifiers", [])),
            "kaynak_cumle": _stringify(t.get("kaynak_cumle", "")),
        })
    return normalized
