"""
Async website fetcher with:
  • Per-hop SSRF validation on redirects
  • Full browser-like headers to avoid 403/bot-blocking
  • One automatic retry per hop on transient network errors
  • BeautifulSoup HTML cleaning — strips scripts/styles/nav/footer boilerplate
  • Token-budget trimming (MAX_CONTENT_CHARS)
"""
import re
from dataclasses import dataclass, field
from typing import Dict, List, Set
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup, Comment

from app.config import get_settings
from app.utils.validators import (
    SSRFValidationError,
    URLValidationError,
    validate_and_sanitize_url,
)


# ── Custom exceptions ─────────────────────────────────────────────────────────

class WebsiteExtractionError(Exception):
    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class WebsiteTimeoutError(WebsiteExtractionError):
    def __init__(self, msg: str = "Website request timed out."):
        super().__init__(msg, 504)


class WebsiteConnectionError(WebsiteExtractionError):
    def __init__(self, msg: str = "Unable to connect to website."):
        super().__init__(msg, 502)


class WebsiteAccessBlockedError(WebsiteExtractionError):
    def __init__(self, msg: str = "Website blocked access (401/403)."):
        super().__init__(msg, 422)


class WebsiteNotFoundError(WebsiteExtractionError):
    def __init__(self, msg: str = "Website not found (404)."):
        super().__init__(msg, 404)


class WebsiteServerError(WebsiteExtractionError):
    def __init__(self, msg: str = "Website returned a server error."):
        super().__init__(msg, 502)


# ── Data container ────────────────────────────────────────────────────────────

@dataclass
class ExtractedWebsiteContent:
    url: str
    final_url: str
    title: str = ""
    meta_description: str = ""
    site_name: str = ""
    headings: List[str] = field(default_factory=list)
    clean_text: str = ""
    social_links: Dict[str, str] = field(default_factory=dict)
    external_links: List[str] = field(default_factory=list)
    raw_html_length: int = 0
    clean_text_length: int = 0


# ── Browser-like headers ──────────────────────────────────────────────────────

_BROWSER_HEADERS = {
    "User-Agent": "",           # filled per-request from settings
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Sec-Ch-Ua": '"Google Chrome";v="124", "Chromium";v="124", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "Cache-Control": "no-cache",
}

_TAGS_TO_STRIP = [
    "script", "style", "noscript", "svg", "canvas", "iframe",
    "nav", "footer", "header", "aside", "form", "button",
    "menu", "dialog", "template", "select", "option",
]

_BOILERPLATE_RE = re.compile(
    r"(cookie|consent|gdpr|popup|banner|advertisement|newsletter-signup)",
    re.I,
)


