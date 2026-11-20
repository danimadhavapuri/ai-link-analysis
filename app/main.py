from contextlib import asynccontextmanager
import logging
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.schemas import ErrorResponse, LinkAnalysisRequest, LinkAnalysisResponse
from app.services.analysis_service import AnalysisService
from app.services.llm_service import LLMServiceError
from app.services.website_extractor import (
    WebsiteAccessBlockedError,
    WebsiteConnectionError,
    WebsiteExtractionError,
    WebsiteNotFoundError,
    WebsiteServerError,
    WebsiteTimeoutError,
)
from app.utils.validators import SSRFValidationError, URLValidationError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("ai_link_analysis")

settings = get_settings()
analysis_service = AnalysisService()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle events for startup and shutdown."""
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION} on {settings.HOST}:{settings.PORT}")
    yield
    logger.info(f"Shutting down {settings.APP_NAME}")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "Production-ready AI-powered website analysis API. Extracts live website content, "
        "enforces robust SSRF protection, and utilizes LLM intelligence to return structured "
        "market intelligence across 5 dimensions: Competitor Analysis, Target Search Queries, "
        "SEO Improvements, Top Services, and Target Audience Identification."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# Enable CORS for web and client integrations
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -----------------------------------------------------------------------------
# Custom Exception Handlers (Standardized Structured Error Responses)
# -----------------------------------------------------------------------------

@app.exception_handler(SSRFValidationError)
async def ssrf_validation_exception_handler(request: Request, exc: SSRFValidationError):
    """Handle SSRF blocked requests with 400 Bad Request."""
    logger.warning(f"SSRF violation blocked on {request.url}: {exc}")
    error_resp = ErrorResponse(
        success=False,
        error="SSRF Protection Violation",
        detail=str(exc),
        status_code=status.HTTP_400_BAD_REQUEST,
    )
    return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content=error_resp.model_dump())


@app.exception_handler(URLValidationError)
async def url_validation_exception_handler(request: Request, exc: URLValidationError):
    """Handle malformed or invalid URLs with 400 Bad Request."""
    logger.warning(f"URL validation failed on {request.url}: {exc}")
    error_resp = ErrorResponse(
        success=False,
        error="URL Validation Failed",
        detail=str(exc),
        status_code=status.HTTP_400_BAD_REQUEST,
    )
    return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content=error_resp.model_dump())


@app.exception_handler(WebsiteNotFoundError)
async def website_not_found_handler(request: Request, exc: WebsiteNotFoundError):
    """Handle 404 from target website."""
    error_resp = ErrorResponse(
        success=False,
        error="Target Website Not Found",
        detail=exc.message,
        status_code=status.HTTP_404_NOT_FOUND,
    )
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content=error_resp.model_dump())


@app.exception_handler(WebsiteTimeoutError)
async def website_timeout_handler(request: Request, exc: WebsiteTimeoutError):
    """Handle target website timeout with 504 Gateway Timeout."""
    error_resp = ErrorResponse(
        success=False,
        error="Target Website Timeout",
        detail=exc.message,
        status_code=status.HTTP_504_GATEWAY_TIMEOUT,
    )
    return JSONResponse(status_code=status.HTTP_504_GATEWAY_TIMEOUT, content=error_resp.model_dump())


@app.exception_handler(WebsiteAccessBlockedError)
async def website_access_blocked_handler(request: Request, exc: WebsiteAccessBlockedError):
    """Handle 401/403 blocked by target site with 422 Unprocessable Entity."""
    error_resp = ErrorResponse(
        success=False,
        error="Target Website Inaccessible",
        detail=exc.message,
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    )
    return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content=error_resp.model_dump())


@app.exception_handler(WebsiteConnectionError)
async def website_connection_error_handler(request: Request, exc: WebsiteConnectionError):
    """Handle connection failure with 502 Bad Gateway."""
    error_resp = ErrorResponse(
        success=False,
        error="Target Website Connection Failed",
        detail=exc.message,
        status_code=status.HTTP_502_BAD_GATEWAY,
    )
    return JSONResponse(status_code=status.HTTP_502_BAD_GATEWAY, content=error_resp.model_dump())


@app.exception_handler(WebsiteExtractionError)
async def website_extraction_error_handler(request: Request, exc: WebsiteExtractionError):
    """Handle general extraction errors."""
    error_resp = ErrorResponse(
        success=False,
        error="Website Extraction Error",
        detail=exc.message,
        status_code=exc.status_code,
    )
    return JSONResponse(status_code=exc.status_code, content=error_resp.model_dump())


@app.exception_handler(LLMServiceError)
async def llm_service_error_handler(request: Request, exc: LLMServiceError):
    """Handle LLM API failure with 502 Bad Gateway."""
    logger.error(f"LLM generation failed: {exc.message}")
    error_resp = ErrorResponse(
        success=False,
        error="LLM Intelligence Generation Failed",
        detail=exc.message,
        status_code=status.HTTP_502_BAD_GATEWAY,
    )
    return JSONResponse(status_code=status.HTTP_502_BAD_GATEWAY, content=error_resp.model_dump())


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle Pydantic request validation errors."""
    errors = exc.errors()
    error_msg = "; ".join([f"{err.get('loc')}: {err.get('msg')}" for err in errors])
    error_resp = ErrorResponse(
        success=False,
        error="Invalid Request Body",
        detail=error_msg,
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    )
    return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content=error_resp.model_dump())


