from unittest.mock import AsyncMock, patch
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas import (
    AnalysisData,
    CompetitorAnalysis,
    CompetitorDetail,
    LinkAnalysisResponse,
    RecommendedTitle,
    SEOImprovements,
    SEOTitleRecommendation,
    SupportingContentIdeas,
    TargetAudience,
    TargetSearchQuery,
    TopService,
)
from app.services.website_extractor import ExtractedWebsiteContent, WebsiteExtractor, WebsiteNotFoundError, WebsiteTimeoutError
from app.utils.validators import SSRFValidationError, URLValidationError, validate_and_sanitize_url


@pytest.fixture
def client():
    """FastAPI TestClient fixture."""
    return TestClient(app)


# -----------------------------------------------------------------------------
# 1. SSRF and URL Validation Tests
# -----------------------------------------------------------------------------

class TestSSRFProtection:
    """Test suite ensuring strict SSRF protection across various attack vectors."""

    @pytest.mark.parametrize(
        "blocked_url",
        [
            "http://localhost",
            "http://localhost:8000",
            "http://127.0.0.1",
            "http://127.0.0.1:4000/internal",
            "http://0.0.0.0",
            "http://10.0.0.1/admin",
            "http://10.255.255.254",
            "http://172.16.0.1",
            "http://172.31.255.255",
            "http://192.168.1.1",
            "http://192.168.0.100:8080",
            "http://169.254.169.254/latest/meta-data/",  # AWS/Cloud metadata
            "http://169.254.1.1",
            "http://metadata.google.internal/computeMetadata/v1/",
            "http://sub.localhost",
            "http://dev.internal",
        ],
    )
    def test_ssrf_blocks_private_and_metadata_addresses(self, blocked_url: str):
        with pytest.raises(SSRFValidationError):
            validate_and_sanitize_url(blocked_url, resolve_dns=False)

    @pytest.mark.parametrize(
        "invalid_scheme_url",
        [
            "ftp://example.com/file.txt",
            "file:///etc/passwd",
            "gopher://example.com",
            "javascript:alert(1)",
            "data:text/html,<html></html>",
            "ws://example.com/socket",
        ],
    )
    def test_ssrf_blocks_unsupported_schemes(self, invalid_scheme_url: str):
        with pytest.raises(URLValidationError):
            validate_and_sanitize_url(invalid_scheme_url, resolve_dns=False)

    @pytest.mark.parametrize("empty_url", ["", "   ", None])
    def test_ssrf_rejects_empty_urls(self, empty_url):
        with pytest.raises(URLValidationError):
            validate_and_sanitize_url(empty_url, resolve_dns=False)

    def test_ssrf_dns_rebinding_detection(self):
        """Ensure domains resolving to internal IP addresses are caught by DNS check."""
        with patch("app.utils.validators.socket.getaddrinfo") as mock_dns:
            # Mock DNS returning a private 192.168.1.5 address for a public-looking domain
            mock_dns.return_value = [
                (2, 1, 6, "", ("192.168.1.5", 80))
            ]
            with pytest.raises(SSRFValidationError) as exc:
                validate_and_sanitize_url("http://attacker-controlled-domain.com", resolve_dns=True)
            assert "resolves to blocked IP" in str(exc.value)

    def test_valid_public_url_allowed(self):
        url, _ = validate_and_sanitize_url("https://example.com", resolve_dns=False)
        assert url == "https://example.com"


# -----------------------------------------------------------------------------
# 2. HTML Extraction and Content Cleaning Tests
# -----------------------------------------------------------------------------

