"""Pydantic / dataclasses for A2 trend radar."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional
from uuid import UUID

import numpy as np


@dataclass
class CorpusPostVector:
    post_id: str
    embedding: np.ndarray
    total_engagement: int
    topic: Optional[str] = None
    content: str = ""


@dataclass
class ClusterSnapshot:
    cluster_id: str
    label: str
    post_count: int
    share_of_corpus: float
    growth_rate: Optional[float]
    mean_total_engagement: float
    example_post_ids: list[str]
    centroid: np.ndarray
    example_snippets: list[str] = field(default_factory=list)
    topic_hints: list[str] = field(default_factory=list)


@dataclass
class TrendRow:
    week_start: date
    cluster_id: str
    label: str
    post_count: int
    share_of_corpus: float
    growth_rate: Optional[float]
    mean_total_engagement: float
    example_post_ids: list[str]
    centroid: list[float]
    source: str = "corpus"
    trend_id: Optional[UUID] = None
    computed_at: Optional[datetime] = None
