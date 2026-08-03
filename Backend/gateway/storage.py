from __future__ import annotations

import os
from functools import lru_cache

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "http://minio:9000")
# Presigned URLs are handed to the browser, which cannot resolve the internal
# docker-network hostname; they must be signed against a host it can reach.
MINIO_PUBLIC_ENDPOINT = os.getenv("MINIO_PUBLIC_ENDPOINT", "http://localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "kg-documents")
MINIO_REGION = os.getenv("MINIO_REGION", "us-east-1")

PRESIGN_EXPIRES_SECONDS = int(os.getenv("UPLOAD_PRESIGN_EXPIRES_SECONDS", "600"))


class StorageError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _build_client(endpoint: str):
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
        region_name=MINIO_REGION,
        config=Config(signature_version="s3v4"),
    )


@lru_cache(maxsize=1)
def _internal_client():
    return _build_client(MINIO_ENDPOINT)


@lru_cache(maxsize=1)
def _public_client():
    return _build_client(MINIO_PUBLIC_ENDPOINT)


def ensure_bucket() -> None:
    client = _internal_client()
    try:
        client.head_bucket(Bucket=MINIO_BUCKET)
    except ClientError:
        client.create_bucket(Bucket=MINIO_BUCKET)


def generate_presigned_upload(object_key: str, *, content_type: str) -> str:
    """Signed PUT URL the browser uploads directly to, so PDF bytes never
    pass through (or get stored in) the application database."""
    return _public_client().generate_presigned_url(
        "put_object",
        Params={"Bucket": MINIO_BUCKET, "Key": object_key, "ContentType": content_type},
        ExpiresIn=PRESIGN_EXPIRES_SECONDS,
    )


def stat_object(object_key: str) -> dict | None:
    try:
        response = _internal_client().head_object(Bucket=MINIO_BUCKET, Key=object_key)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey"}:
            return None
        raise StorageError(f"Depolama nesnesi sorgulanamadı: {object_key}") from exc
    return {"size": response["ContentLength"], "content_type": response.get("ContentType")}


def get_object_bytes(object_key: str) -> bytes:
    try:
        response = _internal_client().get_object(Bucket=MINIO_BUCKET, Key=object_key)
        return response["Body"].read()
    except ClientError as exc:
        raise StorageError(f"Depolama nesnesi okunamadı: {object_key}") from exc


def put_object_bytes(object_key: str, data: bytes, *, content_type: str) -> None:
    try:
        _internal_client().put_object(
            Bucket=MINIO_BUCKET, Key=object_key, Body=data, ContentType=content_type
        )
    except ClientError as exc:
        raise StorageError(f"Depolama nesnesi yazılamadı: {object_key}") from exc


def delete_object(object_key: str) -> None:
    try:
        _internal_client().delete_object(Bucket=MINIO_BUCKET, Key=object_key)
    except ClientError:
        pass


def iter_objects():
    """Yields (key, last_modified) for every object in the bucket. Used by
    the maintenance sweep (worker/maintenance.py) to find uploaded objects
    with no corresponding document row -- last_modified is a timezone-aware
    UTC datetime, straight from the S3 API."""
    paginator = _internal_client().get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=MINIO_BUCKET):
        for obj in page.get("Contents", []):
            yield obj["Key"], obj["LastModified"]


__all__ = [
    "StorageError",
    "MINIO_BUCKET",
    "ensure_bucket",
    "generate_presigned_upload",
    "stat_object",
    "get_object_bytes",
    "put_object_bytes",
    "delete_object",
    "iter_objects",
]
