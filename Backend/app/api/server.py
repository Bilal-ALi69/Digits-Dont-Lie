"""FastAPI application for the fraud analysis backend."""

from __future__ import annotations

import json
import logging
import os
import secrets
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.api.rate_limit import SlidingWindowLimiter, client_key
from app.models import AnalysisResponse, ClassificationResponse
from app.orchestrator import (
    analyze_dataset,
    analyze_document_text,
    analyze_file,
    analyze_single_value,
    classify_input,
)

# Development conveniences are opt-in, not the default.
#
# This used to default to "development", which meant the only thing standing
# between a deployment and a fully unauthenticated API with /docs open was
# remembering to set a variable. Forgetting is silent and looks exactly like
# working. Now an unset or unrecognised value gets the hardened posture, and a
# developer who wants the conveniences asks for them by name.
_DEV_ENVIRONMENTS = {"dev", "development", "local", "test"}

_environment = os.environ.get("ENVIRONMENT", "").strip().lower()
_is_production = _environment not in _DEV_ENVIRONMENTS

_logger = logging.getLogger("app.api.server")
if not _is_production:
    # require_api_key() below skips all auth checks whenever this is false.
    # Reaching here now takes an explicit ENVIRONMENT=development, so it cannot
    # happen by omission — but it is still worth saying out loud, because the
    # server looks identical either way.
    _logger.warning(
        "ENVIRONMENT=%r — API key authentication is DISABLED and /docs, /redoc "
        "are exposed. Unset ENVIRONMENT (or set it to 'production') before "
        "deploying anywhere reachable outside localhost.",
        _environment,
    )


@asynccontextmanager
async def lifespan(app_instance):
    """Validate required config at startup; yield to let the app run."""
    _get_api_key()
    yield


app = FastAPI(
    title="Fraud Analysis & Verification API",
    version="1.0.0",
    description="Multi-modal fraud analysis and verification backend.",
    docs_url=None if _is_production else "/docs",
    redoc_url=None if _is_production else "/redoc",
    # Disabling the two doc UIs is not enough on its own: FastAPI serves the
    # schema they render from at /openapi.json regardless, so every route,
    # parameter and model stayed published to anyone who asked for it directly.
    openapi_url=None if _is_production else "/openapi.json",
    lifespan=lifespan,
)

_allowed_origins = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]

# Guard: wildcard origin + credentials is a security misconfiguration (Starlette
# echoes the caller's Origin header, allowing any site to make credentialed
# requests).  Reject it loudly at import time rather than silently allowing it.
_cors_credentials = bool(_allowed_origins)
if "*" in _allowed_origins:
    raise RuntimeError(
        "ALLOWED_ORIGINS must not contain '*' when credentials are supported. "
        "List explicit origins instead, e.g. ALLOWED_ORIGINS=https://yourapp.com"
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=_cors_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request timeout (outermost middleware — added last so it wraps everything)
# ---------------------------------------------------------------------------

# Two budgets, because the endpoints cost wildly different amounts. Classifying a
# string is microseconds; an upload is several seconds of Tesseract across
# multiple preprocessing passes, so it gets its own, much smaller allowance.
_general_limiter = SlidingWindowLimiter(
    limit=int(os.environ.get("RATE_LIMIT_PER_MINUTE", "60")),
    window_seconds=60.0,
)
_upload_limiter = SlidingWindowLimiter(
    limit=int(os.environ.get("RATE_LIMIT_UPLOADS_PER_MINUTE", "12")),
    window_seconds=60.0,
)

# Health is exempt: the frontend polls it to choose between the real backend and
# its offline fallback, so rate-limiting it would make a busy server look down
# and silently downgrade every client to the weaker client-side analysis.
_RATE_LIMIT_EXEMPT_PATHS = {"/api/health"}
_UPLOAD_PATHS = {"/api/analyze/upload", "/api/classify/image"}


@app.middleware("http")
async def rate_limit_requests(request: Request, call_next):
    """Bound how much work one caller can demand.

    Authentication says who may ask; it says nothing about how often. A single
    valid key can otherwise drive unlimited OCR, which is the most expensive
    thing this service does.
    """
    path = request.url.path
    if request.method == "OPTIONS" or path in _RATE_LIMIT_EXEMPT_PATHS:
        return await call_next(request)

    limiter = _upload_limiter if path in _UPLOAD_PATHS else _general_limiter
    retry_after = limiter.check(client_key(request))
    if retry_after is not None:
        seconds = max(1, int(retry_after) + 1)
        return JSONResponse(
            status_code=429,
            content={"detail": f"Too many requests. Try again in {seconds}s."},
            headers={"Retry-After": str(seconds)},
        )

    return await call_next(request)


_REQUEST_TIMEOUT_SECONDS = int(os.environ.get("REQUEST_TIMEOUT", "120"))


@app.middleware("http")
async def _request_timeout_middleware(request: Request, call_next):
    """Abort requests that exceed REQUEST_TIMEOUT seconds (default 120)."""
    start = time.monotonic()
    response = await call_next(request)
    elapsed = time.monotonic() - start
    if elapsed > _REQUEST_TIMEOUT_SECONDS:
        # The response already completed, but log and return a warning header.
        # True hard-kill requires ASGI-level task cancellation which is
        # framework-specific; the header signals the client that it was slow.
        response.headers["X-Request-Timeout"] = "exceeded"
    return response


_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
_MAX_DATASET_VALUES = 100_000
_MAX_TEXT_CHARS = 500_000


# ---------------------------------------------------------------------------
# API-key authentication
# ---------------------------------------------------------------------------

def _get_api_key() -> str:
    """Return the configured API key, raising if unset."""
    key = os.environ.get("API_KEY")
    if not key:
        raise RuntimeError(
            "API_KEY environment variable is not set. "
            "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(32))\" "
            "and set API_KEY=<value> in your .env file."
        )
    return key


async def require_api_key(request: Request) -> None:
    """FastAPI dependency enforcing the shared API key via the X-API-Key header.

    Header only, deliberately. A credential in a query string is written to web
    server and proxy access logs, kept in browser history, and sent onward in the
    Referer header of any request the page makes to a third party — so accepting
    one there quietly hands the key to all of them. Compared with
    compare_digest so a wrong key takes the same time to reject as a right one.

    Skipped in development mode for easier testing.
    """
    if not _is_production:
        return
    expected = _get_api_key()
    provided = request.headers.get("X-API-Key", "")
    if not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid API key. Provide a valid X-API-Key header.",
        )


