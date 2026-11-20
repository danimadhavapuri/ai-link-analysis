import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup, Comment
import httpx

from app.config import get_settings
from app.utils.validators import SSRFValidationError, URLValidationError, validate_and_sanitize_url


class WebsiteExtractionError(Exception):
    """Base error for website extraction failures."""
    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class WebsiteTimeoutError(WebsiteExtractionError):
    def __init__(self, message: str = "Website request timed out."):
        super().__init__(message, status_code=504)


class WebsiteConnectionError(WebsiteExtractionError):
    def __init__(self, message: str = "Unable to connect to target website."):
        super().__init__(message, status_code=502)


class WebsiteAccessBlockedError(WebsiteExtractionError):
    def __init__(self, message: str = "Access to website was blocked by target server (HTTP 401/403)."):
        super().__init__(message, status_code=422)


class WebsiteNotFoundError(WebsiteExtractionError):
    def __init__(self, message: str = "Website was not found (HTTP 404)."):
        super().__init__(message, status_code=404)


class WebsiteServerError(WebsiteExtractionError):
    def __init__(self, message: str = "Target website returned a server error."):
        super().__init__(message, status_code=502)


@dataclass
class ExtractedWebsiteContent:
    """Represents cleaned, structured information extracted from a website."""
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


class WebsiteExtractor:
    """Service to fetch, validate, and clean web content while preventing SSRF."""

    def __init__(self):
        self.settings = get_settings()

    async def fetch_and_extract(self, url: str) -> ExtractedWebsiteContent:
        """
        Validate URL with SSRF protection, fetch HTML across redirects safely,
        and clean/extract meaningful textual content.
        """
        # Step 1: Initial SSRF check on input URL
        current_url, _ = validate_and_sanitize_url(url, resolve_dns=True)
        final_url = current_url
        html_content = ""

        # Step 2: Fetch with manual redirect following to enforce SSRF on each hop
        headers = {
            "User-Agent": self.settings.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate",
            "Cache-Control": "no-cache",
        }

        timeout = httpx.Timeout(self.settings.REQUEST_TIMEOUT, connect=5.0)

        async with httpx.AsyncClient(headers=headers, timeout=timeout, follow_redirects=False) as client:
            redirects_followed = 0

            while redirects_followed <= self.settings.MAX_REDIRECTS:
                try:
                    response = await client.get(current_url)
                except httpx.TimeoutException as exc:
                    raise WebsiteTimeoutError(
                        f"Request to '{current_url}' timed out after {self.settings.REQUEST_TIMEOUT}s."
                    ) from exc
                except httpx.ConnectError as exc:
                    raise WebsiteConnectionError(
                        f"Failed to connect to target host at '{current_url}'."
                    ) from exc
                except httpx.RequestError as exc:
                    raise WebsiteConnectionError(
                        f"Network request error occurred when requesting '{current_url}': {exc}"
                    ) from exc

                # Check if response is a redirect
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        break
                    
                    next_url = urljoin(current_url, location)
                    # Enforce SSRF validation on the redirect target
                    next_url, _ = validate_and_sanitize_url(next_url, resolve_dns=True)
                    current_url = next_url
                    redirects_followed += 1
                    continue

                # Not a redirect - inspect status code
                final_url = current_url
                if response.status_code == 404:
                    raise WebsiteNotFoundError(f"Website at '{final_url}' returned 404 Not Found.")
                elif response.status_code in (401, 403):
                    raise WebsiteAccessBlockedError(
                        f"Target website returned HTTP {response.status_code} (Access Forbidden / Protected)."
                    )
                elif response.status_code >= 500:
                    raise WebsiteServerError(
                        f"Target website returned HTTP {response.status_code} internal error."
                    )
                elif response.status_code >= 400:
                    raise WebsiteExtractionError(
                        f"Target website returned client error HTTP {response.status_code}.",
                        status_code=response.status_code
                    )

                html_content = response.text
                break
            else:
                raise WebsiteExtractionError("Too many redirects encountered while fetching target URL.", status_code=400)

        if not html_content or not html_content.strip():
            raise WebsiteExtractionError("Target website returned an empty response.", status_code=422)

        # Step 3: Parse and clean HTML
        return self._clean_and_extract_html(html_content, url, final_url)

    def _clean_and_extract_html(
        self, html: str, original_url: str, final_url: str
    ) -> ExtractedWebsiteContent:
        """Parses HTML, removes boilerplates, scripts, and extracts clean structured text."""
        soup = BeautifulSoup(html, "html.parser")
        raw_length = len(html)

        # Remove HTML comments
        for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
            comment.extract()

        # Extract Title
        title_tag = soup.find("title")
        title = title_tag.get_text(strip=True) if title_tag else ""

        # Extract Meta Description
        meta_desc = ""
        meta_desc_tag = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
        if not meta_desc_tag:
            meta_desc_tag = soup.find("meta", attrs={"property": re.compile(r"^og:description$", re.I)})
        if meta_desc_tag and meta_desc_tag.get("content"):
            meta_desc = meta_desc_tag["content"].strip()

        # Extract Site Name or Brand Hint
        site_name = ""
        og_site_name = soup.find("meta", attrs={"property": re.compile(r"^og:site_name$", re.I)})
        if og_site_name and og_site_name.get("content"):
            site_name = og_site_name["content"].strip()

        # Extract Social Links
        social_links: Dict[str, str] = {}
        external_links: Set[str] = set()
        
        parsed_domain = urlsplit(final_url).netloc.lower()
        if parsed_domain.startswith("www."):
            parsed_domain = parsed_domain[4:]

        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href or href.startswith("#") or href.startswith("javascript:"):
                continue
            
            href_lower = href.lower()
            if "linkedin.com" in href_lower and "linkedin" not in social_links:
                social_links["linkedin"] = href
            elif ("twitter.com" in href_lower or "x.com" in href_lower) and "x" not in social_links:
                social_links["x"] = href
            elif "facebook.com" in href_lower and "facebook" not in social_links:
                social_links["facebook"] = href
            elif "instagram.com" in href_lower and "instagram" not in social_links:
                social_links["instagram"] = href
            elif "github.com" in href_lower and "github" not in social_links:
                social_links["github"] = href
            elif href_lower.startswith("http"):
                try:
                    ext_host = urlsplit(href).netloc.lower()
                    if ext_host and parsed_domain not in ext_host:
                        external_links.add(href)
                except Exception:
                    pass

        # Extract Headings (H1, H2, H3)
        headings: List[str] = []
        for h in soup.find_all(["h1", "h2", "h3"]):
            text = h.get_text(separator=" ", strip=True)
            if text and len(text) > 3 and text not in headings:
                headings.append(f"<{h.name}>{text}</{h.name}>")

        # Strip scripts, styles, forms, boilerplate navigation and footer elements
        tags_to_decompose = [
            "script", "style", "noscript", "svg", "canvas", "iframe",
            "nav", "footer", "header", "aside", "form", "button",
            "menu", "dialog", "template", "select", "option"
        ]
        for tag_name in tags_to_decompose:
            for el in soup.find_all(tag_name):
                el.decompose()

        # Also remove boilerplate classes / IDs (cookie banners, modals)
        boilerplate_pattern = re.compile(
            r"(cookie|consent|gdpr|banner|popup|advertisement|newsletter-signup|widget)",
            re.I
        )
        for el in soup.find_all(attrs={"class": boilerplate_pattern}):
            el.decompose()
        for el in soup.find_all(attrs={"id": boilerplate_pattern}):
            el.decompose()

        # Find main content container if available, otherwise use body
        content_root = soup.find("main") or soup.find("article") or soup.find("body") or soup

        # Extract all text elements with space separation
        text_lines: List[str] = []
        for element in content_root.stripped_strings:
            cleaned_line = re.sub(r"\s+", " ", element).strip()
            if cleaned_line and len(cleaned_line) > 2:
                text_lines.append(cleaned_line)

        raw_clean_text = "\n".join(text_lines)
        
        # Deduplicate repeating lines
        seen_lines: Set[str] = set()
        deduped_lines: List[str] = []
        for line in raw_clean_text.splitlines():
            line_str = line.strip()
            if line_str and line_str not in seen_lines:
                seen_lines.add(line_str)
                deduped_lines.append(line_str)

        combined_text = "\n".join(deduped_lines)
        
        # Prepend structured metadata at the top of clean text
        summary_header = []
        if title:
            summary_header.append(f"Website Title: {title}")
        if meta_desc:
            summary_header.append(f"Meta Description: {meta_desc}")
        if site_name:
            summary_header.append(f"Site Name: {site_name}")
        if headings:
            summary_header.append("Key Headings:\n" + "\n".join(headings[:15]))
        
        full_text = "\n\n".join(summary_header) + "\n\nMain Content:\n" + combined_text
        
        # Optimize tokens: trim to max length while retaining clean boundaries
        if len(full_text) > self.settings.MAX_CONTENT_LENGTH:
            full_text = full_text[:self.settings.MAX_CONTENT_LENGTH].rsplit(" ", 1)[0] + "\n...[Content truncated for analysis]"

        return ExtractedWebsiteContent(
            url=original_url,
            final_url=final_url,
            title=title,
            meta_description=meta_desc,
            site_name=site_name,
            headings=headings[:15],
            clean_text=full_text,
            social_links=social_links,
            external_links=list(external_links)[:20],
            raw_html_length=raw_length,
            clean_text_length=len(full_text)
        )
