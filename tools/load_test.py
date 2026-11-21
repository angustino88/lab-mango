"""Configurable concurrent-user performance and load-testing tool for Lab Mango.

Supports single endpoints, multi-endpoint weighted scenarios, or built-in preset scenarios
(such as ``equipment_table`` / ``computing_table`` / ``dashboard`` / ``locations``).
Measures latency percentiles (p50, p90, p95, p99, max), throughput (RPS), HTTP status/ETag
rates, payload sizes, and per-endpoint breakdowns.

Run as a standalone HTTP load generator against a live server (or with ``--mint-jwt`` /
``--in-process`` when running inside the Django repository):

    python -m tools.load_test --base-url http://localhost:8000 --concurrency 100 --requests 1000 \\
        --endpoint "GET /api/labs/equipment"

    python -m tools.load_test --base-url http://localhost:8000 --concurrency 1000 --duration 30 \\
        --scenario computing_table --mint-jwt admin

    python -m tools.load_test --config tools/load_test_example.json --concurrency 200 --json-out report.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import random
import statistics
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class TargetSpec:
    """One HTTP request template in a load-test scenario."""

    name: str
    method: str
    path: str
    weight: float = 1.0
    headers: dict[str, str] = field(default_factory=dict)
    body: dict[str, Any] | str | None = None
    expected_statuses: tuple[int, ...] = (200, 201, 204, 304)


@dataclass(frozen=True, slots=True)
class SampleResult:
    """Telemetry from a single executed request."""

    target_name: str
    method: str
    path: str
    status_code: int
    elapsed_ms: float
    response_bytes: int
    ok: bool
    has_etag: bool = False
    cache_control: str = ""
    error: str = ""
    db_queries: int | None = None


@dataclass(slots=True)
class EndpointMetrics:
    """Aggregated latency, throughput, and status statistics for one target."""

    name: str
    method: str
    path: str
    total_requests: int
    ok_requests: int
    failed_requests: int
    error_rate_pct: float
    rps: float
    min_ms: float
    mean_ms: float
    median_ms: float
    p90_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float
    stdev_ms: float
    total_bytes: int
    avg_bytes: float
    etag_present_count: int
    not_modified_304_count: int
    status_counts: dict[str, int]
    errors: dict[str, int]
    avg_db_queries: float | None = None


@dataclass(slots=True)
class LoadTestReport:
    """Complete benchmark report across all targets."""

    base_url: str
    mode: str
    concurrency: int
    total_duration_s: float
    overall: EndpointMetrics
    endpoints: list[EndpointMetrics]


PRESET_SCENARIOS: dict[str, list[TargetSpec]] = {
    "computing_table": [
        TargetSpec(
            name="equipment_list_page1",
            method="GET",
            path="/api/labs/equipment?page=1&page_size=25",
            weight=5.0,
        ),
        TargetSpec(
            name="equipment_list_available",
            method="GET",
            path="/api/labs/equipment?status=available&page=1&page_size=25",
            weight=2.0,
        ),
        TargetSpec(
            name="equipment_list_search",
            method="GET",
            path="/api/labs/equipment?q=pc&page=1&page_size=25",
            weight=1.5,
        ),
        TargetSpec(
            name="equipment_reference_data",
            method="GET",
            path="/api/labs/equipment/reference-data",
            weight=1.0,
        ),
        TargetSpec(
            name="equipment_facets_kind",
            method="GET",
            path="/api/labs/equipment/facets?dimension=kind&page_size=25",
            weight=1.0,
        ),
        TargetSpec(
            name="equipment_facets_manufacturer",
            method="GET",
            path="/api/labs/equipment/facets?dimension=manufacturer&page_size=25",
            weight=1.0,
        ),
        TargetSpec(
            name="equipment_options",
            method="GET",
            path="/api/labs/equipment/options?q=a",
            weight=1.0,
        ),
    ],
    "equipment_table": [
        TargetSpec(
            name="equipment_list",
            method="GET",
            path="/api/labs/equipment?page=1&page_size=25",
            weight=4.0,
        ),
        TargetSpec(
            name="equipment_filters",
            method="GET",
            path="/api/labs/equipment/filters",
            weight=1.0,
        ),
        TargetSpec(
            name="equipment_reference_data",
            method="GET",
            path="/api/labs/equipment/reference-data",
            weight=1.0,
        ),
        TargetSpec(
            name="equipment_facets_category",
            method="GET",
            path="/api/labs/equipment/facets?dimension=category",
            weight=1.0,
        ),
    ],
    "locations_and_benches": [
        TargetSpec(
            name="benches_list",
            method="GET",
            path="/api/labs/benches?page=1&page_size=25",
            weight=3.0,
        ),
        TargetSpec(
            name="stations_list",
            method="GET",
            path="/api/labs/stations?page=1&page_size=25",
            weight=2.0,
        ),
        TargetSpec(
            name="rooms_list",
            method="GET",
            path="/api/labs/rooms?page=1&page_size=25",
            weight=1.0,
        ),
    ],
    "licenses": [
        TargetSpec(
            name="licenses_list",
            method="GET",
            path="/api/labs/licenses?page=1&page_size=25",
            weight=3.0,
        ),
        TargetSpec(
            name="licenses_options",
            method="GET",
            path="/api/labs/licenses/options",
            weight=1.0,
        ),
    ],
}


def percentile(sorted_values: Sequence[float], pct: float) -> float:
    """Compute linear-interpolated percentile (0..100) from a pre-sorted sequence."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    rank = (pct / 100.0) * (len(sorted_values) - 1)
    lower = int(math.floor(rank))
    upper = int(math.ceil(rank))
    if lower == upper:
        return float(sorted_values[lower])
    weight = rank - lower
    return float(sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight)


