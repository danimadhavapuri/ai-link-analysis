"""
Pydantic v2 schemas — request, all 5 analysis sections, response, and errors.
"""
from datetime import datetime, timezone
from typing import List, Literal, Optional
from pydantic import BaseModel, Field, field_validator


# ═══════════════════════════════════════════════════════════════════════════════
# Request
# ═══════════════════════════════════════════════════════════════════════════════

class LinkAnalysisRequest(BaseModel):
    url: str = Field(
        ...,
        description="Full URL of the target website (http or https only).",
        examples=["https://stripe.com", "https://chivoxai.com"],
    )

    @field_validator("url")
    @classmethod
    def _strip(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("url must be a non-empty string")
        return v.strip()


# ═══════════════════════════════════════════════════════════════════════════════
# Section 1 — Competitor Analysis
# ═══════════════════════════════════════════════════════════════════════════════

class CompetitorDetail(BaseModel):
    name: str
    website_or_domain: Optional[str] = None
    strengths: List[str] = Field(default_factory=list)
    weaknesses_or_gaps: List[str] = Field(default_factory=list)
    source: Literal["extracted_from_site", "ai_inferred"]
    is_inferred: bool = Field(
        ..., description="True when AI-suggested; False when found on the site."
    )


class CompetitorAnalysis(BaseModel):
    brand_name: str
    business_overview: str
    main_business_category: str
    main_products_services: List[str]
    competitors: List[CompetitorDetail] = Field(..., min_length=3)
    brand_competitive_advantages: List[str]
    positioning_opportunities: List[str]


# ═══════════════════════════════════════════════════════════════════════════════
# Section 2 — Target Search Queries
# ═══════════════════════════════════════════════════════════════════════════════

Platform = Literal["Google", "Facebook", "Instagram", "LinkedIn", "X"]


class TargetSearchQuery(BaseModel):
    platform: Platform
    query: str
    search_intent: str
    business_relevance: str
    target_audience: str


# ═══════════════════════════════════════════════════════════════════════════════
# Section 3 — SEO Improvements
# ═══════════════════════════════════════════════════════════════════════════════

class SEOTitleRecommendation(BaseModel):
    title: str
    structure_rationale: str

# Alias kept for backward-compat with existing test imports
RecommendedTitle = SEOTitleRecommendation


class SupportingContentIdeas(BaseModel):
    landing_pages: List[str] = Field(default_factory=list)
    industry_pages: List[str] = Field(default_factory=list)
    faqs: List[str] = Field(default_factory=list)
    blog_topics: List[str] = Field(default_factory=list)
    location_pages: List[str] = Field(default_factory=list)
    articles: List[str] = Field(default_factory=list)


class SEOImprovements(BaseModel):
    primary_keyword: str
    secondary_keywords: List[str]
    long_tail_keywords: List[str]
    business_keywords: List[str]
    recommended_seo_title: SEOTitleRecommendation
    recommended_meta_description: str = Field(
        ..., description="≤160 characters, human-friendly, keyword-rich."
    )
    supporting_content_ideas: SupportingContentIdeas


# ═══════════════════════════════════════════════════════════════════════════════
# Section 4 — Top 5 Services
# ═══════════════════════════════════════════════════════════════════════════════

class TopService(BaseModel):
    service_name: str
    description: str
    target_industry: str
    target_customer: str
    main_benefit: str
    is_inferred: bool = Field(
        ..., description="False = from site; True = AI-inferred."
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Section 5 — Target Audience
# ═══════════════════════════════════════════════════════════════════════════════

class TargetAudience(BaseModel):
    primary_target_audience: str
    secondary_target_audience: str
    industry_segments: List[str]
    business_types: List[str]
    customer_profiles: List[str]
    geographic_focus: Optional[str] = None
    customer_needs_challenges: List[str]
    interests: List[str]
    marketing_segments: List[str]


# ═══════════════════════════════════════════════════════════════════════════════
# Aggregated Analysis
# ═══════════════════════════════════════════════════════════════════════════════

class AnalysisData(BaseModel):
    competitor_analysis: CompetitorAnalysis
    target_search_queries: List[TargetSearchQuery] = Field(
        ..., min_length=5, max_length=5,
        description="Exactly 5 queries: one per platform (Google, Facebook, Instagram, LinkedIn, X).",
    )
    seo_improvements: SEOImprovements
    top_services: List[TopService] = Field(
        ..., min_length=5, max_length=5,
        description="Exactly 5 services grounded in site content.",
    )
    target_audience: TargetAudience


# ═══════════════════════════════════════════════════════════════════════════════
# Metadata & Full Response
# ═══════════════════════════════════════════════════════════════════════════════

class AnalysisMetadata(BaseModel):
    analyzed_at: str
    execution_time_ms: float
    model_used: str
    cached: bool = False
    content_characters_analyzed: int
    estimated_input_tokens: int
    estimated_output_tokens: int


class LinkAnalysisResponse(BaseModel):
    success: bool = True
    website: str
    brand: str
    analysis: AnalysisData
    metadata: Optional[AnalysisMetadata] = None


# ═══════════════════════════════════════════════════════════════════════════════
# Error Response
# ═══════════════════════════════════════════════════════════════════════════════

class ErrorResponse(BaseModel):
    success: bool = False
    error: str
    detail: Optional[str] = None
    status_code: int
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
