import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database import engine  # noqa: E402
import main as app_main  # noqa: E402
from verify_transaction_safety import _cleanup_fixture, _create_user_fixture, _patched_generation  # noqa: E402


LONG_IDLE_THRESHOLD_SECONDS = 1.0


def _idle_samples(long_only: bool = False) -> list[dict[str, Any]]:
    long_clause = "AND now() - xact_start >= (:threshold * interval '1 second')" if long_only else ""
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT pid, state, wait_event_type, wait_event, query, now() - xact_start AS xact_age
                FROM pg_stat_activity
                WHERE datname = current_database()
                  AND state = 'idle in transaction'
                  {long_clause}
                ORDER BY xact_start NULLS LAST
                LIMIT 10
                """
            ),
            {"threshold": LONG_IDLE_THRESHOLD_SECONDS},
        ).mappings().all()
    return [
        {
            "pid": int(row["pid"]),
            "state": row["state"],
            "wait_event_type": row["wait_event_type"],
            "wait_event": row["wait_event"],
            "query": str(row["query"] or "")[:240],
            "xact_age": str(row["xact_age"]),
        }
        for row in rows
    ]


def _db_snapshot() -> dict[str, int]:
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        row = conn.execute(
            text(
                """
                SELECT
                  COUNT(*) FILTER (WHERE state = 'idle in transaction') AS idle_in_tx,
                  COUNT(*) FILTER (
                    WHERE state = 'idle in transaction'
                      AND now() - xact_start >= (:threshold * interval '1 second')
                  ) AS long_idle_in_tx,
                  COUNT(*) FILTER (WHERE state = 'active') AS active_count,
                  COUNT(*) AS total_count
                FROM pg_stat_activity
                WHERE datname = current_database()
                """
            ),
            {"threshold": LONG_IDLE_THRESHOLD_SECONDS},
        ).mappings().one()
    return {
        "idle_in_tx": int(row["idle_in_tx"] or 0),
        "long_idle_in_tx": int(row["long_idle_in_tx"] or 0),
        "active_count": int(row["active_count"] or 0),
        "total_count": int(row["total_count"] or 0),
    }


async def _monitor_db(stop_event: asyncio.Event, interval: float = 0.1) -> dict[str, int]:
    baseline = _db_snapshot()
    peaks = dict(baseline)
    peak_idle_samples: list[dict[str, Any]] = []
    peak_long_idle_samples: list[dict[str, Any]] = []
    while not stop_event.is_set():
        await asyncio.sleep(interval)
        current = _db_snapshot()
        for key in peaks:
            peaks[key] = max(peaks[key], current[key])
        if current["idle_in_tx"] >= peaks["idle_in_tx"] and current["idle_in_tx"] > 0:
            peak_idle_samples = _idle_samples()
        if current["long_idle_in_tx"] >= peaks["long_idle_in_tx"] and current["long_idle_in_tx"] > 0:
            peak_long_idle_samples = _idle_samples(long_only=True)
    return {
        "baseline_idle_in_tx": baseline["idle_in_tx"],
        "baseline_long_idle_in_tx": baseline["long_idle_in_tx"],
        "baseline_active_count": baseline["active_count"],
        "baseline_total_count": baseline["total_count"],
        "peak_idle_in_tx": peaks["idle_in_tx"],
        "peak_long_idle_in_tx": peaks["long_idle_in_tx"],
        "peak_active_count": peaks["active_count"],
        "peak_total_count": peaks["total_count"],
        "delta_idle_in_tx": peaks["idle_in_tx"] - baseline["idle_in_tx"],
        "delta_long_idle_in_tx": peaks["long_idle_in_tx"] - baseline["long_idle_in_tx"],
        "delta_active_count": peaks["active_count"] - baseline["active_count"],
        "delta_total_count": peaks["total_count"] - baseline["total_count"],
        "peak_idle_samples": peak_idle_samples,
        "peak_long_idle_samples": peak_long_idle_samples,
    }


async def _call_generate_novel(client: httpx.AsyncClient, fixture: dict[str, Any]) -> httpx.Response:
    return await client.post(
        f"/api/chapters/{fixture['chapter_id']}/generate-novel",
        headers={"Authorization": f"Bearer {fixture['token']}"},
    )


async def _call_framework_generate(client: httpx.AsyncClient, fixture: dict[str, Any], worker_index: int) -> httpx.Response:
    return await client.post(
        f"/api/stories/{fixture['story_id']}/framework/generate",
        headers={"Authorization": f"Bearer {fixture['token']}"},
        json={"description": f"并发压测框架生成 {worker_index}"},
    )


async def _call_generate_manga_stream(client: httpx.AsyncClient, fixture: dict[str, Any]) -> httpx.Response:
    app_main._write_scenes_file(
        fixture["chapter_id"],
        ["镜头一", "镜头二", "镜头三", "镜头四", "镜头五", "镜头六"],
        [],
    )
    return await client.post(
        f"/api/chapters/{fixture['chapter_id']}/generate-manga-stream",
        headers={"Authorization": f"Bearer {fixture['token']}"},
    )


async def _worker(
    client: httpx.AsyncClient,
    fixture: dict[str, Any],
    endpoint: str,
    worker_index: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    if endpoint == "generate_novel":
        response = await _call_generate_novel(client, fixture)
    elif endpoint == "framework_generate":
        response = await _call_framework_generate(client, fixture, worker_index)
    elif endpoint == "generate_manga_stream":
        response = await _call_generate_manga_stream(client, fixture)
    else:
        raise ValueError(f"Unsupported endpoint: {endpoint}")
    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    return {
        "endpoint": endpoint,
        "worker_index": worker_index,
        "status_code": response.status_code,
        "duration_ms": duration_ms,
        "body_preview": response.text[:160],
    }


def _summarize_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    by_endpoint: dict[str, list[dict[str, Any]]] = {}
    for item in results:
        by_endpoint.setdefault(item["endpoint"], []).append(item)

    summary: dict[str, Any] = {}
    for endpoint, items in by_endpoint.items():
        durations = [entry["duration_ms"] for entry in items]
        statuses = [entry["status_code"] for entry in items]
        summary[endpoint] = {
            "count": len(items),
            "status_codes": statuses,
            "ok_count": sum(1 for code in statuses if code == 200),
            "p50_ms": round(statistics.median(durations), 2) if durations else 0,
            "p95_ms": round(sorted(durations)[max(0, int(len(durations) * 0.95) - 1)], 2) if durations else 0,
            "max_ms": round(max(durations), 2) if durations else 0,
        }
    return summary


async def main() -> None:
    parser = argparse.ArgumentParser(description="Concurrent transaction safety load test")
    parser.add_argument("--novel-workers", type=int, default=4)
    parser.add_argument("--framework-workers", type=int, default=4)
    parser.add_argument("--manga-workers", type=int, default=2)
    args = parser.parse_args()

    fixtures: list[dict[str, Any]] = []
    total_workers = args.novel_workers + args.framework_workers + args.manga_workers
    for _ in range(total_workers):
        fixtures.append(_create_user_fixture())

    stop_event = asyncio.Event()
    monitor_task = asyncio.create_task(_monitor_db(stop_event))
    transport = httpx.ASGITransport(app=app_main.app)
    results: list[dict[str, Any]] = []

    try:
        async with _patched_generation():
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=120) as client:
                tasks: list[asyncio.Task] = []
                cursor = 0
                for idx in range(args.novel_workers):
                    tasks.append(asyncio.create_task(_worker(client, fixtures[cursor], "generate_novel", idx + 1)))
                    cursor += 1
                for idx in range(args.framework_workers):
                    tasks.append(asyncio.create_task(_worker(client, fixtures[cursor], "framework_generate", idx + 1)))
                    cursor += 1
                for idx in range(args.manga_workers):
                    tasks.append(asyncio.create_task(_worker(client, fixtures[cursor], "generate_manga_stream", idx + 1)))
                    cursor += 1
                results = await asyncio.gather(*tasks)
    finally:
        stop_event.set()
        db_stats = await monitor_task
        for fixture in fixtures:
            _cleanup_fixture(fixture)

    summary = _summarize_results(results)
    failures: list[str] = []
    for endpoint, endpoint_summary in summary.items():
        if endpoint_summary["ok_count"] != endpoint_summary["count"]:
            failures.append(f"{endpoint} has non-200 responses: {endpoint_summary['status_codes']}")
    if db_stats["delta_long_idle_in_tx"] > 0:
        failures.append(
            f"long idle in transaction delta observed: {db_stats['delta_long_idle_in_tx']} "
            f"(threshold={LONG_IDLE_THRESHOLD_SECONDS}s)"
        )

    output = {
        "workers": {
            "generate_novel": args.novel_workers,
            "framework_generate": args.framework_workers,
            "generate_manga_stream": args.manga_workers,
        },
        "db_stats": db_stats,
        "long_idle_threshold_seconds": LONG_IDLE_THRESHOLD_SECONDS,
        "summary": summary,
        "failures": failures,
        "ok": not failures,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
