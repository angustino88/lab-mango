"""Permanent semantic drift guards for the scoped bench GET generator."""

from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from scripts.openapi.generate_bench_detail import DETAIL_OPERATION_ID, DETAIL_PATH, assert_no_drift


@pytest.fixture()
def module():
    return yaml.safe_load(Path("openapi/labs-benches.yml").read_text(encoding="utf-8"))


def test_established_operation_id_and_identical_candidate(module):
    assert module["paths"][DETAIL_PATH]["get"]["operationId"] == DETAIL_OPERATION_ID
    assert_no_drift(module, deepcopy(module))


@pytest.mark.parametrize("target", ["operation", "component", "operation_id"])
def test_check_rejects_committed_contract_drift(module, target):
    committed = deepcopy(module)
    if target == "operation":
        committed["paths"][DETAIL_PATH]["get"]["summary"] = "Drifted summary"
    elif target == "component":
        ref = committed["paths"][DETAIL_PATH]["get"]["responses"]["200"]["content"]["application/json"]["schema"][
            "$ref"
        ]
        name = ref.rsplit("/", 1)[1]
        committed["components"]["schemas"][name]["description"] = "Drifted component"
    else:
        committed["paths"][DETAIL_PATH]["get"]["operationId"] = "benches_retrieve_by_bench_id"
    with pytest.raises(AssertionError, match="drift"):
        assert_no_drift(committed, module)


def test_check_ignores_unrelated_operations_and_components(module):
    committed = deepcopy(module)
    committed["paths"][DETAIL_PATH]["patch"]["summary"] = "Unrelated write"
    committed["components"]["schemas"]["UnreachableSyntheticComponent"] = {"type": "string"}
    assert_no_drift(committed, module)
