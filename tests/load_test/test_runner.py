"""Unit tests for the concurrent load-testing tool (`tools/load_test`)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx

from tools.load_test import (
    PRESET_SCENARIOS,
    SampleResult,
    TargetSpec,
    build_parser,
    build_report,
    build_targets,
    load_preset_scenarios,
    parse_endpoint_arg,
    percentile,
    run_http_load_test,
    summarize_samples,
)


def test_preset_scenarios_loaded_from_manifest():
    scenarios = load_preset_scenarios()
    assert "computing_table" in scenarios
    assert "equipment_table" in scenarios
    assert len(PRESET_SCENARIOS["computing_table"]) >= 5


def test_parse_endpoint_arg_supports_name_method_path_and_weight():
    spec = parse_endpoint_arg("computing_list=GET /api/labs/equipment?page_size=25|4.5", 1)
    assert spec.name == "computing_list"
    assert spec.method == "GET"
    assert spec.path == "/api/labs/equipment?page_size=25"
    assert spec.weight == 4.5


def test_parse_endpoint_arg_defaults_method_and_weight():
    spec = parse_endpoint_arg("/api/labs/benches?page=1", 2)
    assert spec.name == "GET /api/labs/benches?page=1"
    assert spec.method == "GET"
    assert spec.path == "/api/labs/benches?page=1"
    assert spec.weight == 1.0


def test_percentile_and_summarize_samples_metrics():
    samples = [
        SampleResult(
            target_name="equipment_list",
            method="GET",
            path="/api/labs/equipment",
            status_code=200,
            elapsed_ms=10.0,
            response_bytes=1024,
            ok=True,
            has_etag=True,
            db_queries=9,
        ),
        SampleResult(
            target_name="equipment_list",
            method="GET",
            path="/api/labs/equipment",
            status_code=304,
            elapsed_ms=20.0,
            response_bytes=0,
            ok=True,
            has_etag=True,
            db_queries=3,
        ),
        SampleResult(
            target_name="equipment_list",
            method="GET",
            path="/api/labs/equipment",
            status_code=500,
            elapsed_ms=100.0,
            response_bytes=256,
            ok=False,
            error="HTTP 500",
            db_queries=9,
        ),
    ]
    assert percentile([10.0, 20.0, 100.0], 50) == 20.0
    metrics = summarize_samples("equipment_list", "GET", "/api/labs/equipment", samples, duration_s=2.0)
    assert metrics.total_requests == 3
    assert metrics.ok_requests == 2
    assert metrics.failed_requests == 1
    assert metrics.error_rate_pct == 33.33
    assert metrics.rps == 1.5
    assert metrics.min_ms == 10.0
    assert metrics.median_ms == 20.0
    assert metrics.max_ms == 100.0
    assert metrics.etag_present_count == 2
    assert metrics.not_modified_304_count == 1
    assert metrics.status_counts == {"200": 1, "304": 1, "500": 1}
    assert metrics.avg_db_queries == 7.0


def test_build_targets_combines_config_scenario_and_cli_endpoints(tmp_path: Path):
    cfg_file = tmp_path / "scenario.json"
    cfg_file.write_text(
        json.dumps(
            {
                "endpoints": [
                    {
                        "name": "custom_benches",
                        "method": "GET",
                        "path": "/api/labs/benches",
                        "weight": 2.5,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    parser = build_parser()
    args = parser.parse_args(
        [
            "--config",
            str(cfg_file),
            "--scenario",
            "licenses",
            "--endpoint",
            "rooms=GET /api/labs/rooms|1.5",
        ]
    )
    targets = build_targets(args)
    names = [t.name for t in targets]
    assert names == ["custom_benches", "licenses_list", "licenses_options", "rooms"]
    assert targets[0].weight == 2.5
    assert targets[-1].weight == 1.5


async def test_run_http_load_test_with_mocked_transport(respx_mock):
    respx_mock.get("http://testserver.local/api/labs/equipment").mock(
        return_value=httpx.Response(
            200,
            json={"data": []},
            headers={"ETag": '"etag-v1"', "Cache-Control": "private, no-cache"},
        )
    )
    respx_mock.get("http://testserver.local/api/labs/equipment/options").mock(
        return_value=httpx.Response(
            304,
            headers={"ETag": '"opt-v1"', "Cache-Control": "private, no-cache"},
        )
    )
    targets = [
        TargetSpec(name="eq_list", method="GET", path="/api/labs/equipment", weight=2.0),
        TargetSpec(name="eq_options", method="GET", path="/api/labs/equipment/options", weight=1.0),
    ]
    samples, elapsed_s = await run_http_load_test(
        base_url="http://testserver.local",
        targets=targets,
        concurrency=10,
        total_requests=30,
        duration_s=None,
        warmup_requests=2,
        timeout_s=5.0,
        shared_headers={"Authorization": "Bearer test-token"},
        reuse_etag=True,
        think_time_ms=0.0,
        ramp_up_s=0.0,
    )
    assert len(samples) == 30
    assert all(s.ok for s in samples)
    report = build_report(
        base_url="http://testserver.local",
        mode="async-http",
        concurrency=10,
        targets=targets,
        samples=samples,
        duration_s=elapsed_s,
    )
    assert report.overall.total_requests == 30
    assert report.overall.failed_requests == 0
    assert len(report.endpoints) == 2
