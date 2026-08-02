import json
import logging
import os
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, field_validator
from dotenv import load_dotenv

load_dotenv()

from accounts import install_accounts
from accounts.setup import accounts_ready
from gateway_middleware import (
    MiddlewareSettings,
    install_error_handlers,
    install_platform_middleware,
)
from gateway_middleware.context import request_id_context
from visualization import build_graph_html, build_source_graph_html
from llm import extract_triplets
from prompts import extract_with_ape, extract_with_dspy, extract_with_textgrad
from kggen_pipeline import (
    extract_with_kggen_ape,
    extract_with_kggen_dspy,
    extract_with_kggen_temel,
    extract_with_kggen_textgrad,
)

logger = logging.getLogger(__name__)
middleware_settings = MiddlewareSettings.from_env()
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(middleware_settings.allowed_origins),
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    allow_credentials=True,
)

install_accounts(app)
install_error_handlers(app)
install_platform_middleware(app, middleware_settings)

BASE_DIR       = os.path.dirname(__file__)
MODELS_FILE    = os.path.join(BASE_DIR, "allowedOpenroutherLLMModels.json")
WIKONTIC_URL   = os.getenv("WIKONTIC_URL", "http://localhost:8001")
WIKONTIC_TIMEOUT_SECONDS = float(os.getenv("WIKONTIC_TIMEOUT_SECONDS", "170"))


def _response_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text or response.reason_phrase
    if isinstance(payload, dict):
        return str(payload.get("detail") or payload)
    return str(payload)


@app.get("/api/health/live")
def live():
    return {"status": "ok", "service": "backend"}


@app.get("/api/health/ready")
async def ready():
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            response = await client.get(f"{WIKONTIC_URL}/health/ready")
        if not response.is_success:
            raise HTTPException(status_code=503, detail="Wikontic is unavailable")
    except HTTPException:
        raise
    except httpx.HTTPError as exc:
        logger.warning("Wikontic readiness check failed: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Wikontic is unavailable") from exc
    try:
        if not await accounts_ready(app):
            raise HTTPException(status_code=503, detail="Account services are unavailable")
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Account readiness check failed: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Account services are unavailable") from exc
    return {"status": "ok", "service": "backend", "wikontic": "ready"}


# ── Models ────────────────────────────────────────────────────────────────────

@app.get("/api/models")
def get_models():
    with open(MODELS_FILE, encoding="utf-8") as f:
        return json.load(f)


# ── Extraction ────────────────────────────────────────────────────────────────

class ExtractRequest(BaseModel):
    text:            str
    model:           str
    prompt_type:     str = "temel"      # temel | ape | dspy | textgrad
    kg_type:         str = "wikipedia"  # wikipedia | wicontic | kggen
    embedding_model: str = "contriever" # contriever | bge_m3 | turkish_e5_large | turkish_sbert_mean_nli_stsb | mft_random
    ontology_language: str = "en"       # en | tr

    @field_validator("text")
    @classmethod
    def reject_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Metin boş olamaz")
        return value


async def _extract_wikontic(
    text: str,
    llm_model: str,
    embedding_model: str,
    ontology_language: str,
    prompt_type: str = "temel",
) -> list[dict]:
    """Calls the Wikontic service and normalises response to the app's Turkish field names."""
    payload = {
        "text":              text,
        "embedding_model":   embedding_model,
        "llm_model":         llm_model,
        "ontology_language": ontology_language,
        "prompt_type":       prompt_type,
    }
    try:
        async with httpx.AsyncClient(timeout=WIKONTIC_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{WIKONTIC_URL}/extract",
                json=payload,
                headers={"X-Request-ID": request_id_context.get()},
            )
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="Wikontic isteği zaman aşımına uğradı") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Wikontic servisine ulaşılamadı") from exc

    if not resp.is_success:
        upstream_status = resp.status_code
        public_status = upstream_status if upstream_status in {400, 401, 403, 404, 409, 422, 503} else 502
        raise HTTPException(status_code=public_status, detail=_response_detail(resp))

    raw_triplets = resp.json().get("triplets", [])

    # Map Wikontic field names → app field names
    normalised = []
    for t in raw_triplets:
        normalised.append({
            "baş":      t.get("subject", ""),
            "baş_tipi": t.get("subject_type", ""),
            "ilişki":   t.get("relation", ""),
            "uç":       t.get("object", ""),
            "uç_tipi":  t.get("object_type", ""),
            "qualifiers": t.get("qualifiers", []),
            "kaynak_cumle": t.get("kaynak_cumle", ""),
        })
    return normalised


@app.post("/api/extract")
async def extract(body: ExtractRequest):
    try:
        if body.kg_type == "wicontic":
            triplets = await _extract_wikontic(
                body.text,
                body.model,
                body.embedding_model,
                body.ontology_language,
                body.prompt_type,
            )
        elif body.kg_type == "wikipedia":
            if body.prompt_type == "ape":
                triplets = await extract_with_ape(body.text, body.model)
            elif body.prompt_type == "dspy":
                triplets = await extract_with_dspy(body.text, body.model)
            elif body.prompt_type == "textgrad":
                triplets = await extract_with_textgrad(body.text, body.model)
            else:
                triplets = await extract_triplets(body.text, body.model)
        elif body.kg_type == "kggen":
            if body.prompt_type == "ape":
                triplets = await extract_with_kggen_ape(body.text, body.model)
            elif body.prompt_type == "dspy":
                triplets = await extract_with_kggen_dspy(body.text, body.model)
            elif body.prompt_type == "textgrad":
                triplets = await extract_with_kggen_textgrad(body.text, body.model)
            else:
                triplets = await extract_with_kggen_temel(body.text, body.model)
        else:
            raise HTTPException(status_code=400, detail=f"Bilinmeyen kg_type: {body.kg_type}")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Extraction request failed: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Triple çıkarma işlemi tamamlanamadı") from exc

    # Baş varlıkları highlight olarak döndür
    highlight = list({t.get("baş", "") for t in triplets if t.get("baş")})
    return {"triplets": triplets, "highlight": highlight}


# ── Visualization ─────────────────────────────────────────────────────────────

class Triple(BaseModel):
    baş:          str
    baş_tipi:     str = ""
    ilişki:       str
    uç:           str
    uç_tipi:      str = ""
    qualifiers:   list[dict] = []
    kaynak_cumle: str = ""


class VisualizeRequest(BaseModel):
    triplets: list[Triple]
    highlight: list[str] = []


class SourceGraphSource(BaseModel):
    id: str
    slot_label: str = ""
    source_letter: str = ""
    graph_label: str = ""
    kg_label: str = ""
    prompt_label: str = ""
    embedding_label: str = ""
    ontology_label: str = ""
    model: str = ""
    triplets: list[Triple] = []


class SourceGraphRequest(BaseModel):
    sources: list[SourceGraphSource]


@app.post("/api/visualize", response_class=HTMLResponse)
def visualize(body: VisualizeRequest):
    triplets = [t.model_dump() for t in body.triplets]
    html = build_graph_html(triplets, highlight_entities=body.highlight)
    return HTMLResponse(content=html)


@app.post("/api/visualize/source", response_class=HTMLResponse)
def visualize_source_graph(body: SourceGraphRequest):
    sources = []
    for source in body.sources:
        data = source.model_dump()
        data["triplets"] = [triplet.model_dump() for triplet in source.triplets]
        sources.append(data)
    html = build_source_graph_html(sources)
    return HTMLResponse(content=html)
