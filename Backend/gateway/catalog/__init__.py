from __future__ import annotations

from fastapi import FastAPI

from .routes import router


def install_catalog(app: FastAPI) -> None:
    app.include_router(router)
