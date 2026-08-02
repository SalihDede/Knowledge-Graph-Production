from __future__ import annotations

from fastapi import FastAPI

from accounts.runtime import AuthRuntime
from .routes import router


def install_triples(app: FastAPI, runtime: AuthRuntime | None) -> None:
    if runtime is None:
        return
    app.include_router(router)