def summarize_samples(
    name: str,
    method: str,
    path: str,
    samples: Sequence[SampleResult],
    duration_s: float,
) -> EndpointMetrics:
    """Aggregate raw SampleResult items into an EndpointMetrics summary."""
    total = len(samples)
    ok_count = sum(1 for item in samples if item.ok)
    failed_count = total - ok_count
    latencies = sorted(item.elapsed_ms for item in samples)
    total_bytes = sum(item.response_bytes for item in samples)
    status_counter: Counter[str] = Counter()
    error_counter: Counter[str] = Counter()
    etag_count = 0
    not_modified_count = 0
    query_counts: list[int] = []

    for item in samples:
        status_counter[str(item.status_code)] += 1
        if item.error:
            error_counter[item.error] += 1
        if item.has_etag:
            etag_count += 1
        if item.status_code == 304:
            not_modified_count += 1
        if item.db_queries is not None:
            query_counts.append(item.db_queries)

    safe_duration = max(duration_s, 1e-6)
    return EndpointMetrics(
        name=name,
        method=method,
        path=path,
        total_requests=total,
        ok_requests=ok_count,
        failed_requests=failed_count,
        error_rate_pct=round((failed_count / total * 100.0) if total else 0.0, 2),
        rps=round(total / safe_duration, 2),
        min_ms=round(latencies[0], 2) if latencies else 0.0,
        mean_ms=round(statistics.fmean(latencies), 2) if latencies else 0.0,
        median_ms=round(percentile(latencies, 50), 2),
        p90_ms=round(percentile(latencies, 90), 2),
        p95_ms=round(percentile(latencies, 95), 2),
        p99_ms=round(percentile(latencies, 99), 2),
        max_ms=round(latencies[-1], 2) if latencies else 0.0,
        stdev_ms=round(statistics.stdev(latencies), 2) if len(latencies) > 1 else 0.0,
        total_bytes=total_bytes,
        avg_bytes=round(total_bytes / total, 1) if total else 0.0,
        etag_present_count=etag_count,
        not_modified_304_count=not_modified_count,
        status_counts=dict(sorted(status_counter.items())),
        errors=dict(error_counter.most_common(5)),
        avg_db_queries=round(statistics.fmean(query_counts), 2) if query_counts else None,
    )


def parse_endpoint_arg(raw: str, index: int) -> TargetSpec:
    """Parse ``[NAME=]METHOD /path[|weight]`` or ``/path`` into a TargetSpec."""
    spec = raw.strip()
    weight = 1.0
    if "|" in spec:
        spec, weight_part = spec.rsplit("|", 1)
        weight = float(weight_part.strip())

    name = f"endpoint_{index}"
    if "=" in spec and (" " in spec.split("=", 1)[1].strip() or spec.split("=", 1)[1].strip().startswith("/")):
        candidate_name, rest = spec.split("=", 1)
        if candidate_name.strip() and "/" not in candidate_name:
            name = candidate_name.strip()
            spec = rest.strip()

    parts = spec.split(None, 1)
    if len(parts) == 1:
        method = "GET"
        path = parts[0]
    else:
        method = parts[0].upper()
        path = parts[1].strip()

    if not path.startswith("/"):
        path = "/" + path

    if name == f"endpoint_{index}":
        name = f"{method} {path}"
    return TargetSpec(name=name, method=method, path=path, weight=weight)


