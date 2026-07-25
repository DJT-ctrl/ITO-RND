"""Postgres CRUD for agentic scrape proof reports (T10.5.5)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from phase_10.models import ScrapeProof


def insert_proof(
    conn: psycopg.Connection,
    *,
    job_id: str,
    payload: dict[str, Any],
    niche: str | None = None,
) -> ScrapeProof:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO agentic_scrape_proofs (job_id, niche, payload)
            VALUES (%s, %s, %s)
            RETURNING id, created_at
            """,
            (job_id, niche, Jsonb(payload)),
        )
        row = cur.fetchone()
    conn.commit()
    proof_id, created_at = row
    created = None
    if isinstance(created_at, datetime):
        created = created_at.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    summary = str(payload.get("summary") or payload.get("health") or "ok")
    return ScrapeProof(
        id=str(proof_id),
        job_id=job_id,
        niche=niche,
        created_at=created,
        summary=summary,
        payload=payload,
        ok=bool(payload.get("ok", True)),
    )


def list_proofs(
    conn: psycopg.Connection,
    *,
    limit: int = 20,
) -> list[ScrapeProof]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, job_id, niche, created_at, payload
            FROM agentic_scrape_proofs
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()
    out: list[ScrapeProof] = []
    for proof_id, job_id, niche, created_at, payload in rows:
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                payload = {}
        if not isinstance(payload, dict):
            payload = {}
        created = None
        if isinstance(created_at, datetime):
            created = (
                created_at.astimezone(timezone.utc).replace(microsecond=0).isoformat()
            )
        out.append(
            ScrapeProof(
                id=str(proof_id),
                job_id=str(job_id),
                niche=niche,
                created_at=created,
                summary=str(payload.get("summary") or "—"),
                payload=payload,
                ok=bool(payload.get("ok", True)),
            )
        )
    return out
