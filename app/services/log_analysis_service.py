from __future__ import annotations

import re
from typing import Any

from app.config import settings
from app.repositories import log_repository
from app.services.advisor_service import (
    Recommendation,
    build_index_recommendation,
    extract_candidates_from_query,
    normalize_query,
)


SLOW_LOG_LINE = re.compile(r"duration:\s*([0-9]+(?:\.[0-9]+)?)\s*ms\s+(?:statement:|execute\s+[^:]+:)\s*(.*)", re.I)
ANY_DURATION_LINE = re.compile(r"duration:\s*([0-9]+(?:\.[0-9]+)?)\s*ms\s+(.*)", re.I)


def iter_slow_log_entries(text: str):
    current_duration: float | None = None
    current_query: list[str] = []

    def flush():
        nonlocal current_duration, current_query
        if current_duration is not None:
            query = "\n".join(current_query).strip()
            if query:
                yield {"duration_ms": current_duration, "query": query}
        current_duration = None
        current_query = []

    for line in text.splitlines():
        match = SLOW_LOG_LINE.search(line)
        if not match:
            any_duration = ANY_DURATION_LINE.search(line)
            if any_duration:
                for entry in flush():
                    yield entry
                query = any_duration.group(2).replace("statement:", "", 1).strip()
                current_duration = float(any_duration.group(1))
                current_query = [query]
                continue
            if current_duration is not None and line.strip():
                if sum(len(item) for item in current_query) < 20000:
                    current_query.append(line)
            continue
        for entry in flush():
            yield entry
        current_duration = float(match.group(1))
        current_query = [match.group(2).strip()]
    for entry in flush():
        yield entry


async def process_log_text_to_cache(
    *,
    text: str,
    min_ms: float,
    database: str | None,
    postgres_config_id: str | None,
    environment_id: str | None,
    source: str,
    lines_requested: int | None = None,
    command: str | None = None,
    fetch_error: str | None = None,
    raw_bytes: int | None = None,
    raw_truncated: bool = False,
) -> int:
    run_id = log_repository.create_run(
        database_name=database,
        postgres_config_id=postgres_config_id,
        environment_id=environment_id,
        source=source,
        min_ms=min_ms,
        lines_requested=lines_requested,
        command=command,
        fetch_error=fetch_error,
        raw_bytes=raw_bytes if raw_bytes is not None else len(text.encode("utf-8", errors="replace")),
        raw_truncated=raw_truncated,
    )

    grouped: dict[str, dict[str, Any]] = {}
    entries_count = 0
    ignored_count = 0
    for entry in iter_slow_log_entries(text):
        duration = float(entry["duration_ms"])
        if duration < float(min_ms or 0):
            ignored_count += 1
            continue
        entries_count += 1
        query = str(entry["query"])
        normalized = normalize_query(query)
        group = grouped.setdefault(normalized, {"normalized_query": normalized, "calls": 0, "total_ms": 0.0, "max_ms": 0.0, "sample_query": query[:20000]})
        group["calls"] += 1
        group["total_ms"] += duration
        group["max_ms"] = max(float(group["max_ms"]), duration)

    rows: list[dict[str, Any]] = []
    for group in grouped.values():
        calls = max(int(group["calls"]), 1)
        group["mean_ms"] = round(float(group["total_ms"]) / calls, 2)
        group["total_ms"] = round(float(group["total_ms"]), 2)
        group["max_ms"] = round(float(group["max_ms"]), 2)
        rows.append(group)
    rows.sort(key=lambda item: item["total_ms"], reverse=True)
    log_repository.save_groups(run_id, rows)
    log_repository.update_run_counts(run_id, entries_count=entries_count, ignored_count=ignored_count, groups_count=len(rows))

    recommendations: list[Recommendation] = []
    seen_candidates: set[tuple[str, tuple[str, ...]]] = set()
    max_groups = max(10, int(settings.max_log_recommendation_groups or 250))
    max_recs = max(10, int(settings.max_log_recommendations or 250))
    for group in rows[:max_groups]:
        for table, cols in extract_candidates_from_query(group["sample_query"]):
            key = (table.lower(), tuple(col.lower() for col in cols))
            if key in seen_candidates:
                continue
            seen_candidates.add(key)
            recommendations.append(
                await build_index_recommendation(
                    table,
                    cols,
                    database=database,
                    source="slow_log_cache",
                    base_evidence=group,
                    weight_ms=float(group["total_ms"]),
                )
            )
            if len(recommendations) >= max_recs:
                break
        if len(recommendations) >= max_recs:
            break
    recommendations.sort(key=lambda rec: ({"high": 0, "medium": 1, "low": 2}.get(rec.severity, 3), -rec.confidence))
    log_repository.save_recommendations(run_id, recommendations)
    log_repository.update_run_counts(run_id, entries_count=entries_count, ignored_count=ignored_count, recommendations_count=len(recommendations))
    return run_id

