"""Seed the v1 telemetry metrics (Q17). Reverse removes them; it fails if channels already use them."""

from decimal import Decimal

from django.db import migrations

V1_METRICS = (
    {
        "key": "temperature_c",
        "name": "Temperature",
        "unit": "°C",
        "combine": "mean",
        "value_min": Decimal("-273.15"),
        "value_max": None,
        "kind": "gauge",
        "aggregation": "mean",
        "decimals": 2,
    },
    {
        "key": "humidity_percent",
        "name": "Relative humidity",
        "unit": "%",
        "combine": "mean",
        "value_min": Decimal("0"),
        "value_max": Decimal("100"),
        "kind": "gauge",
        "aggregation": "mean",
        "decimals": 1,
    },
    {
        "key": "power_w",
        "name": "Active power",
        "unit": "W",
        "combine": "sum",
        "value_min": Decimal("0"),
        "value_max": None,
        "kind": "gauge",
        "aggregation": "mean",
        "decimals": 1,
    },
)


def seed_metrics(apps, schema_editor):
    metric_model = apps.get_model("labs", "MetricDefinition")
    for metric in V1_METRICS:
        values = {field: value for field, value in metric.items() if field != "key"}
        metric_model.objects.update_or_create(key=metric["key"], defaults=values)


def remove_metrics(apps, schema_editor):
    metric_model = apps.get_model("labs", "MetricDefinition")
    metric_model.objects.filter(key__in=[metric["key"] for metric in V1_METRICS]).delete()


class Migration(migrations.Migration):
    dependencies = [("labs", "0002_telemetry_configuration")]

    operations = [migrations.RunPython(seed_metrics, remove_metrics)]
