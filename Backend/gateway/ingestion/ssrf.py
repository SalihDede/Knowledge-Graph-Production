from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

import policy

from .errors import IngestionError


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def assert_public_url(url: str) -> str:
    """Rejects URLs that don't point at a public host: disallowed schemes,
    unresolvable hosts, and hosts resolving to a private/loopback/link-local/
    reserved/multicast IP (RFC 1918, localhost, cloud metadata endpoints,
    ...). Must be called again for every redirect hop, since a first,
    innocuous-looking URL can redirect straight into the internal network.
    """
    parsed = urlparse(url)

    if parsed.scheme not in policy.ALLOWED_URL_SCHEMES:
        raise IngestionError(f"İzin verilmeyen URL şeması: {parsed.scheme or '(boş)'}")

    hostname = parsed.hostname
    if not hostname:
        raise IngestionError("URL içinde geçerli bir host bulunamadı")

    try:
        resolved = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise IngestionError(f"URL host adı çözümlenemedi: {hostname}") from exc

    for family, _type, _proto, _canonname, sockaddr in resolved:
        raw_ip = sockaddr[0]
        try:
            ip = ipaddress.ip_address(raw_ip)
        except ValueError:
            continue
        if _is_blocked_ip(ip):
            raise IngestionError(f"URL bir iç ağ adresine işaret ediyor: {hostname} -> {raw_ip}")

    return url
