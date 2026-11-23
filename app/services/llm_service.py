"""
LLM orchestration:
  • Primary: Gemini 2.5 Flash  (gemini-2.5-flash)
  • Fallback: Gemini 2.0 Flash (gemini-2.0-flash)
  • Offline: content-grounded heuristic engine (no API key needed)

The heuristic engine is used automatically when GEMINI_API_KEY is absent or
all LLM calls fail. It produces templated but content-grounded output — good
enough for local dev and CI.
"""
import json
import logging
import re
from typing import List, Tuple

from app.config import get_settings
from app.schemas import (
    AnalysisData,
    CompetitorAnalysis,
    CompetitorDetail,
    SEOImprovements,
    SEOTitleRecommendation,
    SupportingContentIdeas,
    TargetAudience,
    TargetSearchQuery,
    TopService,
)
from app.services.website_extractor import ExtractedWebsiteContent

logger = logging.getLogger(__name__)

# ── Prompt constants ──────────────────────────────────────────────────────────

_SYSTEM = """\
You are an elite Senior Digital Strategist, Market Researcher, and Technical SEO Architect.

CRITICAL RULES
1. Base ALL insights strictly on the extracted website content provided. Never fabricate.
2. Do NOT invent search volumes, ranking numbers, or traffic figures.
3. Return EXACTLY 5 target_search_queries — one per platform in this order:
   Google → Facebook → Instagram → LinkedIn → X.
4. Return EXACTLY 5 top_services. If the site lists fewer, infer adjacent offerings
   and mark is_inferred: true.
5. Provide at least 3 competitors. Mark source as "extracted_from_site" if explicitly
   found on the site, or "ai_inferred" (is_inferred: true) if suggested by market context.
6. Output MUST be valid JSON matching the schema provided via response_schema.
"""


def _build_prompt(content: ExtractedWebsiteContent, signals: List[str]) -> str:
    sigs = ", ".join(signals) if signals else "None detected on-page"
    return f"""\
Target URL : {content.url}
Final URL  : {content.final_url}
Title      : {content.title or "N/A"}
Site Name  : {content.site_name or "N/A"}
Meta Desc  : {content.meta_description or "N/A"}

On-page competitor signals : {sigs}

Social links found:
{json.dumps(content.social_links, indent=2)}

Extracted website content:
\"\"\"
{content.clean_text}
\"\"\"

Produce a deep analysis across all 5 dimensions:
1. competitor_analysis (brand_name, business_overview, main_business_category,
   main_products_services, competitors≥3, brand_competitive_advantages, positioning_opportunities)
2. target_search_queries — EXACTLY 5, platforms: Google, Facebook, Instagram, LinkedIn, X
3. seo_improvements (keywords, recommended_seo_title, recommended_meta_description ≤160 chars,
   supporting_content_ideas)
4. top_services — EXACTLY 5 (service_name, description, target_industry, target_customer,
   main_benefit, is_inferred)
5. target_audience (primary/secondary, segments, profiles, geographic_focus, challenges, interests)
"""


# ── LLM service ───────────────────────────────────────────────────────────────

class LLMServiceError(Exception):
    def __init__(self, msg: str, status_code: int = 502):
        super().__init__(msg)
        self.message = msg
        self.status_code = status_code


