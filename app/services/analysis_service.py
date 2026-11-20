from collections import OrderedDict
from datetime import datetime, timezone
import logging
import time
from typing import Dict, Optional, Tuple

from app.config import get_settings
from app.schemas import AnalysisMetadata, LinkAnalysisResponse
from app.services.competitor_service import CompetitorService
from app.services.llm_service import LLMService
from app.services.website_extractor import WebsiteExtractor

logger = logging.getLogger(__name__)


class AnalysisService:
    """Orchestrates end-to-end link analysis: extraction, competitor analysis, LLM inference, and caching."""

    def __init__(self):
        self.settings = get_settings()
        self.extractor = WebsiteExtractor()
        self.competitor_service = CompetitorService()
        self.llm_service = LLMService()
        # In-memory LRU Cache (URL -> (timestamp, LinkAnalysisResponse))
        self._cache: OrderedDict[str, Tuple[float, LinkAnalysisResponse]] = OrderedDict()

    def _get_from_cache(self, url: str) -> Optional[LinkAnalysisResponse]:
        """Retrieves cached response if valid under TTL."""
        if not self.settings.CACHE_ENABLED:
            return None

        clean_url = url.strip().lower()
        if clean_url in self._cache:
            cached_time, response = self._cache[clean_url]
            if (time.time() - cached_time) < self.settings.CACHE_TTL_SECONDS:
                # Move to end (LRU)
                self._cache.move_to_end(clean_url)
                # Clone and mark cached
                cached_copy = response.model_copy(deep=True)
                if cached_copy.metadata:
                    cached_copy.metadata.cached = True
                return cached_copy
            else:
                # Expired
                del self._cache[clean_url]
        return None

    def _save_to_cache(self, url: str, response: LinkAnalysisResponse) -> None:
        """Stores analysis response in LRU cache."""
        if not self.settings.CACHE_ENABLED:
            return

        clean_url = url.strip().lower()
        if len(self._cache) >= self.settings.CACHE_MAX_ITEMS:
            # Pop oldest item
            self._cache.popitem(last=False)

        self._cache[clean_url] = (time.time(), response)

    async def analyze_link(self, url: str) -> LinkAnalysisResponse:
        """
        Main execution flow:
        1. Check Cache
        2. Fetch & Clean Website Content (with SSRF check)
        3. Detect Competitor Signals
        4. LLM Analysis
        5. Verify and enrich competitor items
        6. Cache and return final response
        """
        start_time = time.time()

        # Step 1: Check cache
        cached_response = self._get_from_cache(url)
        if cached_response:
            logger.info(f"Returning cached analysis for '{url}'")
            return cached_response

        # Step 2: Fetch and clean HTML
        content = await self.extractor.fetch_and_extract(url)

        # Step 3: Detect competitor signals
        competitor_signals = self.competitor_service.extract_onpage_competitor_signals(
            clean_text=content.clean_text,
            external_links=content.external_links,
            current_domain=content.final_url
        )

        # Step 4: Run LLM Inference
        analysis_data, model_used, in_tokens, out_tokens = await self.llm_service.analyze_website_content(
            content=content,
            competitor_signals=competitor_signals
        )

        # Step 5: Ensure minimum 3 competitors and proper labeling
        analysis_data.competitor_analysis.competitors = self.competitor_service.ensure_minimum_competitors(
            competitors=analysis_data.competitor_analysis.competitors,
            business_category=analysis_data.competitor_analysis.main_business_category,
            brand_name=analysis_data.competitor_analysis.brand_name
        )

        elapsed_ms = round((time.time() - start_time) * 1000, 2)

        metadata = AnalysisMetadata(
            analyzed_at=datetime.now(timezone.utc).isoformat(),
            execution_time_ms=elapsed_ms,
            model_used=model_used,
            cached=False,
            content_characters_analyzed=content.clean_text_length,
            estimated_input_tokens=in_tokens,
            estimated_output_tokens=out_tokens,
        )

        response = LinkAnalysisResponse(
            success=True,
            website=content.final_url,
            brand=analysis_data.competitor_analysis.brand_name,
            analysis=analysis_data,
            metadata=metadata
        )

        # Step 6: Store in cache
        self._save_to_cache(url, response)

        return response
