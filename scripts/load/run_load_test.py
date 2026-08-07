#!/usr/bin/env python3
"""Reproducible HTTP load runner for IntoTheOpen API routes (issue #21).

Examples:
  python scripts/load/run_load_test.py --scenario smoke
  python scripts/load/run_load_test.py --scenario baseline --base-url http://127.0.0.1:8000
  python scripts/load/run_load_test.py --scenario similar-posts-steady --output /tmp/load.json

Against the latency stub (no Gemini/DB):
  python scripts/load/stub_api.py &
  python scripts/load/run_load_test.py --scenario baseline --base-url http://127.0.0.1:8010
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import yaml

SCRIPTS_DIR = Path(__file__).resolve().parent
DEFAULT_SCENARIOS = SCRIPTS_DIR / "scenarios.yaml"


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (pct / 100.0) * (len(sorted_values) - 1)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return sorted_values[low]
    weight = rank - low
    return sorted_values[low] * (1 - weight) + sorted_values[high] * weight


def _render(value: Any, draft: str) -> Any:
    if isinstance(value, str):
        return value.replace("{{draft_content}}", draft)
    if isinstance(value, dict):
        return {k: _render(v, draft) for k, v in value.items()}
    if isinstance(value, list):
        return [_render(v, draft) for v in value]
    return value


def _load_scenarios(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or "scenarios" not in payload:
        raise ValueError(f"Invalid scenarios file: {path}")
    return payload


def _one_request(
    client: httpx.Client,
    *,
    method: str,
    url: str,
    json_body: dict[str, Any] | None,
    timeout_s: float,
) -> dict[str, Any]:
    started = time.perf_counter()
    status = 0
    error: str | None = None
    try:
        response = client.request(method, url, json=json_body, timeout=timeout_s)
        status = response.status_code
        if status >= 400:
            error = response.text[:300]
    except Exception as exc:  # noqa: BLE001 — surface any transport failure in report
        error = f"{type(exc).__name__}: {exc}"
    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    return {
        "status": status,
        "latency_ms": latency_ms,
        "ok": 200 <= status < 400 and error is None,
        "error": error,
    }


def _run_route_block(
    *,
    base_url: str,
    draft: str,
    block: dict[str, Any],
) -> dict[str, Any]:
    route = block["route"]
    method = str(block.get("method", "GET")).upper()
    path = block["path"]
    count = int(block.get("count", 1))
    concurrency = max(1, int(block.get("concurrency", 1)))
    timeout_s = float(block.get("timeout_s", 30))
    json_body = _render(block.get("json"), draft) if block.get("json") is not None else None
    url = base_url.rstrip("/") + path

    results: list[dict[str, Any]] = []
    wall_started = time.perf_counter()
    with httpx.Client() as client:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = [
                pool.submit(
                    _one_request,
                    client,
                    method=method,
                    url=url,
                    json_body=json_body,
                    timeout_s=timeout_s,
                )
                for _ in range(count)
            ]
            for future in as_completed(futures):
                results.append(future.result())
    wall_s = time.perf_counter() - wall_started

    latencies = sorted(r["latency_ms"] for r in results)
    ok_count = sum(1 for r in results if r["ok"])
    status_counts: dict[str, int] = {}
    for r in results:
        key = str(r["status"] or "transport_error")
        status_counts[key] = status_counts.get(key, 0) + 1

    return {
        "route": route,
        "method": method,
        "path": path,
        "count": count,
        "concurrency": concurrency,
        "wall_seconds": round(wall_s, 3),
        "throughput_rps": round(ok_count / wall_s, 3) if wall_s > 0 else 0.0,
        "ok": ok_count,
        "errors": count - ok_count,
        "error_rate": round((count - ok_count) / count, 4) if count else 0.0,
        "latency_ms": {
            "min": latencies[0] if latencies else 0.0,
            "mean": round(statistics.fmean(latencies), 2) if latencies else 0.0,
            "p50": round(_percentile(latencies, 50), 2),
            "p95": round(_percentile(latencies, 95), 2),
            "p99": round(_percentile(latencies, 99), 2),
            "max": latencies[-1] if latencies else 0.0,
        },
        "status_counts": status_counts,
        "sample_errors": [r["error"] for r in results if r["error"]][:5],
    }


def run_scenario(
    *,
    scenarios_path: Path,
    scenario_name: str,
    base_url: str | None,
) -> dict[str, Any]:
    payload = _load_scenarios(scenarios_path)
    defaults = payload.get("defaults") or {}
    scenarios = payload["scenarios"]
    if scenario_name not in scenarios:
        known = ", ".join(sorted(scenarios))
        raise SystemExit(f"Unknown scenario {scenario_name!r}. Known: {known}")

    scenario = scenarios[scenario_name]
    resolved_base = (base_url or defaults.get("base_url") or "http://127.0.0.1:8000").rstrip(
        "/"
    )
    draft = str(defaults.get("draft_content") or "Load-test draft post.")

    route_reports = [
        _run_route_block(base_url=resolved_base, draft=draft, block=block)
        for block in scenario.get("requests") or []
    ]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scenario": scenario_name,
        "description": scenario.get("description"),
        "base_url": resolved_base,
        "routes": route_reports,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario",
        default="smoke",
        help="Scenario name from scenarios.yaml (default: smoke)",
    )
    parser.add_argument(
        "--scenarios-file",
        type=Path,
        default=DEFAULT_SCENARIOS,
        help="Path to scenarios YAML",
    )
    parser.add_argument("--base-url", default=None, help="Override API base URL")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write JSON report to this path (also prints summary)",
    )
    args = parser.parse_args(argv)

    report = run_scenario(
        scenarios_path=args.scenarios_file,
        scenario_name=args.scenario,
        base_url=args.base_url,
    )

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(report, indent=2))
    failed = any(route["errors"] > 0 for route in report["routes"])
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
