from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

import policy
from .models import DocumentSourceType, IngestionStatus, JobStatus


class DocumentCreateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=policy.MAX_EXTRACTION_CHARS)
    title: str | None = Field(default=None, max_length=255)

    @field_validator("text")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Metin boş olamaz")
        return value


class DocumentSummary(BaseModel):
    id: str
    workspace_id: str
    title: str | None
    source_type: DocumentSourceType
    ingestion_status: IngestionStatus
    content_hash: str | None
    char_count: int | None
    page_count: int | None
    created_at: datetime


class DocumentDetail(DocumentSummary):
    raw_text: str | None
    normalized_text: str | None
    source_url: str | None
    ingestion_error: str | None


class PresignUploadRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(default="application/pdf", max_length=255)


class PresignUploadResponse(BaseModel):
    upload_url: str
    storage_key: str
    expires_in_seconds: int


class DocumentPdfCreateRequest(BaseModel):
    storage_key: str = Field(min_length=1, max_length=512)
    title: str | None = Field(default=None, max_length=255)


class DocumentUrlCreateRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    title: str | None = Field(default=None, max_length=255)


class DocumentIngestionResponse(BaseModel):
    id: str
    source_type: DocumentSourceType
    ingestion_status: IngestionStatus
    ingestion_error: str | None
    page_count: int | None
    segment_count: int
    title: str | None
    created_at: datetime


class ExtractionJobCreateRequest(BaseModel):
    document_id: str
    model: str
    prompt_type: str = "temel"
    kg_type: str = "wikipedia"
    embedding_model: str = "contriever"
    ontology_language: str = "en"


class ExtractionJobResponse(BaseModel):
    id: str
    document_id: str
    workspace_id: str
    model: str
    kg_type: str
    prompt_type: str
    embedding_model: str
    ontology_language: str
    pipeline_version: str
    status: JobStatus
    pipeline_fingerprint: str
    result: dict | None
    error_message: str | None
    recovery_attempts: int
    last_recovery_at: datetime | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class ExtractionJobSummary(BaseModel):
    id: str
    document_id: str
    workspace_id: str
    document_title: str | None
    document_preview: str
    document_source_type: DocumentSourceType
    document_page_count: int | None
    document_source_url: str | None
    triple_count: int
    model: str
    kg_type: str
    prompt_type: str
    embedding_model: str
    ontology_language: str
    status: JobStatus
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