def load_config_file(config_path: Path) -> dict[str, Any]:
    """Load a JSON configuration file defining targets and optional test parameters."""
    data = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Configuration JSON root must be an object.")
    return data


def build_targets(args: argparse.Namespace) -> list[TargetSpec]:
    """Assemble the list of TargetSpec items from CLI flags, preset scenario, or config file."""
    targets: list[TargetSpec] = []

    if args.config:
        raw_cfg = load_config_file(Path(args.config))
        for idx, item in enumerate(raw_cfg.get("endpoints", []), start=1):
            if isinstance(item, str):
                targets.append(parse_endpoint_arg(item, idx))
            elif isinstance(item, dict):
                path = str(item["path"])
                method = str(item.get("method", "GET")).upper()
                targets.append(
                    TargetSpec(
                        name=str(item.get("name") or f"{method} {path}"),
                        method=method,
                        path=path,
                        weight=float(item.get("weight", 1.0)),
                        headers=dict(item.get("headers") or {}),
                        body=item.get("body"),
                        expected_statuses=tuple(int(s) for s in item.get("expected_statuses", (200, 201, 204, 304))),
                    )
                )

    if args.scenario:
        for scenario_name in args.scenario:
            if scenario_name not in PRESET_SCENARIOS:
                known = ", ".join(sorted(PRESET_SCENARIOS))
                raise SystemExit(f"Unknown scenario {scenario_name!r}. Available: {known}")
            targets.extend(PRESET_SCENARIOS[scenario_name])

    if args.endpoint:
        for idx, raw_ep in enumerate(args.endpoint, start=len(targets) + 1):
            targets.append(parse_endpoint_arg(raw_ep, idx))

    if not targets:
        targets.extend(PRESET_SCENARIOS["computing_table"])

    return targets


def _setup_django(settings_module: str | None = None) -> None:
    if settings_module:
        os.environ["DJANGO_SETTINGS_MODULE"] = settings_module
    else:
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")
    import django
    from django.apps import apps

    if not apps.ready:
        django.setup()


def mint_jwt_for_user(username: str, *, settings_module: str | None = None) -> str:
    """Mint a valid SimpleJWT Bearer access token for an existing user (or temporary load-test admin)."""
    _setup_django(settings_module)
    from django.contrib.auth import get_user_model
    from rest_framework_simplejwt.tokens import AccessToken

    user_model = get_user_model()
    user = user_model.objects.filter(username=username).first()
    if user is None:
        raise SystemExit(
            f"User {username!r} not found in database. Create the user first or pass an existing username."
        )
    return str(AccessToken.for_user(user))


def _choose_target(targets: Sequence[TargetSpec], weights: Sequence[float]) -> TargetSpec:
    if len(targets) == 1:
        return targets[0]
    return random.choices(targets, weights=weights, k=1)[0]


def _execute_urllib_request(
    base_url: str,
    target: TargetSpec,
    shared_headers: dict[str, str],
    timeout_s: float,
    cached_etag: str | None = None,
) -> tuple[SampleResult, str | None]:
    """Execute one HTTP request via urllib (stdlib fallback when httpx is unavailable)."""
    url = base_url.rstrip("/") + target.path
    headers = {**shared_headers, **target.headers}
    if cached_etag and "If-None-Match" not in headers:
        headers["If-None-Match"] = cached_etag

    body_bytes: bytes | None = None
    if target.body is not None:
        if isinstance(target.body, (dict, list)):
            body_bytes = json.dumps(target.body).encode("utf-8")
            headers.setdefault("Content-Type", "application/json")
        else:
            body_bytes = str(target.body).encode("utf-8")

    req = urllib.request.Request(url, data=body_bytes, headers=headers, method=target.method)
    started = time.perf_counter()
    new_etag: str | None = None
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            payload = resp.read()
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            status_code = int(resp.status)
            new_etag = resp.headers.get("ETag")
            cache_control = resp.headers.get("Cache-Control", "")
            return (
                SampleResult(
                    target_name=target.name,
                    method=target.method,
                    path=target.path,
                    status_code=status_code,
                    elapsed_ms=elapsed_ms,
                    response_bytes=len(payload),
                    ok=status_code in target.expected_statuses,
                    has_etag=bool(new_etag),
                    cache_control=cache_control,
                ),
                new_etag,
            )
    except urllib.error.HTTPError as exc:
        payload = exc.read() if exc.fp else b""
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        status_code = int(exc.code)
        new_etag = exc.headers.get("ETag") if exc.headers else None
        cache_control = exc.headers.get("Cache-Control", "") if exc.headers else ""
        ok = status_code in target.expected_statuses
        return (
            SampleResult(
                target_name=target.name,
                method=target.method,
                path=target.path,
                status_code=status_code,
                elapsed_ms=elapsed_ms,
                response_bytes=len(payload),
                ok=ok,
                has_etag=bool(new_etag),
                cache_control=cache_control,
                error="" if ok else f"HTTP {status_code}",
            ),
            new_etag,
        )
    except Exception as exc:  # noqa: BLE001
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return (
            SampleResult(
                target_name=target.name,
                method=target.method,
                path=target.path,
                status_code=0,
                elapsed_ms=elapsed_ms,
                response_bytes=0,
                ok=False,
                error=f"{type(exc).__name__}: {exc}",
            ),
            None,
        )


