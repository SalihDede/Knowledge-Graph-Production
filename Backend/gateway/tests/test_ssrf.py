from __future__ import annotations

import socket

import pytest

from ingestion.errors import IngestionError
from ingestion.ssrf import assert_public_url


def test_rejects_non_http_scheme() -> None:
    with pytest.raises(IngestionError):
        assert_public_url("ftp://example.com/file")


def test_rejects_missing_host() -> None:
    with pytest.raises(IngestionError):
        assert_public_url("http:///just-a-path")


def test_rejects_unresolvable_host() -> None:
    def fake_getaddrinfo(*_args, **_kwargs):
        raise socket.gaierror("not found")

    import ingestion.ssrf as ssrf_module
    original = ssrf_module.socket.getaddrinfo
    ssrf_module.socket.getaddrinfo = fake_getaddrinfo
    try:
        with pytest.raises(IngestionError):
            assert_public_url("http://this-host-does-not-exist.invalid")
    finally:
        ssrf_module.socket.getaddrinfo = original


def _fake_resolve(ip: str):
    def fake_getaddrinfo(*_args, **_kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]
    return fake_getaddrinfo


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",       # loopback
        "10.0.0.5",        # RFC 1918 private
        "172.16.0.5",      # RFC 1918 private
        "192.168.1.1",     # RFC 1918 private
        "169.254.169.254",  # link-local / cloud metadata endpoint
        "::1",             # IPv6 loopback
        "0.0.0.0",         # unspecified
    ],
)
def test_rejects_internal_and_special_use_ips(monkeypatch, ip: str) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _fake_resolve(ip))

    with pytest.raises(IngestionError):
        assert_public_url("http://internal.example.com")


def test_allows_a_public_ip(monkeypatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _fake_resolve("93.184.216.34"))

    assert assert_public_url("http://example.com/page") == "http://example.com/page"
