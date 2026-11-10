"""Exercise the real pinned Spectral CLI with synthetic, temporary OpenAPI fixtures.

Run without Django or a database using --confcutdir=tests/unit -p no:django.
Each case names a rule and the regression it detects; no generated specs are edited.
"""

import copy
import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
MONEY_RULE = "lm-money-is-decimal-string"
TIME_RULE = "lm-timestamps-are-date-time"
DATE_RULE = "lm-expense-payment-paid-at-is-date"
STATUS_RULE = "lm-allowed-status-codes"
ERROR_RULE = "lm-operation-documents-errors"

DECIMAL = {"type": "string", "format": "decimal"}
MONEY: dict = {
    "type": "object",
    "properties": {
        "amount": {"type": "string", "pattern": r"^-?[0-9]+(\.[0-9]+)?$"},
        "currency": {"type": "string"},
    },
    "required": ["amount", "currency"],
    "additionalProperties": False,
}


def document() -> dict:
    return {
        "openapi": "3.0.3",
        "info": {"title": "Synthetic lint fixture", "version": "1.0.0"},
        "paths": {},
        "components": {"schemas": {}},
    }


def money_case(schema: dict) -> dict:
    result = document()
    result["components"]["schemas"]["Purchase"] = {
        "type": "object",
        "properties": {"total_amount": schema},
    }
    return result


def wrapped_money_case(schema: dict, *, referenced: bool, nullable: bool = True) -> dict:
    """Match spectacular's read-only allOf wrapper, including resolved references."""
    result = money_case({"allOf": [schema], "nullable": nullable, "readOnly": True})
    if referenced:
        result["components"]["schemas"]["MoneyValue"] = schema
        result["components"]["schemas"]["Purchase"]["properties"]["total_amount"]["allOf"] = [
            {"$ref": "#/components/schemas/MoneyValue"}
        ]
    return result


def timestamp_case(component: str, field: str, schema: dict, *, referenced: bool = False) -> dict:
    result = document()
    result["components"]["schemas"][component] = {"type": "object", "properties": {field: schema}}
    if referenced:
        result["components"]["schemas"]["PaymentEnvelope"] = {
            "type": "object",
            "properties": {"data": {"$ref": f"#/components/schemas/{component}"}},
        }
    return result


def response_case(*statuses: str) -> dict:
    result = document()
    result["paths"]["/synthetic"] = {
        "get": {"responses": {status: {"description": "Synthetic response"} for status in statuses}}
    }
    return result