async def run_http_load_test(
    *,
    base_url: str,
    targets: Sequence[TargetSpec],
    concurrency: int,
    total_requests: int | None,
    duration_s: float | None,
    warmup_requests: int,
    timeout_s: float,
    shared_headers: dict[str, str],
    reuse_etag: bool,
    think_time_ms: float,
    ramp_up_s: float,
) -> tuple[list[SampleResult], float]:
    """Run concurrent HTTP virtual users using httpx.AsyncClient (or asyncio threadpool fallback)."""
    weights = [max(t.weight, 0.001) for t in targets]
    try:
        import httpx

        has_httpx = True
    except ImportError:
        has_httpx = False

    if has_httpx:
        import httpx

        limits = httpx.Limits(
            max_connections=max(concurrency + 20, 100),
            max_keepalive_connections=max(concurrency, 50),
        )
        timeout = httpx.Timeout(timeout_s)
        async with httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers=shared_headers,
            limits=limits,
            timeout=timeout,
        ) as client:

            async def one_call(target: TargetSpec, cached_etag: str | None) -> tuple[SampleResult, str | None]:
                req_headers = dict(target.headers)
                if cached_etag and "If-None-Match" not in req_headers:
                    req_headers["If-None-Match"] = cached_etag
                started = time.perf_counter()
                try:
                    if isinstance(target.body, (dict, list)):
                        resp = await client.request(target.method, target.path, headers=req_headers, json=target.body)
                    elif target.body is not None:
                        resp = await client.request(
                            target.method, target.path, headers=req_headers, content=str(target.body)
                        )
                    else:
                        resp = await client.request(target.method, target.path, headers=req_headers)
                    elapsed_ms = (time.perf_counter() - started) * 1000.0
                    etag = resp.headers.get("etag")
                    cache_ctrl = resp.headers.get("cache-control", "")
                    ok = resp.status_code in target.expected_statuses
                    return (
                        SampleResult(
                            target_name=target.name,
                            method=target.method,
                            path=target.path,
                            status_code=resp.status_code,
                            elapsed_ms=elapsed_ms,
                            response_bytes=len(resp.content),
                            ok=ok,
                            has_etag=bool(etag),
                            cache_control=cache_ctrl,
                            error="" if ok else f"HTTP {resp.status_code}",
                        ),
                        etag,
                    )
                except Exception as exc:  # noqa: BLE001
                    elapsed_ms = (time.perf_counter() - started) * 1000.0
                    return (
                        SampleResult(
                            target_name=target.name,
                            method=target.method,
                            path=target.path,
                            status_code=0,
                            elapsed_ms=elapsed_ms,
                            response_bytes=0,
                            ok=False,
                            error=f"{type(exc).__name__}: {exc}",
                        ),
                        None,
                    )

            return await _drive_virtual_users(
                one_call=one_call,
                targets=targets,
                weights=weights,
                concurrency=concurrency,
                total_requests=total_requests,
                duration_s=duration_s,
                warmup_requests=warmup_requests,
                reuse_etag=reuse_etag,
                think_time_ms=think_time_ms,
                ramp_up_s=ramp_up_s,
            )

    async def urllib_call(target: TargetSpec, cached_etag: str | None) -> tuple[SampleResult, str | None]:
        return await asyncio.to_thread(
            _execute_urllib_request, base_url, target, shared_headers, timeout_s, cached_etag
        )

    return await _drive_virtual_users(
        one_call=urllib_call,
        targets=targets,
        weights=weights,
        concurrency=concurrency,
        total_requests=total_requests,
        duration_s=duration_s,
        warmup_requests=warmup_requests,
        reuse_etag=reuse_etag,
        think_time_ms=think_time_ms,
        ramp_up_s=ramp_up_s,
    )


