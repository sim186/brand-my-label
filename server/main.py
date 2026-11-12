"""HTTP API for brand-my-label (deployed on Google Cloud Run).

POST /api/stamp  multipart: label (PDF or Vinted viewer HTML), logo (image),
                 to_a4 (optional, "1"/"0")  ->  stamped PDF

Privacy: labels contain buyer names and addresses. They are processed in
memory and never written to disk or logged. Analytics events carry only
layout/carrier metadata, never label content.
"""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from posthog import Posthog
from starlette.concurrency import run_in_threadpool

from brand_my_label import (StampError, VintedError, fetch_pdf_from_html,
                            is_html, stamp_pdf)
from brand_my_label.vinted import filename_from_html

# ---------------------------------------------------------------- config
DEBUG = os.environ.get("DEBUG", "0") == "1"
POSTHOG_PROJECT_TOKEN = os.environ.get("POSTHOG_PROJECT_TOKEN", "")
POSTHOG_HOST = os.environ.get("POSTHOG_HOST", "https://eu.i.posthog.com")
POSTHOG_DISABLED = os.environ.get("POSTHOG_DISABLED", "0") == "1"
ALLOWED_ORIGINS = [o.strip() for o in os.environ.get(
    "ALLOWED_ORIGINS", "http://localhost:8000").split(",") if o.strip()]
MAX_LABEL_BYTES = int(float(os.environ.get("MAX_LABEL_MB", "10")) * 1024 * 1024)
MAX_LOGO_BYTES = int(float(os.environ.get("MAX_LOGO_MB", "2")) * 1024 * 1024)
RATE_LIMIT = int(os.environ.get("RATE_LIMIT_PER_10MIN", "30"))

logging.basicConfig(level=logging.DEBUG if DEBUG else logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("brand_my_label.server")

# --------------------------------------------------------------- posthog
posthog: Posthog | None = None


def init_posthog() -> None:
    global posthog
    if POSTHOG_DISABLED:
        return
    if not POSTHOG_PROJECT_TOKEN:
        msg = ("POSTHOG_PROJECT_TOKEN variable required by PostHog is missing or "
               "un-configured, this causes events to be silently missed. This error "
               "stops appearing once POSTHOG_PROJECT_TOKEN is configured")
        if DEBUG:
            raise RuntimeError(msg)
        return
    # sync_mode: Cloud Run throttles CPU between requests, so a background
    # sender thread may never flush. Send inline (~50 ms) instead.
    posthog = Posthog(POSTHOG_PROJECT_TOKEN, host=POSTHOG_HOST, debug=DEBUG,
                      sync_mode=True, enable_exception_autocapture=True)


def track(event: str, request: Request, props: dict) -> None:
    if posthog is None:
        return
    distinct_id = (request.headers.get("x-posthog-distinct-id")
                   or f"anon-{uuid.uuid4()}")
    props = {**props, "$process_person_profile": False, "source": "api"}
    session_id = request.headers.get("x-posthog-session-id")
    if session_id:
        props["$session_id"] = session_id
    try:
        posthog.capture(event, distinct_id=distinct_id, properties=props)
    except Exception:  # noqa: BLE001 - analytics must never break a request
        log.warning("posthog capture failed", exc_info=True)


def track_exception(exc: Exception, request: Request) -> None:
    if posthog is None:
        return
    try:
        posthog.capture_exception(
            exc, distinct_id=request.headers.get("x-posthog-distinct-id"),
            properties={"$process_person_profile": False, "path": request.url.path})
    except Exception:  # noqa: BLE001
        log.warning("posthog capture_exception failed", exc_info=True)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_posthog()
    yield
    if posthog is not None:
        posthog.shutdown()


# ------------------------------------------------------------ rate limit
_hits: dict[str, deque] = defaultdict(deque)
_hits_lock = threading.Lock()


def client_ip(request: Request) -> str:
    # Cloud Run puts the real client first in X-Forwarded-For
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() or (request.client.host if request.client else "?")


def rate_limited(ip: str) -> bool:
    now = time.monotonic()
    with _hits_lock:
        q = _hits[ip]
        while q and now - q[0] > 600:
            q.popleft()
        if len(q) >= RATE_LIMIT:
            return True
        q.append(now)
        if len(_hits) > 10_000:  # keep memory bounded
            for k in [k for k, v in _hits.items() if not v][:5000]:
                del _hits[k]
        return False


# ------------------------------------------------------------------- app
app = FastAPI(title="brand-my-label", lifespan=lifespan,
              docs_url="/api/docs" if DEBUG else None, redoc_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["POST", "GET"],
    allow_headers=["x-posthog-distinct-id", "x-posthog-session-id"],
    expose_headers=["x-logo-placed", "x-placement-mode", "x-carrier",
                    "content-disposition"],
    max_age=3600,
)


def error(request: Request, status: int, code: str, message: str, props: dict):
    track("label_stamp_failed", request, {**props, "error_code": code})
    return JSONResponse({"error": code, "message": message}, status_code=status)


async def read_capped(f: UploadFile, cap: int) -> bytes | None:
    data = await f.read(cap + 1)
    return None if len(data) > cap else data


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/api/stamp")
async def stamp(request: Request,
                label: UploadFile = File(...),
                logo: UploadFile = File(...),
                to_a4: str = Form("1")):
    t0 = time.perf_counter()
    props: dict = {"to_a4": to_a4 == "1"}
    if rate_limited(client_ip(request)):
        return error(request, 429, "rate_limited",
                     "too many labels in a short time, try again in a few minutes", props)

    label_bytes = await read_capped(label, MAX_LABEL_BYTES)
    logo_bytes = await read_capped(logo, MAX_LOGO_BYTES)
    if label_bytes is None:
        return error(request, 413, "label_too_large", "label file is too large", props)
    if logo_bytes is None:
        return error(request, 413, "logo_too_large", "logo file is too large", props)
    props["input_kb"] = round(len(label_bytes) / 1024)

    name = os.path.splitext(os.path.basename(label.filename or "label"))[0] or "label"
    try:
        if is_html(label_bytes):
            props["input_type"] = "vinted_html"
            name = os.path.splitext(filename_from_html(label_bytes) or name)[0]
            # blocking network call: run in the threadpool
            label_bytes = await run_in_threadpool(fetch_pdf_from_html, label_bytes)
        else:
            props["input_type"] = "pdf"

        result = await run_in_threadpool(stamp_pdf, label_bytes, logo_bytes,
                                         to_a4=props["to_a4"])
    except (StampError, VintedError) as e:
        return error(request, 422, e.code, str(e), props)
    except Exception as e:  # noqa: BLE001
        log.exception("unexpected stamping failure")
        track_exception(e, request)
        return error(request, 500, "internal", "something went wrong on our side", props)

    track("label_stamped", request, {
        **props,
        "logo_placed": result.placed,
        "placement_mode": result.mode,
        "carrier": result.carrier,
        "normalized_a4": result.normalized_a4,
        "page_count": result.page_count,
        "duration_ms": round((time.perf_counter() - t0) * 1000),
    })
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in name)[:80]
    return Response(
        result.pdf, media_type="application/pdf",
        headers={
            "content-disposition": f'attachment; filename="{safe}-branded.pdf"',
            "x-logo-placed": "1" if result.placed else "0",
            "x-placement-mode": result.mode,
            "x-carrier": result.carrier,
            "cache-control": "no-store",
        })
