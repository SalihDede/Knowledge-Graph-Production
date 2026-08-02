import json

TRAIN_TEXT = "Mustafa Kemal Atatürk (1881-1938) Türkiye Cumhuriyeti kurucusudur."
TRAIN_RELATIONS = [
    {
        "subject": "Mustafa Kemal Atatürk",
        "relation": "founded",
        "object": "Republic of Turkey",
    }
]
TRAIN_OUTPUT = {
    "triplets": [
        {
            "subject": "Mustafa Kemal Atatürk",
            "relation": "kurucusu",
            "object": "Türkiye Cumhuriyeti",
            "qualifiers": [
                {"relation": "doğum tarihi", "object": "1881"},
                {"relation": "ölüm tarihi", "object": "1938"},
            ],
            "subject_type": "Kişi",
            "object_type": "Devlet",
            "kaynak_cumle": TRAIN_TEXT,
        }
    ]
}

TRAIN_RELATIONS_JSON = json.dumps(TRAIN_RELATIONS, ensure_ascii=False, indent=2)
TRAIN_OUTPUT_JSON = json.dumps(TRAIN_OUTPUT, ensure_ascii=False, indent=2)

BASE_PROMPT = f"""You convert KG-Gen relation tuples into the application's strict knowledge graph JSON schema.

You receive:
1. The original source text.
2. A list of relation tuples extracted by KG-Gen.

Your job:
- Keep only relations that are supported by the source text.
- Convert all extracted values to Turkish.
- Enrich the KG-Gen tuples with subject_type, object_type, qualifiers, and kaynak_cumle when the source text supports them.
- Do not invent facts that are not in the source text.

STRICT OUTPUT FORMAT:
Return only a valid JSON object with this shape:
{{
  "triplets": [
    {{
      "subject": "...",
      "relation": "...",
      "object": "...",
      "qualifiers": [{{"relation": "...", "object": "..."}}],
      "subject_type": "...",
      "object_type": "...",
      "kaynak_cumle": "..."
    }}
  ]
}}

Rules:
1. JSON keys must remain exactly in English.
2. Values for subject, relation, object, subject_type, object_type, and qualifiers must be in Turkish.
3. Always include the qualifiers key. Use [] if no qualifier exists.
4. kaynak_cumle must be the exact source sentence from the original text when possible. Use "" only if no exact sentence can be identified.
5. Do not use Markdown fences. Do not add commentary.

Example:
Source text:
{TRAIN_TEXT}

KG-Gen relations:
{TRAIN_RELATIONS_JSON}

Output:
{TRAIN_OUTPUT_JSON}
"""