async def _drive_virtual_users(
    *,
    one_call: Any,
    targets: Sequence[TargetSpec],
    weights: Sequence[float],
    concurrency: int,
    total_requests: int | None,
    duration_s: float | None,
    warmup_requests: int,
    reuse_etag: bool,
    think_time_ms: float,
    ramp_up_s: float,
) -> tuple[list[SampleResult], float]:
    """Coordinate warmup and concurrent virtual-user coroutines."""
    # Warm-up phase (sequential or low-concurrency)
    for i in range(warmup_requests):
        target = targets[i % len(targets)]
        await one_call(target, None)

    results: list[SampleResult] = []
    issued_counter = 0
    counter_lock = asyncio.Lock()
    start_wall = time.perf_counter()
    deadline = (start_wall + duration_s) if duration_s and duration_s > 0 else None

    async def claim_slot() -> bool:
        nonlocal issued_counter
        if deadline is not None and time.perf_counter() >= deadline:
            return False
        if total_requests is not None:
            async with counter_lock:
                if issued_counter >= total_requests:
                    return False
                issued_counter += 1
        return True

    async def virtual_user(worker_idx: int) -> None:
        if ramp_up_s > 0 and concurrency > 1:
            delay = (worker_idx / concurrency) * ramp_up_s
            await asyncio.sleep(delay)

        etag_by_path: dict[str, str] = {}
        while await claim_slot():
            target = _choose_target(targets, weights)
            cached_etag = etag_by_path.get(target.path) if reuse_etag else None
            sample, received_etag = await one_call(target, cached_etag)
            if reuse_etag and received_etag:
                etag_by_path[target.path] = received_etag
            results.append(sample)
            if think_time_ms > 0:
                await asyncio.sleep(think_time_ms / 1000.0)

    workers = [asyncio.create_task(virtual_user(idx)) for idx in range(concurrency)]
    await asyncio.gather(*workers)
    elapsed_wall = time.perf_counter() - start_wall
    return results, elapsed_wall


