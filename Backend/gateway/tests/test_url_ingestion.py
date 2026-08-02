from __future__ import annotations

import httpx
import pytest

import ingestion.url_fetch as url_fetch_module
from documents.models import SegmentType
from ingestion.errors import IngestionError
from ingestion.url_fetch import extract_main_content, fetch_html, ingest_url


def _patch_client(monkeypatch, transport: httpx.MockTransport) -> None:
    class _PatchedAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(url_fetch_module.httpx, "AsyncClient", _PatchedAsyncClient)


def _bypass_ssrf(monkeypatch) -> None:
    monkeypatch.setattr(url_fetch_module, "assert_public_url", lambda url: url)


@pytest.mark.asyncio
async def test_fetch_html_returns_body_for_simple_response(monkeypatch) -> None:
    _bypass_ssrf(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, text="<html>hi</html>")

    _patch_client(monkeypatch, httpx.MockTransport(handler))

    final_url, html = await fetch_html("http://example.com/page")

    assert final_url == "http://example.com/page"
    assert html == "<html>hi</html>"


@pytest.mark.asyncio
async def test_fetch_html_follows_redirect_and_revalidates_each_hop(monkeypatch) -> None:
    seen_urls: list[str] = []

    def fake_assert_public_url(url: str) -> str:
        seen_urls.append(url)
        return url

    monkeypatch.setattr(url_fetch_module, "assert_public_url", fake_assert_public_url)

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "http://example.com/start":
            return httpx.Response(302, headers={"location": "http://example.com/final"})
        return httpx.Response(200, headers={"content-type": "text/html"}, text="<html>final</html>")

    _patch_client(monkeypatch, httpx.MockTransport(handler))

    final_url, html = await fetch_html("http://example.com/start")

    assert final_url == "http://example.com/final"
    assert html == "<html>final</html>"
    assert seen_urls == ["http://example.com/start", "http://example.com/final"]


@pytest.mark.asyncio
async def test_fetch_html_rejects_too_many_redirects(monkeypatch) -> None:
    _bypass_ssrf(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": str(request.url) + "x"})

    _patch_client(monkeypatch, httpx.MockTransport(handler))

    with pytest.raises(IngestionError):
        await fetch_html("http://example.com/loop")


@pytest.mark.asyncio
async def test_fetch_html_enforces_content_length_limit(monkeypatch) -> None:
    _bypass_ssrf(monkeypatch)
    monkeypatch.setattr(url_fetch_module.policy, "MAX_URL_CONTENT_BYTES", 10)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, text="x" * 1000)

    _patch_client(monkeypatch, httpx.MockTransport(handler))

    with pytest.raises(IngestionError):
        await fetch_html("http://example.com/big")


@pytest.mark.asyncio
async def test_fetch_html_rejects_disallowed_content_type(monkeypatch) -> None:
    _bypass_ssrf(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF-1.4")

    _patch_client(monkeypatch, httpx.MockTransport(handler))

    with pytest.raises(IngestionError):
        await fetch_html("http://example.com/file.pdf")


@pytest.mark.asyncio
async def test_fetch_html_raises_on_non_success_status(monkeypatch) -> None:
    _bypass_ssrf(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, headers={"content-type": "text/html"}, text="not found")

    _patch_client(monkeypatch, httpx.MockTransport(handler))

    with pytest.raises(IngestionError):
        await fetch_html("http://example.com/missing")


def test_extract_main_content_pulls_readable_text_from_html() -> None:
    html = """
    <html><body>
    <article>
    <h1>Title</h1>
    <p>This is the first real paragraph with enough content to be kept.</p>
    <p>This is the second real paragraph, also long enough to be extracted.</p>
    </article>
    </body></html>
    """

    content = extract_main_content(html)

    assert "first real paragraph" in content
    assert "second real paragraph" in content


def test_extract_main_content_returns_empty_string_for_no_content() -> None:
    assert extract_main_content("<html><body></body></html>") == ""


@pytest.mark.asyncio
async def test_ingest_url_builds_paragraph_segments_from_final_url(monkeypatch) -> None:
    _bypass_ssrf(monkeypatch)

    html = """
    <html><body><article>
    <p>This is the first real paragraph with enough content to be kept.</p>
    <p>This is the second real paragraph, also long enough to be extracted.</p>
    </article></body></html>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, text=html)

    _patch_client(monkeypatch, httpx.MockTransport(handler))

    normalized, segments, final_url = await ingest_url("http://example.com/article")

    assert final_url == "http://example.com/article"
    assert segments
    assert all(segment.segment_type == SegmentType.paragraph for segment in segments)
    assert all(segment.page_number is None for segment in segments)
    for segment in segments:
        assert normalized[segment.char_start:segment.char_end] == segment.text


@pytest.mark.asyncio
async def test_ingest_url_raises_when_no_main_content_extracted(monkeypatch) -> None:
    _bypass_ssrf(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, text="<html><body></body></html>")

    _patch_client(monkeypatch, httpx.MockTransport(handler))

    with pytest.raises(IngestionError):
        await ingest_url("http://example.com/empty")
