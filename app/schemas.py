from datetime import datetime, timezone
from typing import List, Literal, Optional
from pydantic import BaseModel, Field, HttpUrl, field_validator


# ---------------------------------------------------------
# Request Schema
# ---------------------------------------------------------

class LinkAnalysisRequest(BaseModel):
    """Request payload for website link analysis."""
    url: str = Field(
        ...,
        description="Full URL of the website to analyze (must begin with http:// or https://)",
        examples=["https://chivoxai.com", "https://stripe.com"]
    )

    @field_validator("url")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("URL cannot be empty")
        return v.strip()


# ---------------------------------------------------------
# Section 1: Competitor Analysis
# ---------------------------------------------------------

class CompetitorDetail(BaseModel):
    """Details for a single competitor."""
    name: str = Field(..., description="Name of the competitor")
    website_or_domain: Optional[str] = Field(
        None,
        description="Domain or website of the competitor if known"
    )
    strengths: List[str] = Field(
        default_factory=list,
        description="Observed or known strengths of the competitor"
    )
    weaknesses_or_gaps: List[str] = Field(
        default_factory=list,
        description="Gaps or weaknesses in the competitor's offerings"
    )
    source: Literal["extracted_from_site", "ai_inferred"] = Field(
        ...,
        description="Whether this competitor was explicitly found on the site or AI-inferred"
    )
    is_inferred: bool = Field(
        ...,
        description="True if suggested by AI; False if explicitly referenced in site content"
    )


class CompetitorAnalysis(BaseModel):
    """Section 1: Competitor vs Your Brand Details."""
    brand_name: str = Field(..., description="Identified brand or business name")
    business_overview: str = Field(..., description="High-level overview of the business")
    main_business_category: str = Field(..., description="Primary industry category")
    main_products_services: List[str] = Field(
        ...,
        description="Key products or services offered by the brand"
    )
    competitors: List[CompetitorDetail] = Field(
        ...,
        min_length=3,
        description="At least 3 relevant competitors, clearly labeled if inferred"
    )
    brand_competitive_advantages: List[str] = Field(
        ...,
        description="Distinct competitive strengths and value propositions of the brand"
    )
    positioning_opportunities: List[str] = Field(
        ...,
        description="Strategic positioning or differentiation opportunities in the market"
    )


# ---------------------------------------------------------
# Section 2: Top 5 Target Search Queries
# ---------------------------------------------------------

PlatformLiteral = Literal["Google", "Facebook", "Instagram", "LinkedIn", "X"]


class TargetSearchQuery(BaseModel):
    """Search query tailored for a specific platform."""
    platform: PlatformLiteral = Field(
        ...,
        description="Target platform: Google, Facebook, Instagram, LinkedIn, or X"
    )
    query: str = Field(..., description="The exact search query or phrase")
    search_intent: str = Field(
        ...,
        description="Intent type (e.g., Informational, Commercial Investigation, Transactional, Navigational)"
    )
    business_relevance: str = Field(
        ...,
        description="Why this query is commercially relevant to the business"
    )
    target_audience: str = Field(
        ...,
        description="Segment of users searching for this query"
    )


# ---------------------------------------------------------
# Section 3: SEO Improvement
# ---------------------------------------------------------

class SEOTitleRecommendation(BaseModel):
    """Recommended SEO title and structural rationale."""
    title: str = Field(..., description="Optimized page title containing primary keyword")
    structure_rationale: str = Field(
        ...,
        description="Rationale explaining keyword placement and click-through appeal"
    )

RecommendedTitle = SEOTitleRecommendation


class SupportingContentIdeas(BaseModel):
    """Content ideas to strengthen organic visibility."""
    landing_pages: List[str] = Field(default_factory=list, description="Targeted landing page concepts")
    industry_pages: List[str] = Field(default_factory=list, description="Industry-specific vertical pages")
    faqs: List[str] = Field(default_factory=list, description="Customer questions and FAQ topics")
    blog_topics: List[str] = Field(default_factory=list, description="In-depth blog and thought leadership ideas")
    location_pages: List[str] = Field(default_factory=list, description="Geo-targeted pages if relevant")
    articles: List[str] = Field(default_factory=list, description="Technical or educational article concepts")


