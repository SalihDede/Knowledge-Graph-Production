from __future__ import annotations

import json
import logging
import os
from datetime import timedelta

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from accounts.models import AnonymousVisitor, utc_now
from documents.models import Document

logger = logging.getLogger(__name__)

# Anonymous visitor rows are only ever cleaned up once their signed cookie
# would already have expired on its own -- reusing the same TTL keeps this
# sweep from ever racing a still-live cookie. Duplicated from
# accounts.config.AuthSettings.visitor_ttl_seconds's default rather than
# importing it, to avoid this module depending on the full AuthSettings
# construction (env parsing, cookie secret validation, ...) for one number.
VISITOR_CLEANUP_STALE_SECONDS = int(os.getenv("AUTH_VISITOR_TTL_SECONDS", "7776000"))
VISITOR_CLEANUP_BATCH_SIZE = int(os.getenv("VISITOR_CLEANUP_BATCH_SIZE", "500"))

# Grace window before a storage object with no matching document row is
# considered truly abandoned (rather than a presigned upload that's still
# mid-flight, a few seconds between the PUT finishing and the confirming
# POST /api/documents/pdf call).
ORPHAN_UPLOAD_GRACE_SECONDS = int(os.getenv("ORPHAN_UPLOAD_GRACE_SECONDS", str(24 * 3600)))

WIKONTIC_URL = os.getenv("WIKONTIC_URL", "http://wikontic:8001")
HEALTH_CHECK_TIMEOUT_SECONDS = float(os.getenv("MAINTENANCE_HEALTH_CHECK_TIMEOUT_SECONDS", "10"))


async def sweep_stale_anonymous_visitors(sessions: async_sessionmaker) -> int:
    """Deletes anonymous_visitors rows that were never claimed by a user and
    are older than the visitor cookie's own TTL. Once the signed cookie
    would have expired anyway, the browser gets a brand new visitor on its
    next visit, so the old row -- and, via the existing ON DELETE CASCADE
    chain, any workspace/documents/segments/jobs/triples it solely owned --
    is genuinely orphaned. Claimed visitors (claimed_by_user_id is not
    null) are never touched here regardless of age: they're kept as the
    historical link between an account and its original anonymous session.
    """
    stale_before = utc_now() - timedelta(seconds=VISITOR_CLEANUP_STALE_SECONDS)

    async with sessions() as db:
        result = await db.execute(
            select(AnonymousVisitor.id)
            .where(
                AnonymousVisitor.claimed_by_user_id.is_(None),
                AnonymousVisitor.last_seen_at < stale_before,
            )
            .limit(VISITOR_CLEANUP_BATCH_SIZE)
            .with_for_update(skip_locked=True)
        )
        ids = [row[0] for row in result.all()]
        if ids:
            await db.execute(delete(AnonymousVisitor).where(AnonymousVisitor.id.in_(ids)))
            await db.commit()

    if ids:
        logger.info("[maintenance] removed %s stale anonymous visitor(s)", len(ids))
    return len(ids)


async def sweep_orphaned_storage_objects(sessions: async_sessionmaker) -> int:
    """Deletes MinIO objects with no matching documents.storage_key row --
    either a presigned upload the browser never confirmed via
    POST /api/documents/pdf, or a document row that was since cascade-
    deleted (account deletion, stale-visitor cleanup) leaving its PDF
    behind. Only objects older than ORPHAN_UPLOAD_GRACE_SECONDS are
    considered, so an upload mid-confirmation is never raced. Live
    documents (any ingestion_status, including failed -- a failed job may
    still be retried against the same file) are never touched, since their
    storage_key still has a referencing row."""
    import storage

    cutoff = utc_now() - timedelta(seconds=ORPHAN_UPLOAD_GRACE_SECONDS)
    removed = 0

    for key, last_modified in storage.iter_objects():
        if last_modified > cutoff:
            continue

        async with sessions() as db:
            exists = await db.scalar(select(Document.id).where(Document.storage_key == key))

        if exists is not None:
            continue

        try:
            storage.delete_object(key)
            removed += 1
        except storage.StorageError:
            logger.warning("[maintenance] could not delete orphaned storage object %s", key, exc_info=True)

    if removed:
        logger.info("[maintenance] removed %s orphaned storage object(s)", removed)
    return removed


async def check_wikontic_health() -> dict:
    """Periodic (not request-triggered) MongoDB + embedding-profile health
    check, so a broken profile is caught proactively instead of only being
    discovered when a real extraction request using it fails. Hits
    wikontic's /health/ready (generic Mongo connectivity + API key) and
    /health/profiles (per-configured-profile ontology/triplets DB
    presence) endpoints and logs a single structured summary."""
    status: dict = {"ready": None, "profiles": None}

    async with httpx.AsyncClient(timeout=HEALTH_CHECK_TIMEOUT_SECONDS) as client:
        try:
            response = await client.get(f"{WIKONTIC_URL}/health/ready")
            status["ready"] = {"ok": response.is_success, "status_code": response.status_code}
        except httpx.HTTPError as exc:
            status["ready"] = {"ok": False, "error": str(exc)}

        try:
            response = await client.get(f"{WIKONTIC_URL}/health/profiles")
            body = response.json() if response.is_success else None
            status["profiles"] = {
                "ok": response.is_success and body is not None and body.get("status") == "ok",
                "status_code": response.status_code,
                "detail": body,
            }
        except httpx.HTTPError as exc:
            status["profiles"] = {"ok": False, "error": str(exc)}

    overall_ok = bool(status["ready"] and status["ready"].get("ok")) and bool(
        status["profiles"] and status["profiles"].get("ok")
    )
    log_line = json.dumps({"event": "wikontic_health_check", "ok": overall_ok, **status}, ensure_ascii=False, default=str)
    if overall_ok:
        logger.info(log_line)
    else:
        logger.warning(log_line)

    return status
