import logging
import os
import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, field_validator
from dotenv import load_dotenv

load_dotenv()

from accounts import install_accounts
from accounts.setup import accounts_ready
from catalog import install_catalog
from documents import install_documents
from triples import install_triples
from gateway_middleware import (
    MiddlewareSettings,
    install_error_handlers,
    install_platform_middleware,
)
from gateway_middleware.context import request_id_context
from visualization import build_graph_html, build_source_graph_html
from extraction import ExtractionError, run_extraction
from policy import PolicyError, validate_pipeline, validate_text_length

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

accounts_runtime = install_accounts(app)
install_documents(app, accounts_runtime)
install_triples(app, accounts_runtime)
install_catalog(app)
install_error_handlers(app)
install_platform_middleware(app, middleware_settings)

WIKONTIC_URL   = os.getenv("WIKONTIC_URL", "http://localhost:8001")


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


@app.post("/api/extract")
async def extract(body: ExtractRequest, request: Request):
    is_anonymous = getattr(request.state, "user", None) is None
    try:
        validate_text_length(body.text)
        validate_pipeline(
            model=body.model,
            kg_type=body.kg_type,
            prompt_type=body.prompt_type,
            embedding_model=body.embedding_model,
            ontology_language=body.ontology_language,
            is_anonymous=is_anonymous,
        )
    except PolicyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    try:
        triplets = await run_extraction(
            text=body.text,
            model=body.model,
            kg_type=body.kg_type,
            prompt_type=body.prompt_type,
            embedding_model=body.embedding_model,
            ontology_language=body.ontology_language,
            request_id=request_id_context.get(),
        )
    except ExtractionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

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