def cases() -> list[tuple[str, str, dict, bool]]:
    result = [
        ("decimal-string", MONEY_RULE, money_case(DECIMAL), True),
        ("runtime-money", MONEY_RULE, money_case(MONEY), True),
        ("number", MONEY_RULE, money_case({"type": "number"}), False),
        ("integer", MONEY_RULE, money_case({"type": "integer"}), False),
        ("bare-object", MONEY_RULE, money_case({"type": "object"}), False),
        ("empty-properties", MONEY_RULE, money_case({"type": "object", "properties": {}}), False),
        ("nullable-decimal-string", MONEY_RULE, money_case({**DECIMAL, "nullable": True}), True),
        ("nullable-runtime-money", MONEY_RULE, money_case({**MONEY, "nullable": True}), True),
        ("nullable-number", MONEY_RULE, money_case({"type": "number", "nullable": True}), False),
        ("nullable-integer", MONEY_RULE, money_case({"type": "integer", "nullable": True}), False),
        ("nullable-without-type", MONEY_RULE, money_case({"nullable": True}), False),
        ("oneof-string-number", MONEY_RULE, money_case({"oneOf": [DECIMAL, {"type": "number"}]}), False),
        ("anyof-string-integer", MONEY_RULE, money_case({"anyOf": [DECIMAL, {"type": "integer"}]}), False),
        ("empty-allof", MONEY_RULE, money_case({"allOf": []}), False),
        ("untyped-allof", MONEY_RULE, money_case({"allOf": [{}], "nullable": True}), False),
        ("multiple-allof", MONEY_RULE, money_case({"allOf": [MONEY, {}]}), False),
        (
            "numeric-wrapper-type",
            MONEY_RULE,
            money_case({"type": "number", "allOf": [MONEY], "nullable": True}),
            False,
        ),
        (
            "numeric-wrapper-alternative",
            MONEY_RULE,
            money_case({"allOf": [MONEY], "anyOf": [{"type": "number"}]}),
            False,
        ),
    ]
    for field in ("amount", "currency"):
        missing = copy.deepcopy(MONEY)
        del missing["properties"][field]
        result.append((f"missing-{field}", MONEY_RULE, money_case(missing), False))
        optional = copy.deepcopy(MONEY)
        optional["required"].remove(field)
        result.append((f"optional-{field}", MONEY_RULE, money_case(optional), False))
        for field_type in ("number", "integer", "object"):
            wrong_type = copy.deepcopy(MONEY)
            wrong_type["properties"][field] = {"type": field_type}
            result.append((f"{field}-{field_type}", MONEY_RULE, money_case(wrong_type), False))
    # Every scalar/shape rejection must survive the same wrapper as the current bundle.
    for name, rule, fixture, valid in list(result):
        schema = fixture["components"]["schemas"]["Purchase"]["properties"]["total_amount"]
        for referenced in (False, True):
            kind = "referenced" if referenced else "inline"
            result.append((f"{kind}-{name}", rule, wrapped_money_case(schema, referenced=referenced), valid))
    result.append(
        ("referenced-nonnullable-money", MONEY_RULE, wrapped_money_case(MONEY, referenced=True, nullable=False), True)
    )
    result.extend(
        [
            (
                "payment-date",
                TIME_RULE,
                timestamp_case("ExpensePayment", "paid_at", {"type": "string", "format": "date"}),
                True,
            ),
            (
                "referenced-payment-date",
                TIME_RULE,
                timestamp_case("ExpensePayment", "paid_at", {"type": "string", "format": "date"}, referenced=True),
                True,
            ),
            (
                "other-payment-date",
                TIME_RULE,
                timestamp_case("OtherPayment", "paid_at", {"type": "string", "format": "date"}),
                False,
            ),
            (
                "created-date",
                TIME_RULE,
                timestamp_case("ExpensePayment", "created_at", {"type": "string", "format": "date"}),
                False,
            ),
            (
                "timestamp",
                TIME_RULE,
                timestamp_case("OtherPayment", "created_at", {"type": "string", "format": "date-time"}),
                True,
            ),
            (
                "missing-timestamp-format",
                TIME_RULE,
                timestamp_case("OtherPayment", "created_at", {"type": "string"}),
                False,
            ),
            (
                "payment-date-guard",
                DATE_RULE,
                timestamp_case("ExpensePayment", "paid_at", {"type": "string", "format": "date"}),
                True,
            ),
            (
                "payment-datetime-rejected",
                DATE_RULE,
                timestamp_case("ExpensePayment", "paid_at", {"type": "string", "format": "date-time"}),
                False,
            ),
            (
                "payment-number-rejected",
                DATE_RULE,
                timestamp_case("ExpensePayment", "paid_at", {"type": "number", "format": "date"}),
                False,
            ),
            ("304-options", STATUS_RULE, response_case("200", "304", "400"), True),
            ("unsupported-302", STATUS_RULE, response_case("200", "302", "400"), False),
            ("4xx-lower-bound", ERROR_RULE, response_case("200", "400"), True),
            ("4xx-upper-bound", ERROR_RULE, response_case("200", "499"), True),
            ("no-4xx", ERROR_RULE, response_case("200", "304", "500"), False),
            ("default-not-4xx", ERROR_RULE, response_case("200", "default"), False),
            ("4xx-wildcard-not-status", ERROR_RULE, response_case("200", "4XX"), False),
            ("four-digit-not-status", ERROR_RULE, response_case("200", "4000"), False),
        ]
    )
    for status in ("405", "412", "422", "428", "429"):
        result.append((f"documents-{status}", ERROR_RULE, response_case("200", status), True))
    return result


CASES = cases()


@pytest.fixture(scope="module")
def diagnostics(tmp_path_factory: pytest.TempPathFactory) -> list[dict]:
    executable = shutil.which("npx.cmd") or shutil.which("npx")
    assert executable, "Pinned Spectral CLI requires npx; this gate must not silently skip."
    directory = tmp_path_factory.mktemp("spectral")
    for name, _rule, fixture, _valid in CASES:
        path = directory / f"{name}.json"
        path.write_text(json.dumps(fixture), encoding="utf-8")
    completed = subprocess.run(
        [
            executable,
            "--yes",
            "@stoplight/spectral-cli@6.17.0",
            "lint",
            # A glob avoids cmd.exe's command-length limit as the matrix grows.
            f"{directory.as_posix()}/*.json",
            "--ruleset",
            str(ROOT / ".spectral.yaml"),
            "--format",
            "json",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    assert completed.returncode in (0, 1), completed.stderr
    assert completed.stdout.strip(), completed.stderr
    findings = json.loads(completed.stdout)
    assert isinstance(findings, list), completed.stdout
    return findings


@pytest.mark.parametrize("name,rule,fixture,valid", CASES, ids=[case[0] for case in CASES])
def test_spectral_contract(name: str, rule: str, fixture: dict, valid: bool, diagnostics: list[dict]) -> None:
    """Fails if the targeted rule accepts a malformed schema or rejects a contract-valid one."""
    findings = [item for item in diagnostics if Path(item["source"]).stem == name and item["code"] == rule]
    assert bool(findings) is not valid, findings


def test_audited_rule_severities_are_preserved() -> None:
    """Fails if a fix reduces any audited rule's severity."""
    rules = yaml.safe_load((ROOT / ".spectral.yaml").read_text(encoding="utf-8"))["rules"]
    for rule in (MONEY_RULE, TIME_RULE, DATE_RULE):
        assert rules[rule]["severity"] == "error"
    for rule in (STATUS_RULE, ERROR_RULE):
        assert rules[rule]["severity"] == "warn"
