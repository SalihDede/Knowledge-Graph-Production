from __future__ import annotations

import httpx
import trafilatura

import policy
from documents.models import SegmentType
from documents.normalization import normalize_text
from documents.service import SegmentInput

from .errors import IngestionError
from .segmentation import iter_paragraphs_with_offsets
from .ssrf import assert_public_url


async def fetch_html(url: str) -> tuple[str, str]:
    """Fetches `url`, following redirects manually so every hop is
    SSRF-validated before connecting -- a safe first URL can still redirect
    straight into the internal network. Returns (final_url, html)."""
    current_url = assert_public_url(url)

    async with httpx.AsyncClient(
        follow_redirects=False, timeout=policy.URL_FETCH_TIMEOUT_SECONDS
    ) as client:
        for _ in range(policy.MAX_URL_REDIRECTS + 1):
            try:
                async with client.stream("GET", current_url) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise IngestionError("Yönlendirme adresi eksik")
                        current_url = assert_public_url(str(httpx.URL(current_url).join(location)))
                        continue

                    if not response.is_success:
                        raise IngestionError(f"URL isteği başarısız: HTTP {response.status_code}")

                    content_type = response.headers.get("content-type", "")
                    if content_type and "html" not in content_type and "text" not in content_type:
                        raise IngestionError(f"Desteklenmeyen içerik türü: {content_type}")

                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > policy.MAX_URL_CONTENT_BYTES:
                            raise IngestionError(
                                f"URL içeriği en fazla {policy.MAX_URL_CONTENT_BYTES} bayt olabilir"
                            )
                        chunks.append(chunk)

                    html = b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")
                    return current_url, html
            except httpx.TimeoutException as exc:
                raise IngestionError("URL isteği zaman aşımına uğradı", retryable=True) from exc
            except httpx.HTTPError as exc:
                raise IngestionError("URL'ye ulaşılamadı", retryable=True) from exc

        raise IngestionError("Çok fazla yönlendirme")


def extract_main_content(html: str) -> str:
    extracted = trafilatura.extract(html, include_comments=False, include_tables=False)
    return (extracted or "").strip()


async def ingest_url(url: str) -> tuple[str, list[SegmentInput], str]:
    """Full URL ingestion pipeline: SSRF-safe fetch -> main content
    extraction -> paragraph segmentation. Returns (normalized_text, segments,
    final_url_after_redirects)."""
    final_url, html = await fetch_html(url)
    main_text = extract_main_content(html)
    if not main_text:
        raise IngestionError("Sayfadan okunabilir bir ana içerik çıkarılamadı")

    normalized = normalize_text(main_text)
    segments = [
        SegmentInput(
            segment_type=SegmentType.paragraph,
            page_number=None,
            ordinal=ordinal,
            text=paragraph_text,
            char_start=start,
            char_end=end,
        )
        for ordinal, (paragraph_text, start, end) in enumerate(iter_paragraphs_with_offsets(normalized))
    ]
    return normalized, segments, final_url
