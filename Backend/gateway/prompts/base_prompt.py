"""
APE / DSPy / TextGrad pipeline'larında ortak kullanılan temel sistem promptu.
Tüm pipeline'lar bu metnin üzerine optimizasyon yapar (kuralları sıkılaştırır).
"""

BASE_PROMPT = """You are an algorithm designed to extract structured knowledge from texts to build a Wikidata-like knowledge graph consisting of triplets (subject, relation, object) and their qualifiers.

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


TRAIN_EXAMPLE_INPUT = (
    "Marie Curie (7 Kasım 1867 - 4 Temmuz 1934) radyoaktivite üzerine öncü "
    "araştırmalar yapmış bir fizikçi ve kimyagerdi. 1903'te Nobel Fizik Ödülü'nü "
    "ve 1911'de Nobel Kimya Ödülü'nü aldı."
)

TRAIN_EXAMPLE_OUTPUT = """{
    "triplets": [
        {"subject": "Marie Curie", "relation": "doğum tarihi", "object": "7 Kasım 1867", "qualifiers": [], "subject_type": "insan", "object_type": "tarih", "kaynak_cumle": "Marie Curie (7 Kasım 1867 - 4 Temmuz 1934) radyoaktivite üzerine öncü araştırmalar yapmış bir fizikçi ve kimyagerdi. 1903'te Nobel Fizik Ödülü'nü ve 1911'de Nobel Kimya Ödülü'nü aldı."},
        {"subject": "Marie Curie", "relation": "ölüm tarihi", "object": "4 Temmuz 1934", "qualifiers": [], "subject_type": "insan", "object_type": "tarih", "kaynak_cumle": "Marie Curie (7 Kasım 1867 - 4 Temmuz 1934) radyoaktivite üzerine öncü araştırmalar yapmış bir fizikçi ve kimyagerdi. 1903'te Nobel Fizik Ödülü'nü ve 1911'de Nobel Kimya Ödülü'nü aldı."},
        {"subject": "Marie Curie", "relation": "meslek", "object": "fizikçi", "qualifiers": [], "subject_type": "insan", "object_type": "meslek", "kaynak_cumle": "Marie Curie (7 Kasım 1867 - 4 Temmuz 1934) radyoaktivite üzerine öncü araştırmalar yapmış bir fizikçi ve kimyagerdi. 1903'te Nobel Fizik Ödülü'nü ve 1911'de Nobel Kimya Ödülü'nü aldı."},
        {"subject": "Marie Curie", "relation": "meslek", "object": "kimyager", "qualifiers": [], "subject_type": "insan", "object_type": "meslek", "kaynak_cumle": "Marie Curie (7 Kasım 1867 - 4 Temmuz 1934) radyoaktivite üzerine öncü araştırmalar yapmış bir fizikçi ve kimyagerdi. 1903'te Nobel Fizik Ödülü'nü ve 1911'de Nobel Kimya Ödülü'nü aldı."},
        {"subject": "Marie Curie", "relation": "çalışma alanı", "object": "radyoaktivite", "qualifiers": [], "subject_type": "insan", "object_type": "fiziksel fenomen", "kaynak_cumle": "Marie Curie (7 Kasım 1867 - 4 Temmuz 1934) radyoaktivite üzerine öncü araştırmalar yapmış bir fizikçi ve kimyagerdi. 1903'te Nobel Fizik Ödülü'nü ve 1911'de Nobel Kimya Ödülü'nü aldı."},
        {"subject": "Marie Curie", "relation": "kazandığı ödül", "object": "Nobel Fizik Ödülü", "qualifiers": [{"relation": "zaman noktası", "object": "1903"}], "subject_type": "insan", "object_type": "ödül", "kaynak_cumle": "Marie Curie (7 Kasım 1867 - 4 Temmuz 1934) radyoaktivite üzerine öncü araştırmalar yapmış bir fizikçi ve kimyagerdi. 1903'te Nobel Fizik Ödülü'nü ve 1911'de Nobel Kimya Ödülü'nü aldı."},
        {"subject": "Marie Curie", "relation": "kazandığı ödül", "object": "Nobel Kimya Ödülü", "qualifiers": [{"relation": "zaman noktası", "object": "1911"}], "subject_type": "insan", "object_type": "ödül", "kaynak_cumle": "Marie Curie (7 Kasım 1867 - 4 Temmuz 1934) radyoaktivite üzerine öncü araştırmalar yapmış bir fizikçi ve kimyagerdi. 1903'te Nobel Fizik Ödülü'nü ve 1911'de Nobel Kimya Ödülü'nü aldı."}
    ]
}"""


TEXTGRAD_TRAIN_TEXTS = [
    TRAIN_EXAMPLE_INPUT,
    "Albert Einstein (14 Mart 1879 - 18 Nisan 1955), görelilik teorisini geliştiren Alman doğumlu teorik fizikçidir. 1921 yılında fotoelektrik etki üzerine çalışmaları nedeniyle Nobel Fizik Ödülü'nü kazanmıştır.",
]
