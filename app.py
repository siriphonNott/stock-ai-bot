"""FastAPI HTTP layer over core.render_query — consumed by N8N.

Endpoints:
- POST /api/v1/stocks/all  → JSON {count, images:[base64 png...], error, query}  (N8N main contract)
- GET/POST /api/v1/stocks  → image/png of the primary card (+X-Image-Count header)
- GET /healthz             → liveness probe (no upstream calls)

Optional auth: if env API_KEY is set, requests must send a matching X-API-Key
header; if it's unset, the API is open (fine for internal-only docker networks).
"""
from __future__ import annotations

import base64
import logging
import os
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response
from pydantic import BaseModel

from core import NoMatch, QueryError, render_query

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
log = logging.getLogger("stockapi")

app = FastAPI(title="stock-ai-api", version="1.0.0")

_API_KEY = os.environ.get("API_KEY") or ""


def require_api_key(x_api_key: Optional[str] = Header(default=None)) -> None:
    """No-op when API_KEY is unset; otherwise enforce the shared secret."""
    if _API_KEY and x_api_key != _API_KEY:
        raise HTTPException(status_code=401, detail="invalid or missing X-API-Key")


class RenderRequest(BaseModel):
    q: str


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


async def _single(q: str, i: int) -> Response:
    try:
        images = await render_query(q)
    except NoMatch:
        return Response(status_code=204)
    except QueryError as e:
        code = 404 if e.kind == "not_found" else 502
        raise HTTPException(status_code=code, detail=e.thai_message)
    except Exception:
        log.exception("render_query crashed for %r", q[:80])
        raise HTTPException(status_code=500, detail="internal error")

    if not images:
        return Response(status_code=204)
    if i < 0 or i >= len(images):
        raise HTTPException(status_code=404, detail="image index out of range")
    return Response(
        content=images[i],
        media_type="image/png",
        headers={"X-Image-Count": str(len(images)), "X-Image-Index": str(i)},
    )


@app.get("/api/v1/stocks", dependencies=[Depends(require_api_key)])
async def stocks_get(q: str = Query(...), i: int = 0) -> Response:
    return await _single(q, i)


@app.post("/api/v1/stocks", dependencies=[Depends(require_api_key)])
async def stocks_post(body: RenderRequest, i: int = 0) -> Response:
    return await _single(body.q, i)


@app.post("/api/v1/stocks/all", dependencies=[Depends(require_api_key)])
async def stocks_all(body: RenderRequest) -> dict:
    """Uniform contract for N8N — always HTTP 200; errors live in the body.

    count==0 && error!=null → understood but failed (show the Thai message).
    count==0 && error==null → silent case (the bot would not reply).
    """
    try:
        images = await render_query(body.q)
    except NoMatch:
        return {"count": 0, "images": [], "error": None, "query": body.q}
    except QueryError as e:
        return {"count": 0, "images": [], "error": e.thai_message, "query": body.q}
    except Exception:
        log.exception("render_query crashed for %r", body.q[:80])
        return {"count": 0, "images": [], "error": "internal error", "query": body.q}

    return {
        "count": len(images),
        "images": [base64.b64encode(b).decode() for b in images],
        "error": None,
        "query": body.q,
    }
