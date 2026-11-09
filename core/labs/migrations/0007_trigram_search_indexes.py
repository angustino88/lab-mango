"""Migration adding concurrent pg_trgm search indexes to large-class resources (ADR 002, section 20.4)."""

from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("labs", "0006_department_equipmentinterface_material_and_more"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="equipmenttype",
            index=GinIndex(fields=["name"], opclasses=["gin_trgm_ops"], name="equipment_type_name_trgm_idx"),
        ),
        AddIndexConcurrently(
            model_name="equipmentmanufacturer",
            index=GinIndex(fields=["name"], opclasses=["gin_trgm_ops"], name="equipment_mfr_name_trgm_idx"),
        ),
        AddIndexConcurrently(
            model_name="equipmentproductmodel",
            index=GinIndex(fields=["name"], opclasses=["gin_trgm_ops"], name="equipment_model_name_trgm_idx"),
        ),
        AddIndexConcurrently(
            model_name="labproject",
            index=GinIndex(fields=["project_name"], opclasses=["gin_trgm_ops"], name="lab_project_name_trgm_idx"),
        ),
        AddIndexConcurrently(
            model_name="city",
            index=GinIndex(fields=["name"], opclasses=["gin_trgm_ops"], name="city_name_trgm_idx"),
        ),
        AddIndexConcurrently(
            model_name="building",
            index=GinIndex(fields=["name"], opclasses=["gin_trgm_ops"], name="building_name_trgm_idx"),
        ),
    ]