def run_in_process_benchmark(
    *,
    targets: Sequence[TargetSpec],
    concurrency: int,
    total_requests: int,
    warmup_requests: int,
    shared_headers: dict[str, str],
    reuse_etag: bool,
    username: str | None,
    settings_module: str | None,
    seed_computing_rows: int = 0,
) -> tuple[list[SampleResult], float]:
    """Run requests through Django's ASGI/WSGI test client in-process with SQL query counting."""
    _setup_django(settings_module)
    from concurrent.futures import ThreadPoolExecutor

    from django.contrib.auth import get_user_model
    from django.db import close_old_connections, connection
    from django.test.utils import CaptureQueriesContext
    from rest_framework.test import APIClient

    user_model = get_user_model()
    actor = None
    if username:
        actor = user_model.objects.filter(username=username).first()
    if actor is None:
        actor, _ = user_model.objects.get_or_create(
            username="loadtest.admin",
            defaults={"is_staff": True, "is_superuser": True, "is_active": True},
        )

    if seed_computing_rows > 0:
        _seed_synthetic_computing_inventory(seed_computing_rows)

    weights = [max(t.weight, 0.001) for t in targets]

    def execute_one(target: TargetSpec, cached_etag: str | None = None) -> tuple[SampleResult, str | None]:
        close_old_connections()
        client = APIClient()
        if "Authorization" not in shared_headers and "X-Api-Key" not in shared_headers:
            client.force_authenticate(user=actor)

        extra: dict[str, str] = {}
        for k, v in {**shared_headers, **target.headers}.items():
            header_key = "HTTP_" + k.upper().replace("-", "_")
            extra[header_key] = v
        if cached_etag and "HTTP_IF_NONE_MATCH" not in extra:
            extra["HTTP_IF_NONE_MATCH"] = cached_etag

        started = time.perf_counter()
        try:
            with CaptureQueriesContext(connection) as captured:
                method_fn = getattr(client, target.method.lower())
                if target.body is not None:
                    resp = method_fn(target.path, data=target.body, format="json", **extra)
                else:
                    resp = method_fn(target.path, **extra)
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            content_bytes = len(resp.content) if hasattr(resp, "content") else 0
            etag = resp.headers.get("ETag") if hasattr(resp, "headers") else None
            cache_ctrl = resp.headers.get("Cache-Control", "") if hasattr(resp, "headers") else ""
            ok = resp.status_code in target.expected_statuses
            return (
                SampleResult(
                    target_name=target.name,
                    method=target.method,
                    path=target.path,
                    status_code=int(resp.status_code),
                    elapsed_ms=elapsed_ms,
                    response_bytes=content_bytes,
                    ok=ok,
                    has_etag=bool(etag),
                    cache_control=cache_ctrl,
                    error="" if ok else f"HTTP {resp.status_code}",
                    db_queries=len(captured.captured_queries),
                ),
                etag,
            )
        except Exception as exc:  # noqa: BLE001
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            return (
                SampleResult(
                    target_name=target.name,
                    method=target.method,
                    path=target.path,
                    status_code=0,
                    elapsed_ms=elapsed_ms,
                    response_bytes=0,
                    ok=False,
                    error=f"{type(exc).__name__}: {exc}",
                ),
                None,
            )

    for i in range(warmup_requests):
        execute_one(targets[i % len(targets)], None)

    chosen_targets = [_choose_target(targets, weights) for _ in range(total_requests)]
    results: list[SampleResult] = []
    start_wall = time.perf_counter()

    def worker_batch(worker_targets: list[TargetSpec]) -> list[SampleResult]:
        local_results: list[SampleResult] = []
        etag_cache: dict[str, str] = {}
        for target in worker_targets:
            cached = etag_cache.get(target.path) if reuse_etag else None
            sample, new_etag = execute_one(target, cached)
            if reuse_etag and new_etag:
                etag_cache[target.path] = new_etag
            local_results.append(sample)
        return local_results

    batches: list[list[TargetSpec]] = [[] for _ in range(concurrency)]
    for idx, target in enumerate(chosen_targets):
        batches[idx % concurrency].append(target)

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        for batch_res in pool.map(worker_batch, [b for b in batches if b]):
            results.extend(batch_res)

    elapsed_wall = time.perf_counter() - start_wall
    return results, elapsed_wall


def _seed_synthetic_computing_inventory(count: int) -> None:
    """Ensure ``count`` synthetic computing equipment rows exist for reproducible local benchmarking."""
    from core.labs.models import ComputingProfile, Equipment, EquipmentCategory, EquipmentKind

    category, _ = EquipmentCategory.objects.get_or_create(
        key="computing",
        defaults={"name": "Computing", "definition": "Computing units", "monitored": True},
    )
    if not category.monitored:
        EquipmentCategory.objects.filter(pk=category.pk).update(monitored=True)
    kind, _ = EquipmentKind.objects.get_or_create(
        name="Benchmark PC",
        category=category,
        defaults={"key": "benchmark-pc"},
    )
    existing = Equipment.objects.filter(sku__startswith="BENCH-PC-").count()
    needed = max(0, count - existing)
    if needed == 0:
        return

    new_units = [
        Equipment(
            sku=f"BENCH-PC-{existing + i + 1:05d}",
            name=f"Benchmark Computing Unit {existing + i + 1:05d}",
            kind=kind,
            serial_number=f"SN-BENCH-{existing + i + 1:05d}",
        )
        for i in range(needed)
    ]
    created = Equipment.objects.bulk_create(new_units, batch_size=500)
    profiles = [
        ComputingProfile(
            equipment=unit,
            hostname=f"pc-bench-{unit.pk}.lab.local",
            ip_address=f"10.20.{(idx // 250) % 250 + 1}.{(idx % 250) + 1}",
            os_name="Windows 11 Enterprise" if idx % 2 == 0 else "Ubuntu 24.04 LTS",
        )
        for idx, unit in enumerate(created)
    ]
    ComputingProfile.objects.bulk_create(profiles, batch_size=500)