@app.exception_handler(HTTPException)
async def generic_http_exception_handler(request: Request, exc: HTTPException):
    """Handle explicit HTTPExceptions."""
    error_resp = ErrorResponse(
        success=False,
        error="HTTP Error",
        detail=str(exc.detail),
        status_code=exc.status_code,
    )
    return JSONResponse(status_code=exc.status_code, content=error_resp.model_dump())


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Catch-all for unanticipated internal server errors."""
    logger.exception(f"Unhandled server error: {exc}")
    error_resp = ErrorResponse(
        success=False,
        error="Internal Server Error",
        detail="An unexpected error occurred while processing the request.",
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
    return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=error_resp.model_dump())


# -----------------------------------------------------------------------------
# Endpoints
# -----------------------------------------------------------------------------

@app.get(
    "/health",
    summary="Health Check",
    tags=["Health"],
    response_description="System status",
)
async def health_check():
    """Returns application health and operational status."""
    return {
        "status": "healthy",
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "cache_enabled": settings.CACHE_ENABLED,
        "model": settings.GEMINI_MODEL,
    }


@app.get(
    "/",
    summary="Root API Info",
    tags=["Root"],
)
async def root():
    """Root info endpoint providing service details and link to documentation."""
    return {
        "message": f"Welcome to {settings.APP_NAME}",
        "documentation": "/docs",
        "endpoint": "POST /link-analysis",
        "version": settings.APP_VERSION,
    }


@app.post(
    "/link-analysis",
    response_model=LinkAnalysisResponse,
    status_code=status.HTTP_200_OK,
    summary="Perform Comprehensive AI-Powered Website Link Analysis",
    tags=["Analysis"],
    responses={
        200: {"description": "Structured 5-section link analysis successfully generated."},
        400: {"model": ErrorResponse, "description": "Invalid URL or SSRF protection violation."},
        404: {"model": ErrorResponse, "description": "Target website was not found."},
        422: {"model": ErrorResponse, "description": "Website access blocked or invalid payload."},
        502: {"model": ErrorResponse, "description": "Target connection failed or LLM error."},
        504: {"model": ErrorResponse, "description": "Target website request timed out."},
    },
)
async def analyze_link(payload: LinkAnalysisRequest):
    """
    Extracts live content from the provided website URL and generates a grounded 5-section analysis:
    - **1. Competitor vs Brand Details**: Brand overview, category, products, competitors, advantages.
    - **2. Top 5 Target Search Queries**: Exactly 5 queries across Google, Facebook, Instagram, LinkedIn, and X.
    - **3. SEO Improvements**: Keywords, title with rationale, meta description, supporting content ideas.
    - **4. Top 5 Services**: Service name, description, industry, customer, main benefit, inference flag.
    - **5. Target Audience**: Primary/secondary audience, segmentations, pain points, profiles.
    """
    response = await analysis_service.analyze_link(payload.url)
    return response
