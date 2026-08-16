from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit

import httpx
from bs4 import BeautifulSoup

from infoscope.integrations.research.url_policy import ValidatedURL
from infoscope.models import ResearchSourceKind

RAW_RESPONSE_LIMIT = 2 * 1024 * 1024
NORMALIZED_TEXT_LIMIT = 200_000
_HORIZONTAL = re.compile(r"[^\S\r\n]+")
_RFC3339 = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)
_CHARSETS = {
    "utf-8": "utf-8",
    "utf8": "utf-8",
    "utf-8-sig": "utf-8-sig",
    "us-ascii": "ascii",
    "ascii": "ascii",
    "gb18030": "gb18030",
    "big5": "big5",
}


class ResearchFetchError(RuntimeError):
    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


@dataclass(frozen=True, slots=True)
class FetchedResearchSource:
    source_kind: ResearchSourceKind
    canonical_url: str
    title: str | None
    published_at: datetime | None
    normalized_text: str
    fetcher_name: str
    fetcher_version: str = "research-fetch-v1"


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value).replace("\r\n", "\n").replace("\r", "\n")
    lines = [_HORIZONTAL.sub(" ", line).strip() for line in normalized.split("\n")]
    return "\n".join(line for line in lines if line).strip()


def _content_type(value: str) -> tuple[str, str]:
    parts = [part.strip() for part in value.split(";")]
    media_type = parts[0].lower()
    charset = "utf-8"
    for part in parts[1:]:
        name, separator, raw_value = part.partition("=")
        if separator and name.strip().lower() == "charset":
            charset = raw_value.strip().strip('"').lower()
    if charset not in _CHARSETS:
        raise ResearchFetchError("RESEARCH_CONTENT_ENCODING_UNSUPPORTED")
    return media_type, _CHARSETS[charset]


def _published_at(soup: BeautifulSoup) -> datetime | None:
    values: list[datetime] = []
    for tag in soup.find_all("meta"):
        property_value = tag.get("property")
        if (
            not isinstance(property_value, str)
            or property_value.lower() != "article:published_time"
        ):
            continue
        content = tag.get("content")
        if not isinstance(content, str) or not _RFC3339.fullmatch(content):
            return None
        try:
            parsed = datetime.fromisoformat(content.replace("Z", "+00:00")).astimezone(UTC)
        except ValueError:
            return None
        values.append(parsed)
    if not values or any(value != values[0] for value in values[1:]):
        return None
    return values[0]


def _html_document(value: str) -> tuple[str | None, datetime | None, str]:
    soup = BeautifulSoup(value, "html.parser")
    published_at = _published_at(soup)
    title_tag = soup.find("title")
    title = normalize_text(title_tag.get_text(" ", strip=True)) if title_tag else None
    if title and len(title) > 512:
        title = None
    for tag in soup.find_all(["script", "style", "noscript", "template", "svg", "canvas"]):
        tag.decompose()
    for tag in soup.find_all(lambda candidate: candidate.has_attr("hidden")):
        tag.decompose()
    for tag in soup.find_all(attrs={"aria-hidden": re.compile(r"^true$", re.I)}):
        tag.decompose()
    body = ""
    for name in ("main", "article", "body"):
        root = soup.find(name)
        if root is not None:
            body = normalize_text(root.get_text("\n", strip=True))
            if body:
                break
    if not body:
        raise ResearchFetchError("RESEARCH_CONTENT_EMPTY")
    combined = f"{title}\n\n{body}" if title and body.split("\n", 1)[0] != title else body
    return title, published_at, normalize_text(combined)


def _github_title(canonical_url: str) -> str | None:
    segment = PurePosixPath(urlsplit(canonical_url).path).name
    try:
        title = unquote(segment, encoding="utf-8", errors="strict")
    except UnicodeDecodeError:
        return None
    return title if title and len(title) <= 512 else None


class DirectHTTPSResearchFetcher:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def fetch(
        self,
        source_kind: ResearchSourceKind,
        validated: ValidatedURL,
    ) -> FetchedResearchSource:
        request = self.client.build_request(
            "GET",
            validated.canonical_url,
            headers={
                "Accept": "text/html, text/plain, text/markdown, application/json",
                "Accept-Encoding": "identity",
                "User-Agent": "Infoscope-Research/1",
            },
        )
        try:
            response = await self.client.send(request, stream=True, follow_redirects=False)
        except httpx.HTTPError as error:
            raise ResearchFetchError("RESEARCH_FETCH_FAILED") from error
        try:
            if 300 <= response.status_code < 400:
                raise ResearchFetchError("RESEARCH_REDIRECT_REJECTED")
            if not response.is_success:
                raise ResearchFetchError("RESEARCH_FETCH_FAILED")
            self._validate_peer(response, validated)
            chunks: list[bytes] = []
            size = 0
            async for chunk in response.aiter_raw():
                size += len(chunk)
                if size > RAW_RESPONSE_LIMIT:
                    raise ResearchFetchError("RESEARCH_RESPONSE_TOO_LARGE")
                chunks.append(chunk)
            media_type, charset = _content_type(response.headers.get("content-type", ""))
            allowed = (
                {"text/html", "text/plain"}
                if source_kind is ResearchSourceKind.WEB_PAGE
                else {"text/plain", "text/markdown", "application/json", "application/octet-stream"}
            )
            if media_type not in allowed:
                raise ResearchFetchError("RESEARCH_CONTENT_TYPE_UNSUPPORTED")
            try:
                decoded = b"".join(chunks).decode(charset, errors="strict")
            except UnicodeDecodeError as error:
                raise ResearchFetchError("RESEARCH_CONTENT_ENCODING_UNSUPPORTED") from error
            if source_kind is ResearchSourceKind.WEB_PAGE and media_type == "text/html":
                title, published_at, normalized = _html_document(decoded)
                fetcher_name = "direct_https_html"
            else:
                title = (
                    _github_title(validated.canonical_url)
                    if source_kind is ResearchSourceKind.GITHUB_DOCUMENT
                    else None
                )
                published_at = None
                normalized = normalize_text(decoded)
                fetcher_name = (
                    "direct_https_github"
                    if source_kind is ResearchSourceKind.GITHUB_DOCUMENT
                    else "direct_https_html"
                )
            if not normalized:
                raise ResearchFetchError("RESEARCH_CONTENT_EMPTY")
            if len(normalized.encode("utf-8")) > NORMALIZED_TEXT_LIMIT:
                raise ResearchFetchError("RESEARCH_CONTENT_TOO_LARGE")
            return FetchedResearchSource(
                source_kind=source_kind,
                canonical_url=validated.canonical_url,
                title=title,
                published_at=published_at,
                normalized_text=normalized,
                fetcher_name=fetcher_name,
            )
        finally:
            await response.aclose()

    @staticmethod
    def _validate_peer(response: httpx.Response, validated: ValidatedURL) -> None:
        stream = response.extensions.get("network_stream")
        peer = stream.get_extra_info("server_addr") if stream is not None else None
        if not isinstance(peer, tuple) or not peer or str(peer[0]) not in validated.addresses:
            raise ResearchFetchError("RESEARCH_DNS_REBINDING_REJECTED")