class LLMService:

    def __init__(self):
        self.cfg = get_settings()
        self._client = None
        self._init_client()

    def _init_client(self):
        key = self.cfg.GEMINI_API_KEY.strip()
        if key:
            try:
                from google import genai
                self._client = genai.Client(api_key=key)
                logger.info("Gemini client initialised (model=%s).", self.cfg.GEMINI_MODEL)
            except Exception as exc:
                logger.warning("Could not initialise Gemini client: %s", exc)

    async def analyze_website_content(
        self,
        content: ExtractedWebsiteContent,
        competitor_signals: List[str],
    ) -> Tuple[AnalysisData, str, int, int]:
        """
        Returns (AnalysisData, model_name, estimated_input_tokens, estimated_output_tokens).
        """
        prompt = _build_prompt(content, competitor_signals)
        est_in = len(prompt) // 4 + 150

        if not self._client:
            logger.info("No Gemini API key — using heuristic engine.")
            data = self._heuristic(content, competitor_signals)
            return data, "grounded-heuristic-engine", est_in, 950

        models = [self.cfg.GEMINI_MODEL, "gemini-3.8-flash", "gemini-2.5-flash"]
        unique_models = list(dict.fromkeys(models))
        last_exc: Exception | None = None

        for model in unique_models:
            for use_thinking in [True, False]:
                try:
                    from google.genai import types

                    config_kwargs = dict(
                        system_instruction=_SYSTEM,
                        response_mime_type="application/json",
                        response_schema=AnalysisData,
                        temperature=0.2,
                    )

                    if use_thinking and hasattr(types, "ThinkingConfig"):
                        thinking_level = self.cfg.THINKING_LEVEL.lower()
                        if thinking_level == "none":
                            config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
                        elif thinking_level == "low":
                            config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=1024)
                        elif thinking_level == "medium":
                            config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=8192)
                        elif thinking_level == "high":
                            config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=24576)

                    resp = self._client.models.generate_content(
                        model=model,
                        contents=prompt,
                        config=types.GenerateContentConfig(**config_kwargs),
                    )

                    text = resp.text
                    if not text:
                        continue

                    data = AnalysisData.model_validate(json.loads(text))
                    return data, model, est_in, len(text) // 4

                except LLMServiceError:
                    raise
                except Exception as exc:
                    logger.warning("Model '%s' (thinking=%s) failed: %s", model, use_thinking, exc)
                    last_exc = exc
                    if not use_thinking:
                        break

        logger.error("All LLM models failed (%s). Falling back to grounded heuristic engine.", last_exc)
        data = self._heuristic(content, competitor_signals)
        return data, "grounded-heuristic-engine", est_in, 950

    # ── Heuristic (offline) engine ────────────────────────────────────────────

    def _heuristic(
        self, content: ExtractedWebsiteContent, signals: List[str]
    ) -> AnalysisData:
        # Brand name
        brand = content.site_name
        if not brand and content.title:
            brand = re.split(r"[\-|:–•]", content.title)[0].strip()
        brand = brand or "Target Brand"

        overview = content.meta_description or (
            f"{brand} provides specialised services identified through its website."
        )

        # Category
        text_lower = content.clean_text.lower()
        if "artificial intelligence" in text_lower or " ai " in text_lower:
            category = "Artificial Intelligence & Software"
        elif "marketing" in text_lower or "seo" in text_lower:
            category = "Digital Marketing & SEO"
        elif "ecommerce" in text_lower or "e-commerce" in text_lower:
            category = "E-Commerce & Retail"
        elif "fintech" in text_lower or "payment" in text_lower:
            category = "Financial Technology"
        else:
            category = "Technology & Digital Services"

        # Services from headings
        clean_headings = [
            re.sub(r"<[^>]+>", "", h).strip()
            for h in content.headings
            if 5 < len(re.sub(r"<[^>]+>", "", h).strip()) < 60
        ]
        default_svc = [
            ("Core Platform Service",           False),
            ("Integration & API Solutions",     True),
            ("Analytics & Reporting Dashboard", True),
            ("Enterprise Custom Deployment",    True),
            ("Consulting & Strategic Advisory", True),
        ]
        services: List[TopService] = []
        for i in range(5):
            if i < len(clean_headings):
                name, inferred = clean_headings[i], False
            else:
                name, inferred = default_svc[i]
            services.append(TopService(
                service_name=name,
                description=f"{brand} offering focused on {name.lower()}.",
                target_industry=category,
                target_customer="CTOs, Growth Leads, and Operations Managers",
                main_benefit=f"Accelerates value delivery and reduces operational overhead for {brand} clients.",
                is_inferred=inferred,
            ))

        competitors = [
            CompetitorDetail(
                name="Industry Leader Alpha",
                website_or_domain="industryleaderalpha.com",
                strengths=["Broad market recognition", "Global distribution"],
                weaknesses_or_gaps=["Premium pricing", "Legacy architecture"],
                source="ai_inferred", is_inferred=True,
            ),
            CompetitorDetail(
                name="Sector Peer Beta",
                website_or_domain="sectorpeerbeta.io",
                strengths=["Modern UI/UX", "Active developer community"],
                weaknesses_or_gaps=["Limited enterprise support", "Narrower integrations"],
                source="ai_inferred", is_inferred=True,
            ),
            CompetitorDetail(
                name="Challenger Gamma",
                website_or_domain="challengergamma.ai",
                strengths=["Competitive entry pricing", "Fast onboarding"],
                weaknesses_or_gaps=["Shallower feature set", "Fewer compliance certifications"],
                source="ai_inferred", is_inferred=True,
            ),
        ]

        queries = [
            TargetSearchQuery(
                platform="Google",
                query=f"best {category.lower()} platform for businesses",
                search_intent="Commercial Investigation",
                business_relevance=f"High buying-intent query targeting evaluators of {brand}.",
                target_audience="Decision makers comparing enterprise solutions.",
            ),
            TargetSearchQuery(
                platform="Facebook",
                query=f"{brand} reviews and customer success stories",
                search_intent="Informational / Social Proof",
                business_relevance="Builds trust through peer recommendations and case studies.",
                target_audience="SMB owners and marketing directors.",
            ),
            TargetSearchQuery(
                platform="Instagram",
                query=f"#{brand.lower().replace(' ', '')} innovation",
                search_intent="Inspirational / Brand Discovery",
                business_relevance="Visual brand awareness among tech-savvy professionals.",
                target_audience="Founders, designers, and younger tech enthusiasts.",
            ),
            TargetSearchQuery(
                platform="LinkedIn",
                query=f"{brand} enterprise solutions and ROI case studies",
                search_intent="B2B Research & Evaluation",
                business_relevance="Engages C-suite evaluating vendor credibility and partnerships.",
                target_audience="VPs of Engineering, Procurement Leaders, and CTOs.",
            ),
            TargetSearchQuery(
                platform="X",
                query=f"{brand} product launch and updates",
                search_intent="Real-time News & Sentiment",
                business_relevance="Community engagement around feature releases and company news.",
                target_audience="Developers, analysts, and early adopters.",
            ),
        ]

        pk = f"{brand} {category.split()[0].lower()}"
        seo = SEOImprovements(
            primary_keyword=pk,
            secondary_keywords=[f"{brand} software", f"best {category.lower()}", "enterprise platform"],
            long_tail_keywords=[
                f"how {brand} helps businesses with {category.lower()}",
                f"{brand} alternatives for startups and SMBs",
                f"cost of {category.lower()} software solutions",
            ],
            business_keywords=[brand, category, "ROI", "B2B SaaS"],
            recommended_seo_title=SEOTitleRecommendation(
                title=f"{brand} | Leading {category} Solutions",
                structure_rationale="Brand first for recognition, followed by primary category keyword for relevance.",
            ),
            recommended_meta_description=(
                f"Discover {brand} — the {category.lower()} platform that streamlines operations, "
                f"boosts ROI, and scales with your business."
            )[:160],
            supporting_content_ideas=SupportingContentIdeas(
                landing_pages=[f"{brand} for Enterprise", f"{brand} Pricing & Plans"],
                industry_pages=["Healthcare & Life Sciences", "Fintech & Banking", "E-Commerce"],
                faqs=[f"How does {brand} integrate with existing systems?", "What security standards does it meet?"],
                blog_topics=[f"Top 5 Trends in {category}", "Digital Transformation Challenges & Solutions"],
                location_pages=["North America Enterprise", "APAC Growth Markets"],
                articles=["Technical Architecture Whitepaper", "ROI Benchmark Comparison"],
            ),
        )

        audience = TargetAudience(
            primary_target_audience="Enterprise decision makers and VP of Engineering",
            secondary_target_audience="Technical managers and implementation specialists",
            industry_segments=[category, "Information Technology", "Digital Commerce", "Financial Services"],
            business_types=["Mid-Market Enterprises", "High-Growth Scaleups", "Global Corporates"],
            customer_profiles=["Companies modernising legacy tech stacks", "Organisations prioritising speed-to-market"],
            geographic_focus="Global, with primary focus on English-speaking technology markets",
            customer_needs_challenges=["Legacy software bottlenecks", "High integration costs", "Talent scarcity"],
            interests=["Cloud computing", "Automation", "Developer tooling", "Operational efficiency"],
            marketing_segments=["Strategic Enterprise Accounts", "Digital-first Disruptors"],
        )

        comp_analysis = CompetitorAnalysis(
            brand_name=brand,
            business_overview=overview,
            main_business_category=category,
            main_products_services=[s.service_name for s in services],
            competitors=competitors,
            brand_competitive_advantages=[
                f"Proprietary technology tailored for {category}",
                "Developer-first experience with rapid deployment",
                "Cost-effective scaling vs legacy alternatives",
            ],
            positioning_opportunities=[
                "Serve underserved mid-market segments with affordable enterprise features",
                f"Position as the agile, AI-first alternative in {category}",
            ],
        )

        return AnalysisData(
            competitor_analysis=comp_analysis,
            target_search_queries=queries,
            seo_improvements=seo,
            top_services=services,
            target_audience=audience,
        )