class SEOImprovements(BaseModel):
    """Section 3: SEO Keywords, Title, Meta Description & Content Ideas."""
    primary_keyword: str = Field(..., description="Core search keyword representing the primary offering")
    secondary_keywords: List[str] = Field(..., description="Secondary high-relevance keywords")
    long_tail_keywords: List[str] = Field(..., description="Specific, low-competition long-tail query phrases")
    business_keywords: List[str] = Field(..., description="Brand and industry-defining commercial keywords")
    recommended_seo_title: SEOTitleRecommendation = Field(
        ...,
        description="Optimized title tag and rationale"
    )
    recommended_meta_description: str = Field(
        ...,
        description="Human-friendly meta description under 160 characters with primary keywords"
    )
    supporting_content_ideas: SupportingContentIdeas = Field(
        ...,
        description="Categorized content expansion concepts"
    )


# ---------------------------------------------------------
# Section 4: Top 5 Services
# ---------------------------------------------------------

class TopService(BaseModel):
    """Detailed profile of a key service or product offering."""
    service_name: str = Field(..., description="Name of the service or product")
    description: str = Field(..., description="Comprehensive summary of what the service delivers")
    target_industry: str = Field(..., description="Industry or sector benefiting from this service")
    target_customer: str = Field(..., description="Specific customer persona or role (e.g. CTOs, Growth Leads)")
    main_benefit: str = Field(..., description="Primary measurable or qualitative ROI/advantage")
    is_inferred: bool = Field(
        ...,
        description="False if explicitly described on website; True if inferred by AI based on context"
    )


# ---------------------------------------------------------
# Section 5: Target Audience Identification
# ---------------------------------------------------------

class TargetAudience(BaseModel):
    """Section 5: Customer personas, demographics, and market segmentation."""
    primary_target_audience: str = Field(..., description="Core primary buyer persona")
    secondary_target_audience: str = Field(..., description="Influencer, secondary buyer, or end user persona")
    industry_segments: List[str] = Field(..., description="Primary vertical sectors addressed")
    business_types: List[str] = Field(
        ...,
        description="Organizational profiles (e.g., B2B SaaS, Early-stage Startups, Enterprise)"
    )
    customer_profiles: List[str] = Field(
        ...,
        description="Key attributes, company sizes, and maturity levels of ideal clients"
    )
    geographic_focus: Optional[str] = Field(
        None,
        description="Geographic region (Global, North America, India, APAC, etc.) if stated or evident"
    )
    customer_needs_challenges: List[str] = Field(
        ...,
        description="Pain points and strategic challenges faced by these customers"
    )
    interests: List[str] = Field(
        ...,
        description="Professional interests, technologies, and priorities of target decision-makers"
    )
    marketing_segments: List[str] = Field(
        ...,
        description="Marketing and campaign positioning segments"
    )


# ---------------------------------------------------------
# Aggregated Analysis Schema
# ---------------------------------------------------------

class AnalysisData(BaseModel):
    """The 5 required analysis sections grounded in website content."""
    competitor_analysis: CompetitorAnalysis
    target_search_queries: List[TargetSearchQuery] = Field(
        ...,
        min_length=5,
        max_length=5,
        description="Exactly 5 queries covering Google, Facebook, Instagram, LinkedIn, and X"
    )
    seo_improvements: SEOImprovements
    top_services: List[TopService] = Field(
        ...,
        min_length=5,
        max_length=5,
        description="Exactly 5 key services or products"
    )
    target_audience: TargetAudience


class AnalysisMetadata(BaseModel):
    """Metadata regarding analysis execution."""
    analyzed_at: str
    execution_time_ms: float
    model_used: str
    cached: bool = False
    content_characters_analyzed: int
    estimated_input_tokens: int
    estimated_output_tokens: int


class LinkAnalysisResponse(BaseModel):
    """Complete structured JSON response for POST /link-analysis."""
    success: bool = True
    website: str
    brand: str
    analysis: AnalysisData
    metadata: Optional[AnalysisMetadata] = None


# ---------------------------------------------------------
# Error Response Schema
# ---------------------------------------------------------

class ErrorResponse(BaseModel):
    """Structured error response returned on validation or extraction failure."""
    success: bool = False
    error: str
    detail: Optional[str] = None
    status_code: int
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
