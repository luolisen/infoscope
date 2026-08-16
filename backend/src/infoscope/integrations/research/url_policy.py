from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from dataclasses import dataclass
from hashlib import sha256
from urllib.parse import SplitResult, urlsplit, urlunsplit

from infoscope.models import ResearchSourceKind

_PERCENT = re.compile(r"%([0-9a-fA-F]{2})")
_UNRESERVED = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")


class ResearchURLRejected(ValueError):
    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


@dataclass(frozen=True, slots=True)
class ValidatedURL:
    canonical_url: str
    canonical_url_hash: str
    hostname: str
    addresses: frozenset[str]


def _normalize_percent(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        character = chr(int(match.group(1), 16))
        return character if character in _UNRESERVED else f"%{match.group(1).upper()}"

    normalized = _PERCENT.sub(replace, value)
    if "%" in normalized:
        raise ResearchURLRejected("RESEARCH_URL_REJECTED")
    return normalized


def _remove_dot_segments(path: str) -> str:
    input_buffer = path
    output = ""
    while input_buffer:
        if input_buffer.startswith("../"):
            input_buffer = input_buffer[3:]
        elif input_buffer.startswith("./"):
            input_buffer = input_buffer[2:]
        elif input_buffer.startswith("/./"):
            input_buffer = "/" + input_buffer[3:]
        elif input_buffer == "/.":
            input_buffer = "/"
        elif input_buffer.startswith("/../"):
            input_buffer = "/" + input_buffer[4:]
            output = output.rsplit("/", 1)[0]
        elif input_buffer == "/..":
            input_buffer = "/"
            output = output.rsplit("/", 1)[0]
        elif input_buffer in {".", ".."}:
            input_buffer = ""
        else:
            start = 1 if input_buffer.startswith("/") else 0
            next_slash = input_buffer.find("/", start)
            if next_slash == -1:
                output += input_buffer
                input_buffer = ""
            else:
                output += input_buffer[:next_slash]
                input_buffer = input_buffer[next_slash:]
    return output or "/"


def canonicalize_url(value: str, source_kind: ResearchSourceKind) -> tuple[str, str]:
    if len(value) > 2048:
        raise ResearchURLRejected("RESEARCH_URL_REJECTED")
    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() != "https" or not parsed.hostname:
            raise ResearchURLRejected("RESEARCH_URL_REJECTED")
        if parsed.username is not None or parsed.password is not None:
            raise ResearchURLRejected("RESEARCH_URL_REJECTED")
        if parsed.port not in {None, 443}:
            raise ResearchURLRejected("RESEARCH_URL_REJECTED")
        hostname = parsed.hostname.rstrip(".").encode("idna").decode("ascii").lower()
    except (UnicodeError, ValueError) as error:
        raise ResearchURLRejected("RESEARCH_URL_REJECTED") from error
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        raise ResearchURLRejected("RESEARCH_URL_REJECTED")
    if (
        source_kind is ResearchSourceKind.GITHUB_DOCUMENT
        and hostname != "raw.githubusercontent.com"
    ):
        raise ResearchURLRejected("RESEARCH_SOURCE_HOST_REJECTED")
    path = _remove_dot_segments(_normalize_percent(parsed.path or "/"))
    query = _normalize_percent(parsed.query)
    canonical = urlunsplit(SplitResult("https", hostname, path, query, ""))
    return canonical, hostname


async def validate_public_url(value: str, source_kind: ResearchSourceKind) -> ValidatedURL:
    canonical, hostname = canonicalize_url(value, source_kind)
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(
            hostname,
            443,
            type=socket.SOCK_STREAM,
        )
    except OSError as error:
        raise ResearchURLRejected("RESEARCH_DNS_FAILED") from error
    addresses = frozenset(item[4][0] for item in infos)
    if not addresses:
        raise ResearchURLRejected("RESEARCH_DNS_FAILED")
    if any(not ipaddress.ip_address(value).is_global for value in addresses):
        raise ResearchURLRejected("RESEARCH_SSRF_REJECTED")
    return ValidatedURL(
        canonical_url=canonical,
        canonical_url_hash=sha256(canonical.encode("utf-8")).hexdigest(),
        hostname=hostname,
        addresses=addresses,
    )
