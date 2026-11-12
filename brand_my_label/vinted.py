"""Vinted shares labels as an HTML viewer page that embeds a signed S3 link
to the real PDF. Pull the PDF out of it, safely.

The URL comes from user-supplied HTML, so fetching it is an SSRF vector.
Guards: https only, host must match an allowlist (S3 by default), resolved
address must be public, no redirects, size cap, short timeout.
"""

from __future__ import annotations

import html as htmllib
import ipaddress
import re
import socket
from urllib.parse import urlsplit

import httpx

DEFAULT_ALLOWED_SUFFIXES = (".amazonaws.com",)
MAX_PDF_BYTES = 10 * 1024 * 1024


class VintedError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def is_html(data: bytes) -> bool:
    head = data[:512].lstrip().lower()
    return head.startswith(b"<!doctype html") or head.startswith(b"<html")


def candidate_urls(data: bytes) -> list[str]:
    text = data.decode("utf-8", errors="replace")
    urls = re.findall(r'(?:src|href)="([^"]+)"', text)
    return [htmllib.unescape(u) for u in urls
            if ".pdf" in u.lower()
            or "response-content-type=application%2fpdf" in u.lower()]


def filename_from_html(data: bytes) -> str | None:
    text = data.decode("utf-8", errors="replace")
    m = (re.search(r'filename%3D%22([^%"&]+\.pdf)%22', text)
         or re.search(r'filename="([^"]+\.pdf)"', text))
    if not m:
        return None
    name = htmllib.unescape(m.group(1))
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)[:100]


def _host_allowed(host: str, suffixes) -> bool:
    host = host.lower().rstrip(".")
    return any(host == s.lstrip(".") or host.endswith(s) for s in suffixes)


def _resolves_public(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except OSError:
        return False
    return bool(infos) and all(
        ipaddress.ip_address(info[4][0]).is_global for info in infos)


def check_url(url: str, suffixes=DEFAULT_ALLOWED_SUFFIXES,
              resolve=_resolves_public) -> bool:
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    if parts.scheme != "https" or not parts.hostname:
        return False
    if parts.port not in (None, 443) or parts.username or parts.password:
        return False
    if not _host_allowed(parts.hostname, suffixes):
        return False
    return resolve(parts.hostname)


def fetch_pdf_from_html(data: bytes, *, client: httpx.Client | None = None,
                        suffixes=DEFAULT_ALLOWED_SUFFIXES,
                        resolve=_resolves_public,
                        max_bytes: int = MAX_PDF_BYTES) -> bytes:
    urls = [u for u in candidate_urls(data) if check_url(u, suffixes, resolve)]
    if not urls:
        raise VintedError("html_no_pdf", "no downloadable label link found in the page")
    own = client is None
    client = client or httpx.Client(timeout=15, follow_redirects=False)
    try:
        for url in urls[:3]:
            try:
                with client.stream("GET", url) as r:
                    if r.status_code != 200:
                        continue
                    buf = bytearray()
                    for chunk in r.iter_bytes():
                        buf += chunk
                        if len(buf) > max_bytes:
                            raise VintedError("too_large", "linked PDF is too large")
                if bytes(buf[:5]) == b"%PDF-":
                    return bytes(buf)
            except httpx.HTTPError:
                continue
    finally:
        if own:
            client.close()
    raise VintedError("html_fetch_failed",
                      "label link expired or unreachable: share the label again")