class ManualInputRequest(BaseModel):
    input_type: str = Field(
        default="auto",
        description="manual_number, manual_dataset, manual_text, structured_json, or auto",
    )
    value: str | None = Field(default=None, max_length=1000, description="Single value to analyze")
    values: list[float] | None = Field(
        default=None, max_length=_MAX_DATASET_VALUES, description="List of numbers to analyze"
    )
    text: str | None = Field(
        default=None, max_length=_MAX_TEXT_CHARS, description="Text content to analyze"
    )
    data: dict[str, object] | None = Field(default=None, description="Structured data to analyze")
    confirmed_type: str | None = Field(
        default=None,
        description="User-confirmed classification type (legacy, backward compat)",
    )
    confirmed_document_type: str | None = Field(
        default=None,
        description="User-confirmed document type (e.g., credit_card, invoice)",
    )
    confirmed_value_type: str | None = Field(
        default=None,
        description="User-confirmed value type (e.g., card_number, invoice_number)",
    )
    classification_id: str | None = Field(
        default=None,
        description="Optional token from /api/classify to validate the confirmed type against.",
    )


class ClassifyRequest(BaseModel):
    value: str = Field(..., description="Value to classify")
    context: str | None = Field(
        default=None,
        description="Optional surrounding context (e.g., 'Invoice #123456')",
    )


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "1.0.0"
    engines: list[str] = Field(default_factory=lambda: [
        "card_validation",
        "input_classification",
        "benford_analysis",
        "financial_arithmetic",
        "cv_resume",
        "ocr",
    ])


