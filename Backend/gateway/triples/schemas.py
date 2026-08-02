from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from .models import TripleStatus


class TripleEvidenceResponse(BaseModel):
    id: str
    source_text: str
    char_start: int | None
    char_end: int | None
    created_at: datetime


class TripleResponse(BaseModel):
    id: str
    document_id: str
    extraction_job_id: str
    workspace_id: str
    subject: str
    subject_type: str | None
    predicate: str
    object: str
    object_type: str | None
    qualifiers: list | None
    status: TripleStatus
    created_at: datetime
    updated_at: datetime
    evidence: list[TripleEvidenceResponse] = []


class TripleStatusUpdateRequest(BaseModel):
    status: TripleStatus
