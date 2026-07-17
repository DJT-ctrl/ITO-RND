#!/usr/bin/env python3
"""Publish ITO/API CloudWatch metrics from the local Prometheus /metrics scrape.

Issue #16 — bridges FastAPI instrumentator metrics into namespace ITO/API so
CloudWatch alarms (ErrorRate, LatencyP95Seconds) have a signal without ALB.

Usage:
  python scripts/publish_cw_api_metrics.py --environment dev --once
  python scripts/publish_cw_api_metrics.py --environment dev --loop --interval 60
"""

from __future__ import annotations

import argparse
import math
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict


def _parse_prometheus(text: str) -> dict[str, list[tuple[dict[str, str], float]]]:
    series: dict[str, list[tuple[dict[str, str], float]]] = defaultdict(list)
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "{" in line and "}" in line:
            name, rest = line.split("{", 1)
            labels_s, value_s = rest.rsplit("}", 1)
            labels: dict[str, str] = {}
            for part in labels_s.split(","):
                part = part.strip()
                if not part or "=" not in part:
                    continue
                k, v = part.split("=", 1)
                labels[k.strip()] = v.strip().strip('"')
            series[name.strip()].append((labels, float(value_s.strip())))
        else:
            name, value_s = line.split(None, 1)
            series[name.strip()].append(({}, float(value_s.strip())))
    return series


def _error_rate(series: dict[str, list[tuple[dict[str, str], float]]]) -> float:
    total = 0.0
    errors = 0.0
    for labels, value in series.get("http_requests_total", []):
        total += value
        status = labels.get("status", "")
        if status.startswith("5"):
            errors += value
    if total <= 0:
        return 0.0
    return 100.0 * (errors / total)


def _histogram_p95(series: dict[str, list[tuple[dict[str, str], float]]]) -> float:
    """Approximate global p95 from http_request_duration_seconds_bucket."""
    by_le: dict[float, float] = defaultdict(float)
    for labels, value in series.get("http_request_duration_seconds_bucket", []):
        le = labels.get("le")
        if le is None or le == "+Inf":
            continue
        by_le[float(le)] += value
    if not by_le:
        return 0.0
    total = max(by_le.values()) if by_le else 0.0
    # cumulative histogram: use max bucket count as total observations
    # Prefer +Inf if present
    for labels, value in series.get("http_request_duration_seconds_bucket", []):
        if labels.get("le") == "+Inf":
            total = value
            break
    if total <= 0:
        return 0.0
    target = 0.95 * total
    for le in sorted(by_le):
        # Recompute cumulative properly
        pass
    cumulative = 0.0
    for le in sorted(by_le):
        # Buckets in Prometheus are already cumulative per label set; we summed
        # across handlers so treat sorted le thresholds as cumulative approx.
        cumulative = by_le[le]
        if cumulative >= target:
            return le
    return max(by_le) if by_le else 0.0


def _fetch_metrics(url: str) -> str:
    with urllib.request.urlopen(url, timeout=10) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _put_metrics(environment: str, error_rate: float, latency_p95: float, region: str) -> None:
    try:
        import boto3
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "boto3 is required for --live publish. pip install boto3"
        ) from exc

    client = boto3.client("cloudwatch", region_name=region)
    client.put_metric_data(
        Namespace="ITO/API",
        MetricData=[
            {
                "MetricName": "ErrorRate",
                "Dimensions": [{"Name": "Environment", "Value": environment}],
                "Unit": "Percent",
                "Value": float(error_rate),
            },
            {
                "MetricName": "LatencyP95Seconds",
                "Dimensions": [{"Name": "Environment", "Value": environment}],
                "Unit": "Seconds",
                "Value": float(latency_p95),
            },
        ],
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metrics-url", default="http://127.0.0.1:8000/metrics")
    parser.add_argument("--environment", default="dev")
    parser.add_argument("--region", default="eu-west-2")
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print computed metrics without calling CloudWatch.",
    )
    args = parser.parse_args(argv)

    if not args.once and not args.loop:
        args.once = True

    while True:
        try:
            text = _fetch_metrics(args.metrics_url)
            series = _parse_prometheus(text)
            error_rate = _error_rate(series)
            latency_p95 = _histogram_p95(series)
            if math.isnan(error_rate) or math.isnan(latency_p95):
                raise ValueError("NaN metric")
            print(
                f"ITO/API env={args.environment} "
                f"ErrorRate={error_rate:.3f}% LatencyP95Seconds={latency_p95:.3f}"
            )
            if not args.dry_run:
                _put_metrics(args.environment, error_rate, latency_p95, args.region)
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            print(f"publish skipped: {exc}", file=sys.stderr)

        if args.once:
            return 0
        time.sleep(max(args.interval, 15))


if __name__ == "__main__":
    raise SystemExit(main())
