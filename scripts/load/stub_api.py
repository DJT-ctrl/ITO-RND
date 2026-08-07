#!/usr/bin/env python3
"""Latency stub API for reproducible load tests without Gemini/Postgres (issue #21).

Simulates the shape and typical latency of the real routes so `run_load_test.py`
can be exercised offline. Delays are intentionally close to the lab profile in
`docs/ops/LOAD_BASELINE.md` (not a substitute for staging against the real stack).

  python scripts/load/stub_api.py
  # listens on http://127.0.0.1:8010
"""

from __future__ import annotations

import argparse
import asyncio
import time

from fastapi import FastAPI
from pydantic import BaseModel, Field
import uvicorn

app = FastAPI(title="IntoTheOpen Load Stub", version="0.0.0")


class SimilarPostsRequest(BaseModel):
    content: str
    limit: int = Field(default=10, ge=1, le=50)
    user_id: str | None = None


class EvaluateRequest(BaseModel):
    content: str
    variant_strategy: str | None = "dimension"
    use_google_trends: bool = False


# Tunable delays (seconds) — match LOAD_BASELINE "stub lab" column.
SIMILAR_POSTS_DELAY_S = 0.45
EVALUATE_DELAY_S = 12.0
HEALTH_DELAY_S = 0.001


@app.get("/health")
async def health() -> dict[str, str]:
    await asyncio.sleep(HEALTH_DELAY_S)
    return {"status": "ok", "api_version": "v1", "mode": "load-stub"}


@app.post("/api/v1/similar-posts")
async def similar_posts(request: SimilarPostsRequest) -> dict:
    await asyncio.sleep(SIMILAR_POSTS_DELAY_S)
    return {
        "query_content": request.content,
        "results": [
            {
                "post_id": f"stub-{i}",
                "content": f"Stub neighbor {i}",
                "total_engagement": 100 - i,
                "distance": 0.1 * i,
            }
            for i in range(min(request.limit, 3))
        ],
        "stub_delay_s": SIMILAR_POSTS_DELAY_S,
    }


@app.post("/api/v1/evaluate")
async def evaluate(request: EvaluateRequest) -> dict:
    await asyncio.sleep(EVALUATE_DELAY_S)
    return {
        "draft_content": request.content,
        "predictor_result": {"predicted_percentile": 72, "stub": True},
        "diagnostics": {"hook": {"score": 0.8, "stub": True}},
        "variants": [],
        "variant_strategy": request.variant_strategy,
        "elapsed_wall_s": EVALUATE_DELAY_S,
        "generated_at": time.time(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8010)
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
