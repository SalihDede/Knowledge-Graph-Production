from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from accounts.models import AnonymousVisitor
from documents import service as documents_service
from documents.models import ExtractionJob
from triples.models import Triple


def create_document_and_job(
    database_url: str, text: str, model: str = "test-model"
) -> tuple[str, str]:
    engine = create_async_engine(database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    visitor_id = uuid.uuid4()

    async def scenario() -> tuple[str, str]:
        async with sessions() as db:
            # SQLite doesn't enforce foreign keys by default, but PostgreSQL
            # does: the workspace's owner_visitor_id must reference a real row.
            db.add(AnonymousVisitor(id=visitor_id))
            await db.commit()

            workspace = await documents_service.get_or_create_workspace(
                db, user=None, visitor_id=visitor_id
            )
            document, _ = await documents_service.create_document(
                db, workspace=workspace, user=None, visitor_id=visitor_id, text=text, title=None
            )
            job, _ = await documents_service.create_or_reuse_extraction_job(
                db,
                document=document,
                user=None,
                visitor_id=visitor_id,
                kg_type="wikipedia",
                prompt_type="temel",
                embedding_model="contriever",
                ontology_language="en",
                model=model,
            )
            return str(document.id), str(job.id)

    try:
        return asyncio.run(scenario())
    finally:
        asyncio.run(engine.dispose())


def load_job(database_url: str, job_id: str) -> ExtractionJob:
    engine = create_async_engine(database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def scenario() -> ExtractionJob:
        async with sessions() as db:
            return await db.get(ExtractionJob, uuid.UUID(job_id))

    try:
        return asyncio.run(scenario())
    finally:
        asyncio.run(engine.dispose())


def load_triples(database_url: str, job_id: str) -> list[Triple]:
    engine = create_async_engine(database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def scenario() -> list[Triple]:
        async with sessions() as db:
            result = await db.scalars(
                select(Triple).where(Triple.extraction_job_id == uuid.UUID(job_id))
            )
            return list(result)

    try:
        return asyncio.run(scenario())
    finally:
        asyncio.run(engine.dispose())