def build_report(
    *,
    base_url: str,
    mode: str,
    concurrency: int,
    targets: Sequence[TargetSpec],
    samples: Sequence[SampleResult],
    duration_s: float,
) -> LoadTestReport:
    """Create a structured LoadTestReport from collected samples."""
    overall = summarize_samples("ALL ENDPOINTS", "MIXED", "*", samples, duration_s)
    grouped: dict[str, list[SampleResult]] = defaultdict(list)
    target_by_name = {t.name: t for t in targets}
    for sample in samples:
        grouped[sample.target_name].append(sample)

    endpoint_metrics: list[EndpointMetrics] = []
    for name, group in grouped.items():
        spec = target_by_name.get(name)
        method = spec.method if spec else group[0].method
        path = spec.path if spec else group[0].path
        endpoint_metrics.append(summarize_samples(name, method, path, group, duration_s))

    return LoadTestReport(
        base_url=base_url,
        mode=mode,
        concurrency=concurrency,
        total_duration_s=round(duration_s, 3),
        overall=overall,
        endpoints=endpoint_metrics,
    )


def print_report(report: LoadTestReport) -> None:
    """Render a clean human-readable performance table to stdout."""
    ov = report.overall
    print("=" * 108)
    print(f"Lab Mango Concurrent Load Test Report | Mode: {report.mode} | Target: {report.base_url}")
    print(
        f"Concurrency: {report.concurrency} users | Total Duration: {report.total_duration_s:.2f}s | "
        f"Total Requests: {ov.total_requests} | Throughput: {ov.rps:.2f} req/s"
    )
    print("=" * 108)
    header = (
        f"{'Endpoint':<30} {'Reqs':>6} {'Err%':>6} {'RPS':>8} "
        f"{'p50(ms)':>9} {'p90(ms)':>9} {'p95(ms)':>9} {'p99(ms)':>9} {'Max(ms)':>9} {'AvgKB':>7}"
    )
    if ov.avg_db_queries is not None:
        header += f" {'Queries':>7}"
    print(header)
    print("-" * len(header))

    rows_to_print = [*report.endpoints, ov] if len(report.endpoints) > 1 else [ov]
    for metric in rows_to_print:
        if metric is ov and len(report.endpoints) > 1:
            print("-" * len(header))
        label = metric.name[:30]
        avg_kb = metric.avg_bytes / 1024.0
        line = (
            f"{label:<30} {metric.total_requests:>6} {metric.error_rate_pct:>5.1f}% {metric.rps:>8.2f} "
            f"{metric.median_ms:>9.2f} {metric.p90_ms:>9.2f} {metric.p95_ms:>9.2f} "
            f"{metric.p99_ms:>9.2f} {metric.max_ms:>9.2f} {avg_kb:>7.1f}"
        )
        if ov.avg_db_queries is not None:
            q_str = f"{metric.avg_db_queries:.1f}" if metric.avg_db_queries is not None else "-"
            line += f" {q_str:>7}"
        print(line)

    print("=" * len(header))
    for metric in report.endpoints:
        statuses = ", ".join(f"{code}:{cnt}" for code, cnt in metric.status_counts.items())
        etag_info = (
            f" | ETag headers: {metric.etag_present_count}/{metric.total_requests} "
            f"(304 Not Modified: {metric.not_modified_304_count})"
            if metric.etag_present_count or metric.not_modified_304_count
            else ""
        )
        print(f"  • {metric.name} [{metric.method} {metric.path}] -> Statuses: {{{statuses}}}{etag_info}")
        if metric.errors:
            print(f"    Errors: {metric.errors}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tools.load_test",
        description="Configurable concurrent-user performance and load-testing tool for Lab Mango.",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("LABMANGO_BASE_URL", "http://localhost:8000"),
        help="Target server base URL (default: http://localhost:8000).",
    )
    parser.add_argument(
        "-c",
        "--concurrency",
        type=int,
        default=50,
        help="Number of concurrent virtual users (default: 50).",
    )
    parser.add_argument(
        "-n",
        "--requests",
        type=int,
        default=200,
        help="Total number of measured requests across all virtual users (default: 200; ignored if --duration is set).",
    )
    parser.add_argument(
        "-d",
        "--duration",
        type=float,
        default=None,
        help="Run continuously for this duration in seconds instead of a fixed request count.",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=5,
        help="Number of unmeasured warm-up requests before starting the benchmark (default: 5).",
    )
    parser.add_argument(
        "--ramp-up",
        type=float,
        default=0.0,
        help="Seconds over which to linearly ramp up the virtual users (default: 0).",
    )
    parser.add_argument(
        "--think-time-ms",
        type=float,
        default=0.0,
        help="Delay in milliseconds between requests per virtual user (default: 0).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Per-request timeout in seconds (default: 30).",
    )
    parser.add_argument(
        "-e",
        "--endpoint",
        action="append",
        help=(
            "Endpoint spec to test (repeatable). Format: '[name=]METHOD /api/path[|weight]' "
            "or '/api/path'. Example: --endpoint 'list=GET /api/labs/equipment?page_size=25|4'"
        ),
    )
    parser.add_argument(
        "-s",
        "--scenario",
        action="append",
        choices=sorted(PRESET_SCENARIOS),
        help=f"Run a built-in multi-endpoint scenario ({', '.join(sorted(PRESET_SCENARIOS))}). Repeatable.",
    )
    parser.add_argument(
        "--config",
        help="Path to a JSON scenario file specifying endpoints, headers, and weights.",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("LABMANGO_BEARER_TOKEN"),
        help="Bearer JWT access token (or set $LABMANGO_BEARER_TOKEN).",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("LABMANGO_API_KEY"),
        help="API key for X-Api-Key / Authorization Api-Key header (or set $LABMANGO_API_KEY).",
    )
    parser.add_argument(
        "--mint-jwt",
        metavar="USERNAME",
        help="Mint a SimpleJWT Bearer token directly via Django ORM for USERNAME before running.",
    )
    parser.add_argument(
        "--header",
        action="append",
        default=[],
        help="Extra HTTP header in 'Key: Value' format (repeatable).",
    )
    parser.add_argument(
        "--reuse-etag",
        action="store_true",
        help="Cache ETag per virtual user and send If-None-Match on subsequent requests to test 304 caching.",
    )
    parser.add_argument(
        "--in-process",
        action="store_true",
        help="Run against Django's in-process test client instead of live HTTP (also measures DB query count per request).",
    )
    parser.add_argument(
        "--seed-computing",
        type=int,
        default=0,
        metavar="COUNT",
        help="When using --in-process, ensure at least COUNT synthetic computing equipment rows exist.",
    )
    parser.add_argument(
        "--settings",
        default=None,
        help="Django settings module when using --mint-jwt or --in-process (default: config.settings.local).",
    )
    parser.add_argument(
        "--json-out",
        metavar="PATH",
        help="Write the full structured benchmark report as JSON to PATH.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.concurrency < 1:
        parser.error("--concurrency must be >= 1")
    if args.duration is None and (args.requests is None or args.requests < 1):
        parser.error("--requests must be >= 1 when --duration is not specified")

    targets = build_targets(args)
    shared_headers: dict[str, str] = {"Accept": "application/json"}

    for raw_header in args.header:
        if ":" not in raw_header:
            parser.error(f"Invalid --header {raw_header!r}; expected 'Key: Value'")
        k, v = raw_header.split(":", 1)
        shared_headers[k.strip()] = v.strip()

    token = args.token
    if args.mint_jwt:
        token = mint_jwt_for_user(args.mint_jwt, settings_module=args.settings)
    if token:
        shared_headers["Authorization"] = f"Bearer {token}"
    elif args.api_key:
        shared_headers["Authorization"] = f"Api-Key {args.api_key}"

    total_requests = None if args.duration else args.requests

    if args.in_process:
        samples, elapsed_s = run_in_process_benchmark(
            targets=targets,
            concurrency=args.concurrency,
            total_requests=total_requests or args.concurrency * 5,
            warmup_requests=args.warmup,
            shared_headers=shared_headers,
            reuse_etag=args.reuse_etag,
            username=args.mint_jwt,
            settings_module=args.settings,
            seed_computing_rows=args.seed_computing,
        )
        mode = "in-process (Django APIClient + SQL query counter)"
    else:
        samples, elapsed_s = asyncio.run(
            run_http_load_test(
                base_url=args.base_url,
                targets=targets,
                concurrency=args.concurrency,
                total_requests=total_requests,
                duration_s=args.duration,
                warmup_requests=args.warmup,
                timeout_s=args.timeout,
                shared_headers=shared_headers,
                reuse_etag=args.reuse_etag,
                think_time_ms=args.think_time_ms,
                ramp_up_s=args.ramp_up,
            )
        )
        mode = "async-http (httpx/urllib)"

    report = build_report(
        base_url="in-process://django" if args.in_process else args.base_url,
        mode=mode,
        concurrency=args.concurrency,
        targets=targets,
        samples=samples,
        duration_s=elapsed_s,
    )
    print_report(report)

    if args.json_out:
        out_path = Path(args.json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(asdict(report), indent=2) + "\n", encoding="utf-8")
        print(f"\nSaved JSON report to {out_path}")

    return 0 if report.overall.failed_requests == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