@app.get("/api/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    return HealthResponse()


@app.post("/api/classify", response_model=ClassificationResponse)
async def classify_endpoint(
    request: ClassifyRequest,
    _auth: None = Depends(require_api_key),
) -> ClassificationResponse:
    # classify_input is synchronous and may call out to Groq (network I/O).
    # Running it directly here would block the event loop for every other
    # concurrent request; run_in_threadpool hands it off to a worker thread.
    return await run_in_threadpool(classify_input, request.value, context=request.context)


def _parse_vision_guess(raw: str | None):
    """Rebuild a vision verdict the client obtained from /api/classify/image.

    The client is not trusted here: this arrives over the wire and could name any
    type at any confidence, so both fields are checked against the same
    controlled vocabularies the server-side classifier uses, and confidence is
    clamped. Anything malformed returns None, which makes the analysis fall back
    to classifying the image itself rather than honouring bad input.
    """
    if not raw:
        return None

    from app.engines.classifier import (
        _VALID_DOCUMENT_TYPES,
        _VALID_VALUE_TYPES,
        VisionClassification,
    )

    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(parsed, dict):
        return None

    document_type = str(parsed.get("document_type", "")).strip().lower()
    value_type = str(parsed.get("value_type", "")).strip().lower()
    if document_type not in _VALID_DOCUMENT_TYPES or value_type not in _VALID_VALUE_TYPES:
        return None

    try:
        confidence = float(parsed.get("confidence", 0.0))
    except (TypeError, ValueError):
        return None
    confidence = max(0.0, min(0.95, confidence))

    reason = str(parsed.get("reason", "")).strip()[:120] or "Identified from document image"
    return VisionClassification(document_type, value_type, confidence, reason)


@app.post("/api/classify/image")
async def classify_image_endpoint(
    file: UploadFile = File(...),
    _auth: None = Depends(require_api_key),
) -> dict[str, object | None]:
    """Identify an uploaded document's type from the image, without analysing it.

    Mirrors /api/classify for text: the client calls this first so it can show
    what the document appears to be while the slower full analysis runs. Returns
    {"guess": null} when vision is unconfigured or unsure — the caller then shows
    generic progress rather than inventing a guess.
    """
    suffix = Path(file.filename or "upload.bin").suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp"}:
        return {"guess": None}

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        try:
            total = 0
            while True:
                chunk = await file.read(_UPLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                total += len(chunk)
                if total > _MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="File too large (max 10 MB).")
                tmp.write(chunk)
        finally:
            tmp.close()

        from app.engines.classifier import classify_image_document

        vision = await run_in_threadpool(classify_image_document, tmp.name)
        if vision is None:
            return {"guess": None}
        return {
            "guess": {
                "document_type": vision.document_type,
                "value_type": vision.value_type,
                "confidence": round(vision.confidence, 4),
                "reason": vision.reason,
            }
        }
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


@app.post("/api/analyze", response_model=AnalysisResponse)
async def analyze_endpoint(
    request: ManualInputRequest,
    _auth: None = Depends(require_api_key),
) -> AnalysisResponse:
    # Validate classification_id against confirmed types when both are provided
    if request.classification_id:
        from app.classification_store import validate_classification

        # Every confirmed type provided is checked, not merely the first one
        # found. The previous `a or b or c` validated whichever field happened
        # to be set first and then passed all three through untouched, so a
        # caller supplying a legitimate value type could smuggle an arbitrary
        # document type past the token alongside it.
        for confirmed in (
            request.confirmed_value_type,
            request.confirmed_type,
            request.confirmed_document_type,
        ):
            if not confirmed:
                continue
            error = validate_classification(request.classification_id, confirmed)
            if error:
                raise HTTPException(status_code=400, detail=error)

    if request.input_type == "manual_number" and request.value is not None:
        return await run_in_threadpool(
            analyze_single_value,
            request.value,
            confirmed_type=request.confirmed_type,
            confirmed_document_type=request.confirmed_document_type,
            confirmed_value_type=request.confirmed_value_type,
        )

    if request.input_type == "manual_dataset" and request.values is not None:
        if len(request.values) == 0:
            raise HTTPException(status_code=400, detail="Values list is empty.")
        return await run_in_threadpool(analyze_dataset, request.values)

    if request.input_type == "manual_text" and request.text is not None:
        return await run_in_threadpool(analyze_document_text, request.text, source_type="manual_text")

    if request.input_type == "auto":
        if request.value is not None:
            return await run_in_threadpool(
                analyze_single_value,
                request.value,
                confirmed_type=request.confirmed_type,
                confirmed_document_type=request.confirmed_document_type,
                confirmed_value_type=request.confirmed_value_type,
            )
        if request.values is not None and len(request.values) >= 1:
            return await run_in_threadpool(analyze_dataset, request.values)
        if request.text is not None:
            return await run_in_threadpool(analyze_document_text, request.text, source_type="manual_text")
        raise HTTPException(
            status_code=400,
            detail="input_type=auto requires at least one of: value, values, text.",
        )

    raise HTTPException(
        status_code=400,
        detail=f"Invalid input_type: {request.input_type}. Use auto, manual_number, manual_dataset, or manual_text.",
    )


_UPLOAD_CHUNK_BYTES = 1024 * 1024  # 1 MB


@app.post("/api/analyze/upload", response_model=AnalysisResponse)
async def analyze_upload(
    file: UploadFile = File(...),
    input_type: str = "auto",
    vision_guess: str | None = Form(default=None),
    _auth: None = Depends(require_api_key),
) -> AnalysisResponse:
    suffix = Path(file.filename or "upload.bin").suffix.lower()
    allowed = {".csv", ".xlsx", ".xls", ".pdf", ".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp"}
    if suffix not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {suffix}. Allowed: {', '.join(sorted(allowed))}",
        )

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        try:
            # Read in bounded chunks rather than trusting file.size (which can be
            # None — e.g. chunked/streamed uploads with no Content-Length header —
            # letting an unbounded body through and buffering it all into memory).
            total = 0
            while True:
                chunk = await file.read(_UPLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                total += len(chunk)
                if total > _MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="File too large (max 10 MB).")
                tmp.write(chunk)
        finally:
            tmp.close()
        # analyze_file is synchronous and can involve OCR/PDF rasterization/Groq —
        # all CPU- or I/O-blocking. Offload so it doesn't stall the event loop.
        return await run_in_threadpool(
            analyze_file,
            tmp.name,
            declared_type=input_type,
            prior_vision=_parse_vision_guess(vision_guess),
        )
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