class WebsiteExtractor:

    def __init__(self):
        self.cfg = get_settings()

    async def fetch_and_extract(self, url: str) -> ExtractedWebsiteContent:
        # Initial SSRF check
        current_url, _ = validate_and_sanitize_url(url, resolve_dns=True)
        final_url = current_url
        html = ""

        headers = dict(_BROWSER_HEADERS)
        headers["User-Agent"] = self.cfg.USER_AGENT

        timeout = httpx.Timeout(
            timeout=self.cfg.REQUEST_TIMEOUT,
            connect=self.cfg.REQUEST_CONNECT_TIMEOUT,
            read=self.cfg.REQUEST_READ_TIMEOUT,
        )

        async with httpx.AsyncClient(
            headers=headers, timeout=timeout, follow_redirects=False
        ) as client:
            hops = 0
            while hops <= self.cfg.MAX_REDIRECTS:
                response = await self._get_with_retry(client, current_url)

                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        break
                    next_url = urljoin(current_url, location)
                    # SSRF check on redirect target
                    next_url, _ = validate_and_sanitize_url(next_url, resolve_dns=True)
                    current_url = next_url
                    hops += 1
                    continue

                final_url = current_url
                self._raise_for_status(response, final_url)
                html = response.text
                break
            else:
                raise WebsiteExtractionError("Too many redirects.", 400)

        if not html or not html.strip():
            raise WebsiteExtractionError("Website returned an empty response.", 422)

        return self._parse(html, url, final_url)

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _get_with_retry(
        self, client: httpx.AsyncClient, url: str, retries: int = 1
    ) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            try:
                return await client.get(url)
            except httpx.TimeoutException as exc:
                last_exc = exc
                if attempt >= retries:
                    raise WebsiteTimeoutError(
                        f"Request to '{url}' timed out after {self.cfg.REQUEST_TIMEOUT}s."
                    ) from exc
            except (httpx.ConnectError, httpx.RequestError) as exc:
                last_exc = exc
                if attempt >= retries:
                    raise WebsiteConnectionError(
                        f"Cannot connect to '{url}': {exc}"
                    ) from exc
        raise WebsiteConnectionError(str(last_exc))

    @staticmethod
    def _raise_for_status(resp: httpx.Response, url: str) -> None:
        code = resp.status_code
        if code == 404:
            raise WebsiteNotFoundError(f"'{url}' returned 404 Not Found.")
        if code in (401, 403):
            raise WebsiteAccessBlockedError(
                f"'{url}' blocked access with HTTP {code}."
            )
        if code >= 500:
            raise WebsiteServerError(f"'{url}' returned server error HTTP {code}.")
        if code >= 400:
            raise WebsiteExtractionError(f"'{url}' returned HTTP {code}.", code)

    def _parse(
        self, html: str, original_url: str, final_url: str
    ) -> ExtractedWebsiteContent:
        soup = BeautifulSoup(html, "lxml")
        raw_len = len(html)

        # Strip comments
        for c in soup.find_all(string=lambda t: isinstance(t, Comment)):
            c.extract()

        # ── Metadata ──────────────────────────────────────────────────────────
        title = soup.title.get_text(strip=True) if soup.title else ""

        meta_desc = ""
        for attrs in [
            {"name": re.compile(r"^description$", re.I)},
            {"property": re.compile(r"^og:description$", re.I)},
        ]:
            tag = soup.find("meta", attrs=attrs)
            if tag and tag.get("content"):
                meta_desc = tag["content"].strip()
                break

        site_name = ""
        og_sn = soup.find("meta", attrs={"property": re.compile(r"^og:site_name$", re.I)})
        if og_sn and og_sn.get("content"):
            site_name = og_sn["content"].strip()

        # ── Links ─────────────────────────────────────────────────────────────
        social: Dict[str, str] = {}
        external: Set[str] = set()
        base_domain = urlsplit(final_url).netloc.lower().lstrip("www.")

        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href or href.startswith(("#", "javascript:")):
                continue
            hl = href.lower()
            if "linkedin.com" in hl and "linkedin" not in social:
                social["linkedin"] = href
            elif ("twitter.com" in hl or "x.com" in hl) and "x" not in social:
                social["x"] = href
            elif "facebook.com" in hl and "facebook" not in social:
                social["facebook"] = href
            elif "instagram.com" in hl and "instagram" not in social:
                social["instagram"] = href
            elif "github.com" in hl and "github" not in social:
                social["github"] = href
            elif hl.startswith("http"):
                try:
                    h = urlsplit(href).netloc.lower()
                    if h and base_domain not in h:
                        external.add(href)
                except Exception:
                    pass

        # ── Headings ──────────────────────────────────────────────────────────
        headings: List[str] = []
        seen_h: Set[str] = set()
        for h in soup.find_all(["h1", "h2", "h3"]):
            txt = h.get_text(separator=" ", strip=True)
            if txt and len(txt) > 3 and txt not in seen_h:
                seen_h.add(txt)
                headings.append(f"<{h.name}>{txt}</{h.name}>")

        # ── Clean text ────────────────────────────────────────────────────────
        for tag in _TAGS_TO_STRIP:
            for el in soup.find_all(tag):
                el.decompose()
        for el in soup.find_all(attrs={"class": _BOILERPLATE_RE}):
            el.decompose()
        for el in soup.find_all(attrs={"id": _BOILERPLATE_RE}):
            el.decompose()

        root = soup.find("main") or soup.find("article") or soup.find("body") or soup

        lines: List[str] = []
        seen_lines: Set[str] = set()
        for chunk in root.stripped_strings:
            line = re.sub(r"\s+", " ", chunk).strip()
            if line and len(line) > 2 and line not in seen_lines:
                seen_lines.add(line)
                lines.append(line)

        body = "\n".join(lines)

        # Compose full text with structured header
        parts = []
        if title:
            parts.append(f"Website Title: {title}")
        if meta_desc:
            parts.append(f"Meta Description: {meta_desc}")
        if site_name:
            parts.append(f"Site Name: {site_name}")
        if headings:
            parts.append("Key Headings:\n" + "\n".join(headings[:15]))
        parts.append("Main Content:\n" + body)

        full = "\n\n".join(parts)

        limit = self.cfg.MAX_CONTENT_CHARS
        if len(full) > limit:
            full = full[:limit].rsplit(" ", 1)[0] + "\n...[truncated]"

        return ExtractedWebsiteContent(
            url=original_url,
            final_url=final_url,
            title=title,
            meta_description=meta_desc,
            site_name=site_name,
            headings=headings[:15],
            clean_text=full,
            social_links=social,
            external_links=list(external)[:20],
            raw_html_length=raw_len,
            clean_text_length=len(full),
        )
