import re
from typing import List, Set, Tuple
from urllib.parse import urlsplit

from app.schemas import CompetitorDetail


class CompetitorService:
    """Service to detect competitor mentions on-page and enrich/validate competitor intelligence."""

    # Common comparison or alternative keywords often found on SaaS/tech sites
    COMPARISON_REGEX = re.compile(
        r"(?:alternative to|alternatives to|vs\.?|versus|compare with|switch from|better than)\s+([A-Za-z0-9\.\-]+)",
        re.I
    )

    def extract_onpage_competitor_signals(self, clean_text: str, external_links: List[str], current_domain: str) -> List[str]:
        """Scans extracted website text and external links for explicit competitor or alternative mentions."""
        discovered: Set[str] = set()

        # Check comparison patterns in text
        for match in self.COMPARISON_REGEX.finditer(clean_text):
            candidate = match.group(1).strip().rstrip(".,;:!?")
            if candidate and len(candidate) > 2 and candidate.lower() not in ("the", "a", "an", "our", "other", current_domain.lower()):
                discovered.add(candidate.title())

        return list(discovered)[:5]

    def ensure_minimum_competitors(
        self,
        competitors: List[CompetitorDetail],
        business_category: str,
        brand_name: str
    ) -> List[CompetitorDetail]:
        """
        Validates that at least 3 competitors are returned. If fewer, supplements
        with market-standard sector competitors labeled as AI-inferred.
        """
        if not competitors:
            competitors = []

        # Deduplicate existing
        seen_names = set()
        clean_list: List[CompetitorDetail] = []
        for c in competitors:
            norm_name = c.name.strip().lower()
            if norm_name and norm_name not in seen_names and norm_name != brand_name.lower():
                seen_names.add(norm_name)
                # Ensure is_inferred matches source
                if c.source == "ai_inferred":
                    c.is_inferred = True
                clean_list.append(c)

        # Fallback category competitors if fewer than 3
        fallback_map = {
            "saas": ["Salesforce", "HubSpot", "Zoho"],
            "ai": ["OpenAI", "Anthropic", "Cohere"],
            "speech": ["Nuance", "Deepgram", "AssemblyAI"],
            "cloud": ["AWS", "Google Cloud", "Microsoft Azure"],
            "fintech": ["Stripe", "Adyen", "Square"],
            "e-commerce": ["Shopify", "WooCommerce", "BigCommerce"],
            "marketing": ["Semrush", "Ahrefs", "Moz"],
        }

        if len(clean_list) < 3:
            # Pick fallback competitors based on category
            category_lower = business_category.lower()
            chosen_defaults = ["Industry Peer A", "Industry Peer B", "Industry Peer C"]
            for key, defaults in fallback_map.items():
                if key in category_lower:
                    chosen_defaults = defaults
                    break

            for name in chosen_defaults:
                if len(clean_list) >= 3:
                    break
                if name.lower() not in seen_names and name.lower() != brand_name.lower():
                    seen_names.add(name.lower())
                    clean_list.append(
                        CompetitorDetail(
                            name=name,
                            website_or_domain=f"{name.lower().replace(' ', '')}.com",
                            strengths=[f"Established presence in {business_category} market", "Broad brand recognition"],
                            weaknesses_or_gaps=["Higher cost structure", "Less personalized niche customization"],
                            source="ai_inferred",
                            is_inferred=True
                        )
                    )

        return clean_list[:5]
