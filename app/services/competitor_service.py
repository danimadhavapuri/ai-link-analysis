"""
Competitor-signal detection + minimum-competitor guarantee.
"""
import re
from typing import List, Set

from app.schemas import CompetitorDetail


_CMP_RE = re.compile(
    r"(?:alternative(?:s)? to|vs\.?|versus|compare with|switch from|better than)\s+"
    r"([A-Za-z0-9][A-Za-z0-9 \.\-]{1,30})",
    re.I,
)

# Fallback competitors by broad category keyword
_FALLBACK_BY_CATEGORY = {
    "ai":        [("Hugging Face", "huggingface.co"),
                  ("Cohere",       "cohere.com"),
                  ("Anthropic",    "anthropic.com")],
    "speech":    [("Deepgram",   "deepgram.com"),
                  ("AssemblyAI", "assemblyai.com"),
                  ("Nuance",     "nuance.com")],
    "saas":      [("Salesforce", "salesforce.com"),
                  ("HubSpot",    "hubspot.com"),
                  ("Zoho",       "zoho.com")],
    "cloud":     [("AWS",            "aws.amazon.com"),
                  ("Google Cloud",   "cloud.google.com"),
                  ("Microsoft Azure","azure.microsoft.com")],
    "fintech":   [("Stripe",  "stripe.com"),
                  ("Adyen",   "adyen.com"),
                  ("Square",  "squareup.com")],
    "marketing": [("Semrush", "semrush.com"),
                  ("Ahrefs",  "ahrefs.com"),
                  ("Moz",     "moz.com")],
    "ecommerce": [("Shopify",    "shopify.com"),
                  ("WooCommerce","woocommerce.com"),
                  ("BigCommerce","bigcommerce.com")],
}

_DEFAULT_FALLBACK = [
    ("Industry Leader Alpha", "industryleaderalpha.com"),
    ("Sector Peer Beta",      "sectorpeerbeta.io"),
    ("Challenger Gamma",      "challengergamma.ai"),
]


class CompetitorService:

    def extract_onpage_competitor_signals(
        self, clean_text: str, external_links: List[str], current_domain: str
    ) -> List[str]:
        found: Set[str] = set()
        for m in _CMP_RE.finditer(clean_text):
            cand = m.group(1).strip().rstrip(".,;:!?")
            if cand and len(cand) > 2 and cand.lower() not in ("the", "a", "an", current_domain.lower()):
                found.add(cand.title())
        return sorted(found)[:5]

    def ensure_minimum_competitors(
        self,
        competitors: List[CompetitorDetail],
        business_category: str,
        brand_name: str,
    ) -> List[CompetitorDetail]:
        # Deduplicate
        seen: Set[str] = set()
        clean: List[CompetitorDetail] = []
        for c in competitors:
            key = c.name.strip().lower()
            if key and key not in seen and key != brand_name.lower():
                seen.add(key)
                c.is_inferred = c.source == "ai_inferred"
                clean.append(c)

        if len(clean) >= 3:
            return clean[:5]

        # Pick fallback list by category keyword
        cat = business_category.lower()
        fallback_list = _DEFAULT_FALLBACK
        for kw, entries in _FALLBACK_BY_CATEGORY.items():
            if kw in cat:
                fallback_list = entries
                break

        for name, domain in fallback_list:
            if len(clean) >= 3:
                break
            if name.lower() not in seen and name.lower() != brand_name.lower():
                seen.add(name.lower())
                clean.append(CompetitorDetail(
                    name=name,
                    website_or_domain=domain,
                    strengths=["Established market presence", "Brand recognition"],
                    weaknesses_or_gaps=["Higher cost structure", "Less specialised niche focus"],
                    source="ai_inferred",
                    is_inferred=True,
                ))

        return clean[:5]
