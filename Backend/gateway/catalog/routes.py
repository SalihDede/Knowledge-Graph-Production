from __future__ import annotations

from fastapi import APIRouter

from . import registry

router = APIRouter(tags=["catalog"])


@router.get("/api/models")
def get_models():
    return registry.load_models()