class TestHTMLExtraction:
    """Test suite verifying DOM cleaning, script stripping, and boilerplate removal."""

    def test_clean_and_extract_removes_noise(self):
        extractor = WebsiteExtractor()
        sample_html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Acme AI - Next Gen Automation</title>
            <meta name="description" content="Acme AI automates customer support with LLMs.">
            <meta property="og:site_name" content="Acme AI">
            <script>console.log("evil script");</script>
            <style>body { color: red; }</style>
        </head>
        <body>
            <nav><a href="/home">Home</a><a href="/pricing">Pricing</a></nav>
            <div class="cookie-banner">Accept cookies</div>
            <main>
                <h1>Automate Enterprise Support</h1>
                <p>Acme AI delivers AI agents that resolve customer queries instantly.</p>
                <h2>Key Capabilities</h2>
                <ul>
                    <li>Real-time chat resolution</li>
                    <li>Omnichannel CRM integration</li>
                </ul>
            </main>
            <footer>Copyright 2026 Acme</footer>
        </body>
        </html>
        """

        extracted = extractor._parse(sample_html, "https://acme.ai", "https://acme.ai")

        assert extracted.title == "Acme AI - Next Gen Automation"
        assert extracted.meta_description == "Acme AI automates customer support with LLMs."
        assert extracted.site_name == "Acme AI"
        assert "console.log" not in extracted.clean_text
        assert "Accept cookies" not in extracted.clean_text
        assert "Copyright 2026 Acme" not in extracted.clean_text
        assert "Automate Enterprise Support" in extracted.clean_text
        assert "Real-time chat resolution" in extracted.clean_text


# -----------------------------------------------------------------------------
# 3. Pydantic Schema Validation Tests
# -----------------------------------------------------------------------------

class TestSchemaValidation:
    """Ensure strict validation of all 5 required analysis sections."""

    def test_analysis_data_structure(self):
        queries = [
            TargetSearchQuery(platform="Google", query="ai support", search_intent="Commercial", business_relevance="High", target_audience="CTOs"),
            TargetSearchQuery(platform="Facebook", query="acme ai reviews", search_intent="Informational", business_relevance="Medium", target_audience="SMBs"),
            TargetSearchQuery(platform="Instagram", query="#aisupport", search_intent="Inspirational", business_relevance="Low", target_audience="Designers"),
            TargetSearchQuery(platform="LinkedIn", query="acme ai case studies", search_intent="Navigational", business_relevance="High", target_audience="Enterprise Executives"),
            TargetSearchQuery(platform="X", query="acme ai release notes", search_intent="Informational", business_relevance="Medium", target_audience="Developers"),
        ]

        services = [
            TopService(service_name=f"Service {i}", description="Desc", target_industry="Tech", target_customer="Buyers", main_benefit="ROI", is_inferred=False)
            for i in range(1, 6)
        ]

        competitors = [
            CompetitorDetail(name=f"Comp {i}", strengths=["Brand"], weaknesses_or_gaps=["Cost"], source="ai_inferred", is_inferred=True)
            for i in range(1, 4)
        ]

        analysis = AnalysisData(
            competitor_analysis=CompetitorAnalysis(
                brand_name="Acme AI",
                business_overview="Enterprise AI support platform",
                main_business_category="AI Software",
                main_products_services=["AI Chatbot", "Ticket Router"],
                competitors=competitors,
                brand_competitive_advantages=["Faster deployment"],
                positioning_opportunities=["Affordable tier"]
            ),
            target_search_queries=queries,
            seo_improvements=SEOImprovements(
                primary_keyword="ai support software",
                secondary_keywords=["customer ai", "bot support"],
                long_tail_keywords=["how to automate support tickets"],
                business_keywords=["Acme AI", "enterprise support"],
                recommended_seo_title=SEOTitleRecommendation(title="Acme AI | Automated Support", structure_rationale="Keyword first"),
                recommended_meta_description="Empower support teams with Acme AI automation.",
                supporting_content_ideas=SupportingContentIdeas(landing_pages=["AI Chatbot"])
            ),
            top_services=services,
            target_audience=TargetAudience(
                primary_target_audience="VP of Customer Support",
                secondary_target_audience="IT Directors",
                industry_segments=["SaaS", "E-Commerce"],
                business_types=["Enterprise", "Scaleup"],
                customer_profiles=["High ticket volume companies"],
                geographic_focus="Global",
                customer_needs_challenges=["Slow response times"],
                interests=["AI", "Automation"],
                marketing_segments=["High growth"]
            )
        )

        assert len(analysis.target_search_queries) == 5
        assert len(analysis.top_services) == 5
        assert len(analysis.competitor_analysis.competitors) >= 3


# -----------------------------------------------------------------------------
# 4. API Integration Tests (Mocked LLM & Extractor)
# -----------------------------------------------------------------------------

class TestAPIEndpoints:
    """Test FastAPI application endpoints, error handling, and caching."""

    def test_health_check(self, client: TestClient):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "version" in data

    def test_root_endpoint(self, client: TestClient):
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "documentation" in data

    def test_link_analysis_ssrf_blocking(self, client: TestClient):
        """Verify API blocks SSRF requests with HTTP 400."""
        payload = {"url": "http://127.0.0.1:4000/secret"}
        response = client.post("/link-analysis", json=payload)
        assert response.status_code == 400
        data = response.json()
        assert data["success"] is False
        assert data["error"] == "SSRF Protection Violation"
        assert "127.0.0.1" in data["detail"]

    def test_link_analysis_invalid_scheme(self, client: TestClient):
        payload = {"url": "ftp://example.com/resource"}
        response = client.post("/link-analysis", json=payload)
        assert response.status_code == 400
        data = response.json()
        assert data["success"] is False
        assert "Unsupported scheme" in data["detail"]

    def test_link_analysis_missing_url(self, client: TestClient):
        response = client.post("/link-analysis", json={})
        assert response.status_code == 422
        data = response.json()
        assert data["success"] is False

    @patch("app.services.analysis_service.WebsiteExtractor.fetch_and_extract")
    def test_link_analysis_success_flow(self, mock_fetch, client: TestClient):
        """Test successful end-to-end analysis with mocked website fetch."""
        mock_fetch.return_value = ExtractedWebsiteContent(
            url="https://acmeai-example.com",
            final_url="https://acmeai-example.com",
            title="Acme AI - Customer Automation",
            meta_description="Revolutionize customer support with conversational AI.",
            site_name="Acme AI",
            headings=["<h1>Enterprise AI Solutions</h1>", "<h2>Omnichannel Integration</h2>"],
            clean_text="Acme AI builds customer support bots for large scale enterprises.",
            social_links={"linkedin": "https://linkedin.com/company/acme"},
            raw_html_length=1200,
            clean_text_length=500,
        )

        payload = {"url": "https://acmeai-example.com"}
        response = client.post("/link-analysis", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["website"] == "https://acmeai-example.com"
        assert "analysis" in data

        analysis = data["analysis"]
        # Verify 5 sections
        assert "competitor_analysis" in analysis
        assert "target_search_queries" in analysis
        assert "seo_improvements" in analysis
        assert "top_services" in analysis
        assert "target_audience" in analysis

        assert len(analysis["target_search_queries"]) == 5
        assert len(analysis["top_services"]) == 5
        assert len(analysis["competitor_analysis"]["competitors"]) >= 3

        # Verify caching on second call
        second_response = client.post("/link-analysis", json=payload)
        assert second_response.status_code == 200
        assert second_response.json()["metadata"]["cached"] is True

    @patch("app.services.analysis_service.WebsiteExtractor.fetch_and_extract")
    def test_link_analysis_target_not_found(self, mock_fetch, client: TestClient):
        mock_fetch.side_effect = WebsiteNotFoundError("Page 404")
        response = client.post("/link-analysis", json={"url": "https://example.com/not-found"})
        assert response.status_code == 404
        data = response.json()
        assert data["success"] is False
        assert data["error"] == "Target Website Not Found"

    @patch("app.services.analysis_service.WebsiteExtractor.fetch_and_extract")
    def test_link_analysis_target_timeout(self, mock_fetch, client: TestClient):
        mock_fetch.side_effect = WebsiteTimeoutError("Timed out")
        response = client.post("/link-analysis", json={"url": "https://example.com/slow"})
        assert response.status_code == 504
        data = response.json()
        assert data["success"] is False
        assert data["error"] == "Target Website Timeout"
